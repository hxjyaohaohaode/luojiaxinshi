"""Offline, human-adjudicated MVP corpus freezing and scoring. No provider calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import statistics
import sys
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.console import configure_text_output

FACT_KEYS = {'theme', 'audience', 'dates', 'actions', 'materials', 'submission', 'location', 'contact'}
CATEGORIES = {'application', 'materials', 'activity'}
PROTOCOL = 'mvp-human-matching-v1'
Identifier = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_.-]{1,80}$')]
Digest = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
Count = Annotated[int, Field(strict=True, ge=0)]
ErrorTag = Literal['actor', 'deadline', 'materials', 'submission', 'condition', 'dependency',
                   'obligation', 'unsupported', 'granularity', 'other']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def aware(value):
    require(value.tzinfo is not None and value.utcoffset() is not None, 'Timestamps need a timezone')
    return value


def unique(values, label):
    require(len(values) == len(set(values)), f'Duplicate {label}')


class Source(Contract):
    id: Identifier
    kind: Literal['body', 'attachment']
    path: Text
    provenance: Text
    acquired_at: datetime

    @model_validator(mode='after')
    def timestamp(self):
        aware(self.acquired_at)
        return self


class Citation(Contract):
    source_id: Identifier
    locator: Text
    quote: Text


class ExpectedFact(Contract):
    state: Literal['stated', 'not_stated', 'conflicting']
    value: str = Field(max_length=4000)
    evidence: list[Citation] = Field(max_length=50)

    @model_validator(mode='after')
    def consistent(self):
        if self.state == 'not_stated':
            require(not self.value and not self.evidence, 'Unknown facts must not invent a value or quote')
        else:
            require(bool(self.value and self.evidence), 'Stated/conflicting facts need a value and evidence')
        return self


class ExpectedTask(Contract):
    id: Identifier
    action: Text
    actor: Text
    obligation: Literal['required', 'optional', 'verification']
    due_date: str | None
    due_time: str | None
    conditions: list[Text] = Field(max_length=30)
    depends_on: list[Identifier] = Field(max_length=30)
    materials: list[Text] = Field(max_length=50)
    submission: str = Field(max_length=2000)
    location: str = Field(max_length=1000)
    contact: str = Field(max_length=1000)
    evidence: list[Citation] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def dates(self):
        if self.due_date is not None:
            require(date.fromisoformat(self.due_date).isoformat() == self.due_date, 'Use YYYY-MM-DD')
        if self.due_time is not None:
            from datetime import time
            require(self.due_date is not None, 'A deadline time needs a date')
            require(time.fromisoformat(self.due_time).strftime('%H:%M') == self.due_time, 'Use HH:MM')
        unique(self.depends_on, 'task dependency')
        return self


class Gold(Contract):
    format_version: Literal[1]
    annotation_kind: Literal['human_independent']
    annotator_id: Identifier
    annotated_at: datetime
    prepared_without_model_output: StrictBool
    task_unit_rule: Text
    facts: dict[str, ExpectedFact]
    tasks: list[ExpectedTask] = Field(max_length=200)

    @model_validator(mode='after')
    def complete(self):
        aware(self.annotated_at)
        require(self.prepared_without_model_output, 'Gold must precede model-output inspection')
        require(set(self.facts) == FACT_KEYS, 'Gold needs exactly the eight fact categories')
        unique([task.id for task in self.tasks], 'gold task ID')
        graph = {task.id: set(task.depends_on) for task in self.tasks}
        require(all(deps <= graph.keys() for deps in graph.values()), 'Unknown gold dependency')
        pending = dict(graph)
        while pending:
            ready = {key for key, deps in pending.items() if not deps & pending.keys()}
            require(bool(ready), 'Cyclic gold dependency')
            pending = {key: deps for key, deps in pending.items() if key not in ready}
        return self


class Case(Contract):
    id: Identifier
    family_id: Identifier
    split: Literal['development', 'holdout']
    category: Literal['application', 'materials', 'activity']
    source_kind: Literal['real_notice']
    source_use_confirmed: StrictBool
    materials_complete: StrictBool
    profile_kind: Literal['synthetic', 'consented_self_report']
    profile: dict[str, str] = Field(max_length=30)
    sources: list[Source] = Field(min_length=1, max_length=100)
    gold_path: Text

    @model_validator(mode='after')
    def complete(self):
        require(self.source_use_confirmed and self.materials_complete, 'Source rights/completeness need human confirmation')
        unique([source.id for source in self.sources], 'source ID')
        require(sum(source.kind == 'body' for source in self.sources) == 1, 'Each case needs exactly one body')
        return self


class Corpus(Contract):
    format_version: Literal[1]
    dataset_id: Identifier
    protocol: Literal['mvp-human-matching-v1']
    cases: list[Case] = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def split_integrity(self):
        unique([case.id for case in self.cases], 'case ID')
        families = {}
        for case in self.cases:
            require(families.setdefault(case.family_id, case.split) == case.split,
                    'A notice family cannot cross development and holdout')
        for split, minimum in [('development', 10), ('holdout', 20)]:
            selected = [case for case in self.cases if case.split == split]
            require(len(selected) >= minimum, f'{split} needs at least {minimum} notices')
            require({case.category for case in selected} == CATEGORIES, f'{split} must cover all three categories')
        return self


class FileStamp(Contract):
    sha256: Digest
    size: Count


class Snapshot(Contract):
    format_version: Literal[1]
    protocol: Literal['mvp-human-matching-v1']
    frozen_at: datetime
    evaluator_sha256: Digest
    manifest_path: Text
    corpus: Corpus
    gold: dict[str, Gold]
    files: dict[str, FileStamp]
    snapshot_sha256: Digest


class RunResult(Contract):
    case_id: Identifier
    status: Literal['complete', 'error', 'unsupported', 'timeout', 'cancelled', 'invalid_output']
    started_at: datetime
    finished_at: datetime
    output_path: Text | None = None
    output_sha256: Digest | None = None
    failure_note: str = Field(default='', max_length=2000)
    provider_requests: Count | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cached_input_tokens: Count | None = None

    @model_validator(mode='after')
    def valid(self):
        require(aware(self.finished_at) >= aware(self.started_at), 'Negative attempt duration')
        require((self.output_path is None) == (self.output_sha256 is None), 'Output path and hash must appear together')
        if self.status == 'complete':
            require(self.output_path is not None and not self.failure_note, 'Complete result needs its original output')
        else:
            require(bool(self.failure_note), 'Failures need an explanation')
        if self.cached_input_tokens is not None and self.input_tokens is not None:
            require(self.cached_input_tokens <= self.input_tokens, 'Cached input exceeds total input')
        return self


class ModelConfig(Contract):
    provider: Text
    extraction_model: Text
    review_model: Text
    processing_mode: Literal['configured', 'fast']
    extraction_thinking: Literal['enabled', 'disabled']
    review_thinking: Literal['enabled', 'disabled']
    input_budget: Count
    extraction_output_budget: Count
    review_output_budget: Count


class Run(Contract):
    format_version: Literal[1]
    run_id: Identifier
    snapshot_sha256: Digest
    split: Literal['development', 'holdout']
    output_stage: Literal['model_draft_before_human_edit']
    started_at: datetime
    finished_at: datetime
    config: ModelConfig
    implementation_sha256: dict[str, Digest] = Field(min_length=1)
    results: list[RunResult] = Field(max_length=2000)

    @model_validator(mode='after')
    def consistent(self):
        require(aware(self.finished_at) >= aware(self.started_at), 'Negative run duration')
        unique([result.case_id for result in self.results], 'run case ID; reruns need a separate run')
        require(all(self.started_at <= item.started_at <= item.finished_at <= self.finished_at
                    for item in self.results), 'Attempt timestamps exceed the run interval')
        return self


class TaskJudgment(Contract):
    task_index: Count
    gold_task_id: Identifier | None
    verdict: Literal['correct', 'incorrect', 'extra']
    errors: list[ErrorTag] = Field(max_length=10)
    note: Text

    @model_validator(mode='after')
    def consistent(self):
        unique(self.errors, 'error tag')
        if self.verdict == 'correct':
            require(self.gold_task_id is not None and not self.errors, 'Correct tasks need a gold match and no errors')
        else:
            require(bool(self.errors), 'Incorrect/extra tasks need error tags')
            require((self.gold_task_id is None) == (self.verdict == 'extra'), 'Extra tasks have no gold match')
        return self


class CaseJudgment(Contract):
    case_id: Identifier
    output_sha256: Digest
    facts: dict[str, Literal['correct', 'incorrect']]
    tasks: list[TaskJudgment] = Field(max_length=200)
    note: Text

    @model_validator(mode='after')
    def complete(self):
        require(set(self.facts) == FACT_KEYS, 'Adjudicate every fact category, including empty values')
        unique([task.task_index for task in self.tasks], 'judged task index')
        return self


class Judgments(Contract):
    format_version: Literal[1]
    run_id: Identifier
    snapshot_sha256: Digest
    adjudication_kind: Literal['human']
    adjudicator_id: Identifier
    adjudicated_at: datetime
    all_personal_tasks_reviewed: StrictBool
    cases: list[CaseJudgment] = Field(max_length=2000)

    @model_validator(mode='after')
    def complete(self):
        aware(self.adjudicated_at)
        require(self.all_personal_tasks_reviewed, 'Human review must cover all personal predictions')
        unique([case.case_id for case in self.cases], 'judged case ID')
        return self


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def checked_path(root, relative):
    windows = PureWindowsPath(relative)
    require(not windows.drive and not windows.is_absolute() and not Path(relative).is_absolute(), 'Use relative paths within the corpus directory')
    require(':' not in relative, 'Alternate data streams are not corpus files')
    require('..' not in windows.parts, 'Parent traversal is not allowed')
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), 'Path escapes the corpus directory')
    return path


def read_json(path):
    def object_pairs(pairs):
        unique([key for key, _ in pairs], 'JSON key')
        return dict(pairs)
    def invalid_constant(value):
        raise ValueError(f'Non-finite JSON constant: {value}')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def stamp_file(path):
    require(path.is_file(), f'Missing file: {path.name}')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    require(size > 0, f'Empty file: {path.name}')
    return {'sha256': digest.hexdigest(), 'size': size}


def build_snapshot(root, manifest_path, now=None):
    root = Path(root).resolve()
    frozen_at = aware(now or datetime.now(timezone.utc))
    manifest_file = checked_path(root, manifest_path)
    corpus = Corpus.model_validate(read_json(manifest_file))
    files = {manifest_path: stamp_file(manifest_file)}
    gold = {}
    bodies = set()
    for case in corpus.cases:
        gold_file = checked_path(root, case.gold_path)
        annotation = Gold.model_validate(read_json(gold_file))
        require(annotation.annotated_at <= frozen_at, 'Gold annotation cannot be after freezing')
        citations = [citation for fact in annotation.facts.values() for citation in fact.evidence]
        citations.extend(citation for task in annotation.tasks for citation in task.evidence)
        source_ids = {source.id for source in case.sources}
        require(all(citation.source_id in source_ids for citation in citations), 'Gold cites an unknown source')
        files[case.gold_path] = stamp_file(gold_file)
        gold[case.id] = annotation.model_dump(mode='json')
        for source in case.sources:
            require(source.acquired_at <= frozen_at, 'Source acquisition cannot be after freezing')
            path = checked_path(root, source.path)
            files[source.path] = stamp_file(path)
            plain_text = None
            if path.suffix.lower() in {'.txt', '.md'}:
                plain_text = path.read_text(encoding='utf-8-sig')
                require(bool(plain_text.strip()), 'Empty source text')
                require(all(citation.quote.replace('\r\n', '\n') in plain_text
                            for citation in citations if citation.source_id == source.id),
                        'Gold quote does not occur in its plain-text source')
            if source.kind == 'body':
                body_hash = files[source.path]['sha256']
                if plain_text is not None:
                    body_hash = sha256(' '.join(plain_text.split()).encode('utf-8'))
                require(body_hash not in bodies, 'Duplicate notice body; formatting-only copies are not new cases')
                bodies.add(body_hash)
    snapshot = {'format_version': 1, 'protocol': PROTOCOL, 'frozen_at': frozen_at.isoformat(),
                'evaluator_sha256': sha256(Path(__file__).read_bytes()),
                'manifest_path': manifest_path, 'corpus': corpus.model_dump(mode='json'), 'gold': gold, 'files': files}
    snapshot['snapshot_sha256'] = sha256(canonical(snapshot))
    return snapshot


def verify_snapshot(root, snapshot):
    Snapshot.model_validate(snapshot)
    digest = snapshot['snapshot_sha256']
    require(digest == sha256(canonical({key: value for key, value in snapshot.items() if key != 'snapshot_sha256'})),
            'Frozen snapshot checksum mismatch')
    for name, expected in snapshot['files'].items():
        require(stamp_file(checked_path(root, name)) == expected,
                'Frozen file has changed; preserve the original evidence and create a new dataset version')
    rebuilt = build_snapshot(root, snapshot['manifest_path'], datetime.fromisoformat(snapshot['frozen_at']))
    require(rebuilt == snapshot, 'Frozen manifest, annotation, source or evaluator has changed; preserve this evaluation and create a new dataset version')


def personal_indexes(root, result):
    require(stamp_file(checked_path(root, result.output_path))['sha256'] == result.output_sha256, 'Run output checksum mismatch')
    output = read_json(checked_path(root, result.output_path))
    require(isinstance(output, dict), 'Complete output must be a JSON object')
    draft = output.get('draft', output)
    require(isinstance(draft, dict) and isinstance(draft.get('facts'), dict) and set(draft['facts']) == FACT_KEYS,
            'Malformed complete output: use invalid_output status, which remains in the denominator')
    require(all(isinstance(value, dict) and isinstance(value.get('value'), str) for value in draft['facts'].values()), 'Malformed fact values')
    tasks = draft.get('tasks')
    require(isinstance(tasks, list) and all(isinstance(task, dict) and isinstance(task.get('title'), str) and bool(task['title'].strip())
            and task.get('scope') in {'personal', 'other', 'uncertain'} for task in tasks), 'Malformed complete tasks')
    return {index for index, task in enumerate(tasks) if task['scope'] == 'personal'}


def ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else None


def aggregate(rows):
    tp = sum(row['task_tp'] for row in rows)
    fp = sum(row['task_fp'] for row in rows)
    fn = sum(row['task_fn'] for row in rows)
    fact_correct = sum(row['fact_correct'] for row in rows)
    return {'cases': len(rows), 'status_counts': dict(Counter(row['status'] for row in rows)),
            'fact_correct': fact_correct, 'fact_denominator': 8 * len(rows),
            'fact_accuracy': ratio(fact_correct, 8 * len(rows)),
            'task_tp': tp, 'task_fp': fp, 'task_fn': fn,
            'task_precision': ratio(tp, tp + fp), 'task_recall': ratio(tp, tp + fn),
            'duplicate_predictions': sum(row['duplicate_predictions'] for row in rows)}


def score(root, snapshot, run_data, judgment_data):
    root = Path(root).resolve()
    verify_snapshot(root, snapshot)
    run = Run.model_validate(run_data)
    judgments = Judgments.model_validate(judgment_data)
    require(run.snapshot_sha256 == judgments.snapshot_sha256 == snapshot['snapshot_sha256'], 'Dataset snapshot does not match')
    require(run.run_id == judgments.run_id, 'Judgments belong to a different run')
    require(run.started_at >= datetime.fromisoformat(snapshot['frozen_at']), 'Run began before the dataset was frozen')
    require(judgments.adjudicated_at >= run.finished_at, 'Judgment predates the run')
    cases = [case for case in snapshot['corpus']['cases'] if case['split'] == run.split]
    allowed = {case['id'] for case in cases}
    results = {item.case_id: item for item in run.results}
    reviewed = {item.case_id: item for item in judgments.cases}
    require(results.keys() <= allowed, 'Run includes an unknown case or a case from another split')
    require(reviewed.keys() == {key for key, result in results.items() if result.status == 'complete'},
            'Every complete output needs human adjudication; failures must not receive successful judgments')
    rows = []
    for case in cases:
        expected = {task['id'] for task in snapshot['gold'][case['id']]['tasks']}
        result = results.get(case['id'])
        row = {'case_id': case['id'], 'category': case['category'], 'family_id': case['family_id'],
               'status': result.status if result else 'not_run', 'fact_correct': 0,
               'fact_correct_by_category': {key: 0 for key in sorted(FACT_KEYS)},
               'task_tp': 0, 'task_fp': 0, 'task_fn': len(expected), 'duplicate_predictions': 0, 'error_tags': {}}
        if result and result.output_path:
            require(stamp_file(checked_path(root, result.output_path))['sha256'] == result.output_sha256, 'Output checksum mismatch')
        if result and result.status == 'complete':
            judgment = reviewed[case['id']]
            require(judgment.output_sha256 == result.output_sha256, 'Human judgment is for a different output')
            require({task.task_index for task in judgment.tasks} == personal_indexes(root, result),
                    'Judge every personal task exactly once, using its original zero-based index')
            matched = set()
            tags = Counter()
            for task in judgment.tasks:
                require(task.gold_task_id is None or task.gold_task_id in expected, 'Unknown gold task match')
                tags.update(task.errors)
                if task.verdict == 'correct':
                    if task.gold_task_id in matched:
                        row['duplicate_predictions'] += 1
                    matched.add(task.gold_task_id)
            row.update(task_tp=len(matched), task_fp=len(judgment.tasks) - len(matched), task_fn=len(expected - matched),
                       fact_correct=sum(value == 'correct' for value in judgment.facts.values()),
                       fact_correct_by_category={key: int(value == 'correct') for key, value in judgment.facts.items()},
                       error_tags=dict(tags))
        rows.append(row)
    durations = [(item.finished_at - item.started_at).total_seconds() for item in run.results]
    totals = aggregate(rows)
    totals['fact_categories'] = {key: {'correct': sum(row['fact_correct_by_category'][key] for row in rows),
                                      'denominator': len(rows)} for key in sorted(FACT_KEYS)}
    totals['error_tags'] = dict(sum((Counter(row['error_tags']) for row in rows), Counter()))
    usage = {}
    for field in ['provider_requests', 'input_tokens', 'output_tokens', 'cached_input_tokens']:
        values = [getattr(item, field) for item in run.results if getattr(item, field) is not None]
        usage[field] = {'known_total': sum(values) if values else None, 'known_cases': len(values),
                        'unknown_attempted_cases': len(run.results) - len(values)}
    return {'format_version': 1, 'protocol': PROTOCOL, 'run_id': run.run_id, 'split': run.split,
            'snapshot_sha256': snapshot['snapshot_sha256'], 'run_sha256': sha256(canonical(run_data)),
            'judgments_sha256': sha256(canonical(judgment_data)), 'all_cases_attempted': len(results) == len(cases),
            'human_adjudicated_successes': len(reviewed), 'model_calls_by_evaluator': 0,
            'scope': 'Strict one-to-one personal-task matching under the frozen human task-unit rule; missing/failed cases remain. No user-study, device, or total-handling-time claim.',
            'totals': totals, 'categories': {key: aggregate([row for row in rows if row['category'] == key]) for key in sorted(CATEGORIES)},
            'families': len({case['family_id'] for case in cases}), 'usage': usage,
            'attempt_duration_seconds': {'count': len(durations), 'median': statistics.median(durations) if durations else None,
                                         'min': min(durations) if durations else None, 'max': max(durations) if durations else None},
            'cases': rows}


def write_new(path, value):
    # Exclusive creation preserves original snapshots and failed attempts.
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    configure_text_output()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['validate', 'freeze', 'verify', 'score']:
        command = commands.add_parser(name)
        command.add_argument('--root', type=Path, required=True, help='Private directory containing the corpus and evaluation files')
        if name in {'validate', 'freeze'}:
            command.add_argument('--manifest', required=True, help='Corpus manifest, relative to root')
        else:
            command.add_argument('--frozen', required=True, help='Frozen snapshot, relative to root')
        if name == 'score':
            command.add_argument('--run', required=True)
            command.add_argument('--judgments', required=True)
        if name in {'freeze', 'score'}:
            command.add_argument('--output', required=True, help='New JSON path, relative to root; existing files are never overwritten')
    schema = commands.add_parser('schema')
    schema.add_argument('kind', choices=['corpus', 'gold', 'run', 'judgments'])
    args = parser.parse_args()
    try:
        if args.command == 'schema':
            print(json.dumps({'corpus': Corpus, 'gold': Gold, 'run': Run, 'judgments': Judgments}[args.kind].model_json_schema(), ensure_ascii=False, indent=2))
            return
        root = args.root.resolve()
        require(root.is_dir(), 'Corpus root directory does not exist')
        if args.command in {'validate', 'freeze'}:
            report = build_snapshot(root, args.manifest)
        else:
            snapshot = read_json(checked_path(root, args.frozen))
            if args.command == 'verify':
                verify_snapshot(root, snapshot)
            report = snapshot if args.command == 'verify' else score(root, snapshot,
                read_json(checked_path(root, args.run)), read_json(checked_path(root, args.judgments)))
        if args.command in {'freeze', 'score'}:
            output = checked_path(root, args.output)
            require(output.suffix == '.json', 'Evidence output must use a .json filename')
            write_new(output, report)
        summary = {'command': args.command, 'snapshot_sha256': report['snapshot_sha256'], 'model_calls': 0}
        if args.command == 'score':
            summary.update(all_cases_attempted=report['all_cases_attempted'], totals=report['totals'])
        else:
            summary['cases'] = len(report['corpus']['cases'])
        print(json.dumps(summary, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        # Pydantic errors can echo input text. Print paths/types only, never source excerpts.
        if hasattr(exc, 'errors'):
            error = [{'location': list(item['loc']), 'type': item['type']} for item in exc.errors()]
        else:
            error = str(exc)
        print(json.dumps({'error': error, 'model_calls': 0}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
