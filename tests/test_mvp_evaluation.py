"""Synthetic contract tests only; no genuine notices, annotators or provider calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from scripts import evaluate_mvp as evaluation


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    # These test declarations deliberately emulate human fields. They prove only
    # validator behavior, never that software can authenticate a human reviewer.
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: pytest.fail('Offline evaluator opened a connection'))
    cases = []
    for index in range(30):
        identity = f'n{index:02}'
        (tmp_path / f'{identity}.txt').write_text(f'虚构工程夹具 {index}，准备材料，再提交申请。', encoding='utf-8')
        citation = {'source_id': 'body', 'locator': '第 1 段', 'quote': '准备材料，再提交申请'}
        tasks = []
        for task_id in ['prepare', 'submit']:
            tasks.append({'id': task_id, 'action': task_id, 'actor': '本人', 'obligation': 'optional',
                          'due_date': None, 'due_time': None, 'conditions': [],
                          'depends_on': ['prepare'] if task_id == 'submit' else [], 'materials': [],
                          'submission': '', 'location': '', 'contact': '', 'evidence': [citation]})
        gold = {'format_version': 1, 'annotation_kind': 'human_independent', 'annotator_id': 'synthetic-test-role',
                'annotated_at': '2026-01-01T00:00:00+00:00', 'prepared_without_model_output': True,
                'task_unit_rule': '虚构契约测试：准备材料和提交申请分别作为一步。',
                'facts': {key: {'state': 'not_stated', 'value': '', 'evidence': []} for key in evaluation.FACT_KEYS},
                'tasks': tasks}
        save(tmp_path / f'{identity}.gold.json', gold)
        cases.append({'id': identity, 'family_id': identity, 'split': 'development' if index < 10 else 'holdout',
                      'category': ['application', 'materials', 'activity'][index % 3], 'source_kind': 'real_notice',
                      'source_use_confirmed': True, 'materials_complete': True, 'profile_kind': 'synthetic',
                      'profile': {'level': '虚构测试学生'}, 'sources': [
                          {'id': 'body', 'kind': 'body', 'path': f'{identity}.txt', 'provenance': '虚构工程夹具',
                           'acquired_at': '2026-01-01T00:00:00+00:00'}], 'gold_path': f'{identity}.gold.json'})
    manifest = {'format_version': 1, 'dataset_id': 'synthetic-contract-test', 'protocol': evaluation.PROTOCOL, 'cases': cases}
    save(tmp_path / 'corpus.json', manifest)
    return tmp_path, manifest


def freeze(corpus):
    return evaluation.build_snapshot(corpus[0], 'corpus.json', NOW)


def example_run(root, frozen):
    started = datetime.fromisoformat(frozen['frozen_at']) + timedelta(seconds=1)
    ended = started + timedelta(seconds=10)
    results, reviewed = [], []
    for offset, status in enumerate(['complete'] * 3 + ['error', 'timeout', 'unsupported', 'cancelled', 'invalid_output']):
        identity = f'n{10 + offset:02}'
        result = {'case_id': identity, 'status': status, 'started_at': started.isoformat(), 'finished_at': ended.isoformat()}
        if status == 'complete':
            tasks = [{'title': f'虚构步骤 {i}', 'scope': 'personal'} for i in range([4, 2, 0][offset])]
            tasks.extend([{'title': '学院审核', 'scope': 'other'}, {'title': '待核实', 'scope': 'uncertain'}])
            output = {'draft': {'facts': {key: {'value': ''} for key in evaluation.FACT_KEYS}, 'tasks': tasks}}
            save(root / f'{identity}.output.json', output)
            digest = evaluation.stamp_file(root / f'{identity}.output.json')['sha256']
            result.update(output_path=f'{identity}.output.json', output_sha256=digest, provider_requests=2,
                          input_tokens=100, output_tokens=50)
            judgments = [{'task_index': 0, 'gold_task_id': 'prepare', 'verdict': 'correct', 'errors': [], 'note': '虚构匹配：准备材料'},
                         {'task_index': 1, 'gold_task_id': 'submit', 'verdict': 'correct', 'errors': [], 'note': '虚构匹配：提交申请'}]
            if offset == 0:
                judgments[1].update(gold_task_id='prepare', note='重复准备步骤')
                judgments.extend([
                    {'task_index': 2, 'gold_task_id': 'submit', 'verdict': 'incorrect', 'errors': ['deadline'], 'note': '虚构错误期限'},
                    {'task_index': 3, 'gold_task_id': None, 'verdict': 'extra', 'errors': ['unsupported'], 'note': '虚构多余申请'}])
            if offset == 2:
                judgments = []
            facts = {key: 'correct' for key in evaluation.FACT_KEYS}
            if offset == 0:
                facts['dates'] = 'incorrect'
            reviewed.append({'case_id': identity, 'output_sha256': digest, 'facts': facts, 'tasks': judgments, 'note': '仅用于评分器工程测试'})
        else:
            result['failure_note'] = f'Synthetic {status}'
        results.append(result)
    run = {'format_version': 1, 'run_id': 'synthetic-run', 'snapshot_sha256': frozen['snapshot_sha256'], 'split': 'holdout',
           'output_stage': 'model_draft_before_human_edit',
           'started_at': started.isoformat(), 'finished_at': ended.isoformat(),
           'config': {'provider': 'synthetic-no-network', 'extraction_model': 'synthetic', 'review_model': 'synthetic',
                      'processing_mode': 'configured', 'extraction_thinking': 'enabled', 'review_thinking': 'enabled',
                      'input_budget': 100, 'extraction_output_budget': 100, 'review_output_budget': 100},
           'implementation_sha256': {'synthetic-code': '0' * 64}, 'results': results}
    judgments = {'format_version': 1, 'run_id': run['run_id'], 'snapshot_sha256': frozen['snapshot_sha256'],
                 'adjudication_kind': 'human', 'adjudicator_id': 'synthetic-test-role',
                 'adjudicated_at': (ended + timedelta(seconds=1)).isoformat(), 'all_personal_tasks_reviewed': True, 'cases': reviewed}
    return run, judgments


def test_freeze_is_reproducible_and_verifies_original_bytes(corpus):
    root, _ = corpus
    frozen = freeze(corpus)
    assert len(frozen['files']) == 61 and len(frozen['gold']) == 30
    assert frozen == freeze(corpus)
    assert evaluation.verify_snapshot(root, frozen) is None
    (root / 'n20.txt').write_text('改动了被冻结的原件', encoding='utf-8')
    with pytest.raises(ValueError, match='has changed'):
        evaluation.verify_snapshot(root, frozen)


@pytest.mark.parametrize('mutation', ['minimum', 'category', 'family', 'duplicate_id', 'not_real', 'incomplete', 'no_rights', 'no_body'])
def test_corpus_gates_are_not_optional(corpus, mutation):
    root, manifest = corpus
    case = manifest['cases'][10]
    if mutation == 'minimum': manifest['cases'].pop()
    elif mutation == 'category':
        for item in manifest['cases']: item['category'] = 'activity'
    elif mutation == 'family': case['family_id'] = 'n00'
    elif mutation == 'duplicate_id': case['id'] = 'n00'
    elif mutation == 'not_real': case['source_kind'] = 'synthetic'
    elif mutation == 'incomplete': case['materials_complete'] = False
    elif mutation == 'no_rights': case['source_use_confirmed'] = False
    elif mutation == 'no_body': case['sources'][0]['kind'] = 'attachment'
    save(root / 'corpus.json', manifest)
    with pytest.raises(ValueError): freeze(corpus)


@pytest.mark.parametrize('mutation', ['ai_gold', 'posthoc', 'future', 'missing_fact', 'unknown_source', 'invented_quote', 'cycle', 'unknown_dependency', 'guessed_time'])
def test_gold_requires_independent_complete_and_coherent_annotations(corpus, mutation):
    root, _ = corpus
    gold = evaluation.read_json(root / 'n00.gold.json')
    if mutation == 'ai_gold': gold['annotation_kind'] = 'ai_generated'
    elif mutation == 'posthoc': gold['prepared_without_model_output'] = False
    elif mutation == 'future': gold['annotated_at'] = '2027-01-01T00:00:00+00:00'
    elif mutation == 'missing_fact': gold['facts'].pop('dates')
    elif mutation == 'unknown_source': gold['tasks'][0]['evidence'][0]['source_id'] = 'not-a-source'
    elif mutation == 'invented_quote': gold['tasks'][0]['evidence'][0]['quote'] = '并不存在的通知内容'
    elif mutation == 'cycle': gold['tasks'][0]['depends_on'] = ['submit']
    elif mutation == 'unknown_dependency': gold['tasks'][0]['depends_on'] = ['nonexistent']
    elif mutation == 'guessed_time': gold['tasks'][0]['due_time'] = '23:59'
    save(root / 'n00.gold.json', gold)
    with pytest.raises(ValueError): freeze(corpus)


@pytest.mark.parametrize('change', ['body', 'gold', 'manifest', 'checksum', 'evaluator'])
def test_frozen_artifact_drift_cannot_be_silently_rescored(corpus, change):
    root, _ = corpus
    frozen = freeze(corpus)
    if change in {'body', 'gold', 'manifest'}:
        name = {'body': 'n00.txt', 'gold': 'n00.gold.json', 'manifest': 'corpus.json'}[change]
        with (root / name).open('a', encoding='utf-8') as file: file.write('\n')
    elif change == 'checksum': frozen['snapshot_sha256'] = '0' * 64
    else:
        frozen['evaluator_sha256'] = '0' * 64
        frozen['snapshot_sha256'] = evaluation.sha256(evaluation.canonical({k: v for k, v in frozen.items() if k != 'snapshot_sha256'}))
    with pytest.raises(ValueError): evaluation.verify_snapshot(root, frozen)


def test_duplicate_body_rejected_even_when_reformatted(corpus):
    root, _ = corpus
    (root / 'n20.txt').write_text(' \n' + (root / 'n00.txt').read_text(encoding='utf-8') + '\r\n ', encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate notice body'): freeze(corpus)


@pytest.mark.parametrize('path', ['../escape.json', 'C:/private.json', '/outside.json', 'nested/../../outside.json', '..\\escape.json', 'source.txt:stream.json'])
def test_corpus_paths_cannot_escape_root(corpus, path):
    root, manifest = corpus
    manifest['cases'][0]['gold_path'] = path
    save(root / 'corpus.json', manifest)
    with pytest.raises(ValueError): freeze(corpus)


def test_failure_missing_duplicate_and_wrong_predictions_stay_in_denominators(corpus):
    root, _ = corpus
    frozen = freeze(corpus)
    run, judgments = example_run(root, frozen)
    report = evaluation.score(root, frozen, run, judgments)
    totals = report['totals']
    assert totals['cases'] == 20 and totals['fact_denominator'] == 160
    assert totals['fact_correct'] == 23 and totals['fact_accuracy'] == 0.14375
    assert (totals['task_tp'], totals['task_fp'], totals['task_fn']) == (3, 3, 37)
    assert (totals['task_precision'], totals['task_recall']) == (0.5, 0.075)
    assert totals['duplicate_predictions'] == 1
    assert totals['status_counts'] == {'complete': 3, 'error': 1, 'timeout': 1, 'unsupported': 1, 'cancelled': 1, 'invalid_output': 1, 'not_run': 12}
    assert totals['error_tags'] == {'deadline': 1, 'unsupported': 1}
    assert totals['fact_categories']['dates'] == {'correct': 2, 'denominator': 20}
    assert sum(group['cases'] for group in report['categories'].values()) == 20
    assert report['usage']['input_tokens'] == {'known_total': 300, 'known_cases': 3, 'unknown_attempted_cases': 5}
    assert report['usage']['cached_input_tokens']['known_total'] is None
    assert report['attempt_duration_seconds'] == {'count': 8, 'median': 10, 'min': 10, 'max': 10}
    assert report['model_calls_by_evaluator'] == 0 and not report['all_cases_attempted']


def test_empty_run_is_visible_as_not_run_and_does_not_invent_latency_or_usage(corpus):
    root, _ = corpus
    frozen = freeze(corpus)
    run, judgments = example_run(root, frozen)
    run['results'], judgments['cases'] = [], []
    report = evaluation.score(root, frozen, run, judgments)
    assert report['totals']['status_counts'] == {'not_run': 20}
    assert report['totals']['task_fn'] == 40
    assert report['totals']['task_precision'] is None and report['totals']['task_recall'] == 0
    assert report['attempt_duration_seconds']['median'] is None
    assert report['usage']['input_tokens']['known_total'] is None


@pytest.mark.parametrize('mutation', ['missing_case', 'missing_task', 'missing_fact', 'wrong_output', 'wrong_run', 'wrong_dataset',
                                    'wrong_match', 'duplicate_case', 'duplicate_task', 'review_failure', 'not_human', 'not_all', 'early'])
def test_incomplete_or_cross_run_adjudication_never_produces_scores(corpus, mutation):
    root, _ = corpus
    frozen = freeze(corpus)
    run, judgments = example_run(root, frozen)
    case = judgments['cases'][0]
    if mutation == 'missing_case': judgments['cases'].pop()
    elif mutation == 'missing_task': case['tasks'].pop()
    elif mutation == 'missing_fact': case['facts'].pop('dates')
    elif mutation == 'wrong_output': case['output_sha256'] = '0' * 64
    elif mutation == 'wrong_run': judgments['run_id'] = 'another-run'
    elif mutation == 'wrong_dataset': judgments['snapshot_sha256'] = '0' * 64
    elif mutation == 'wrong_match': case['tasks'][0]['gold_task_id'] = 'another-task'
    elif mutation == 'duplicate_case': judgments['cases'].append(deepcopy(case))
    elif mutation == 'duplicate_task': case['tasks'].append(deepcopy(case['tasks'][0]))
    elif mutation == 'review_failure': judgments['cases'].append({**deepcopy(case), 'case_id': 'n13'})
    elif mutation == 'not_human': judgments['adjudication_kind'] = 'model'
    elif mutation == 'not_all': judgments['all_personal_tasks_reviewed'] = False
    elif mutation == 'early': judgments['adjudicated_at'] = frozen['frozen_at']
    with pytest.raises(ValueError): evaluation.score(root, frozen, run, judgments)


@pytest.mark.parametrize('mutation', ['duplicate', 'cross_split', 'human_edited', 'before_freeze', 'reverse_time', 'bool_usage', 'negative_usage', 'cache_overflow', 'modified_output', 'wrong_hash', 'malformed_output'])
def test_run_integrity_errors_are_rejected(corpus, mutation):
    root, _ = corpus
    frozen = freeze(corpus)
    run, judgments = example_run(root, frozen)
    result = run['results'][0]
    if mutation == 'duplicate': run['results'].append(deepcopy(result))
    elif mutation == 'cross_split': run['results'][-1]['case_id'] = 'n00'
    elif mutation == 'human_edited': run['output_stage'] = 'confirmed_after_human_edit'
    elif mutation == 'before_freeze': run['started_at'] = '2025-01-01T00:00:00+00:00'
    elif mutation == 'reverse_time': result['finished_at'] = '2025-01-01T00:00:00+00:00'
    elif mutation == 'bool_usage': result['input_tokens'] = True
    elif mutation == 'negative_usage': result['output_tokens'] = -1
    elif mutation == 'cache_overflow': result['cached_input_tokens'] = 101
    elif mutation == 'modified_output': (root / result['output_path']).write_text('{}', encoding='utf-8')
    elif mutation == 'wrong_hash': result['output_sha256'] = '0' * 64
    elif mutation == 'malformed_output':
        save(root / result['output_path'], {'draft': {'facts': {}, 'tasks': []}})
        result['output_sha256'] = evaluation.stamp_file(root / result['output_path'])['sha256']
        judgments['cases'][0]['output_sha256'] = result['output_sha256']
    with pytest.raises(ValueError): evaluation.score(root, frozen, run, judgments)


def test_json_duplicate_keys_and_nonfinite_values_are_rejected(tmp_path):
    for text in ['{"cases": [], "cases": [1]}', '{"time":NaN}', '{"time":Infinity}']:
        (tmp_path / 'bad.json').write_text(text, encoding='utf-8')
        with pytest.raises(ValueError): evaluation.read_json(tmp_path / 'bad.json')


def test_evidence_is_exclusively_created(tmp_path):
    path = tmp_path / 'report.json'
    evaluation.write_new(path, {'original': True})
    with pytest.raises(FileExistsError): evaluation.write_new(path, {'original': False})
    assert evaluation.read_json(path) == {'original': True}


def test_complete_run_retains_all_notices_and_zero_gold_has_undefined_recall(corpus):
    root, _ = corpus
    gold = evaluation.read_json(root / 'n10.gold.json')
    gold['tasks'] = []
    save(root / 'n10.gold.json', gold)
    frozen = freeze(corpus)
    run, judgments = example_run(root, frozen)
    run['results'] = [dict(run['results'][3], case_id=f'n{index:02}') for index in range(10, 30)]
    judgments['cases'] = []
    report = evaluation.score(root, frozen, run, judgments)
    assert report['all_cases_attempted'] and report['totals']['status_counts'] == {'error': 20}
    assert report['totals']['task_fn'] == 38
    empty = evaluation.aggregate([dict(report['cases'][0], task_fn=0)])
    assert empty['task_recall'] is None and empty['task_precision'] is None


def test_cli_freeze_verify_and_score_without_app_or_provider(corpus):
    root, _ = corpus
    command = [sys.executable, str(Path(evaluation.__file__).resolve())]
    def cli(*arguments):
        return subprocess.run([*command, *arguments], capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert cli('schema', 'gold').returncode == 0
    assert cli('validate', '--root', str(root), '--manifest', 'corpus.json').returncode == 0
    result = cli('freeze', '--root', str(root), '--manifest', 'corpus.json', '--output', 'frozen.json')
    assert result.returncode == 0, result.stderr
    assert cli('verify', '--root', str(root), '--frozen', 'frozen.json').returncode == 0
    frozen = evaluation.read_json(root / 'frozen.json')
    run, judgments = example_run(root, frozen)
    save(root / 'run.json', run)
    save(root / 'judgments.json', judgments)
    result = cli('score', '--root', str(root), '--frozen', 'frozen.json', '--run', 'run.json', '--judgments', 'judgments.json', '--output', 'score.json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['totals']['task_fn'] == 37
    repeated = cli('freeze', '--root', str(root), '--manifest', 'corpus.json', '--output', 'frozen.json')
    assert repeated.returncode == 2 and evaluation.read_json(root / 'frozen.json') == frozen
