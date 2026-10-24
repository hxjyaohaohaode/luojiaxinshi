"""Owner-scoped execution records and explicit, atomic notice change proposals.

Original requirements (TaskData), personal execution (WorkflowData), and incoming
changes have separate lifecycles. Adapters may propose changes; only the user's
version-checked confirmation may apply them. No external action is performed.
"""
from datetime import datetime, timezone
import json
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field, field_validator

from .db import audit, dumps, ident
from .documents import MAX_CHARS, text_source, total_chars
from .models import Strict, TaskData, TaskUpdate, ActionCondition, safe_url
from .action_plans import gate_issues,require_gates,require_task_gates,constraint_key
from .action_review import public_review,require_reviewed,pending,schedule_issues,record_change,record_workflow_change,descendants,FORMAL_FIELDS


class WorkflowStep(Strict):
    id: str = Field(min_length=1,max_length=60,pattern=r'^[a-zA-Z0-9_.:-]+$')
    title: str = Field(min_length=1,max_length=160)
    done: bool = Field(default=False,strict=True)
    note: str = Field(default='',max_length=500)


class WorkflowData(Strict):
    # Personal board placement is independent from formal submission/receipt status.
    board_lane: Literal['action', 'followup'] | None = None
    board_order: int | None = Field(default=None,ge=0,le=1000000)
    stage: Literal['preparing', 'submitted', 'supplement', 'accepted', 'rejected', 'blocked', 'active', 'waiting', 'recorded'] = 'preparing'
    # Legacy records retain their submission semantics. New confirmed plans
    # explicitly choose the handling mode; no keyword guesses rewrite old data.
    execution_mode: Literal['task','submission','attendance','reading','decision','collection','payment','waiting','custom'] = 'submission'
    phase_label: str = Field(default='',max_length=80)
    milestones: list[WorkflowStep] = Field(default_factory=list,max_length=20)
    dependency_mode: Literal['all','any'] = 'all'
    condition_mode: Literal['all','any'] = 'all'
    action_kind: Literal['unclassified', 'required', 'optional', 'verification'] = 'unclassified'
    participation: Literal['undecided', 'joined', 'declined'] = 'undecided'
    prepared_materials: list[str] = Field(default_factory=list, max_length=30)
    dependencies: list[str] = Field(default_factory=list, max_length=30)
    conditions: list[ActionCondition] = Field(default_factory=list,max_length=8)
    receipt: str = Field(default='', max_length=2000)
    receipt_url: str = Field(default='', max_length=2000)
    outcome: str = Field(default='', max_length=2000)
    next_step: str = Field(default='', max_length=1000)
    followup_at: str | None = None

    @field_validator('receipt_url')
    @classmethod
    def valid_url(cls, value):
        return safe_url(value)

    @field_validator('followup_at')
    @classmethod
    def valid_followup(cls, value):
        return TaskData.valid_datetime(value)

    @field_validator('prepared_materials', 'dependencies')
    @classmethod
    def unique_items(cls, values):
        if any(not s or len(s) > 500 for s in values):
            raise ValueError('清单项目不能为空或超过 500 字')
        return list(dict.fromkeys(values))

    @field_validator('conditions')
    @classmethod
    def unique_conditions(cls,values):
        if len({c.id for c in values})!=len(values) or len({c.text for c in values})!=len(values):raise ValueError('办理条件不能重复')
        return values

    @field_validator('milestones')
    @classmethod
    def unique_steps(cls,values):
        if len({s.id for s in values})!=len(values):raise ValueError('步骤标识不能重复')
        return values


class WorkflowUpdate(Strict):
    version: int = Field(ge=0)
    task_version: int = Field(ge=1)
    data: WorkflowData
    complete: bool = Field(default=False,strict=True)


class ChangeTarget(Strict):
    task_id: str = Field(min_length=1, max_length=40)
    version: int = Field(ge=1)
    action: Literal['revise', 'cancel', 'restore'] = 'revise'
    patch: dict = Field(default_factory=dict)


class ChangeProposal(Strict):
    notice_version: int = Field(ge=1)
    kind: Literal['correction', 'postponement', 'cancellation', 'restoration', 'supplement', 'unverified']
    text: str = Field(min_length=2, max_length=6000)
    source_label: str = Field(min_length=1, max_length=100)
    source_url: str = Field(default='', max_length=2000)
    published_at: str | None = None
    targets: list[ChangeTarget] = Field(default_factory=list, max_length=100)

    @field_validator('source_url')
    @classmethod
    def valid_url(cls, value):
        return safe_url(value)

    @field_validator('published_at')
    @classmethod
    def valid_published(cls, value):
        return TaskData.valid_datetime(value)


class ChangeDecision(Strict):
    version: int = Field(ge=1)
    decision: Literal['apply', 'dismiss']
    verified: bool = False
    note: str = Field(min_length=2, max_length=1500)


class CalendarCheck(Strict):
    task_version: int = Field(ge=1)
    device: str = Field(min_length=2, max_length=160)
    result: Literal['imported', 'reminder_verified', 'failed', 'removed']
    note: str = Field(default='', max_length=1000)


PATCH_FIELDS = {'title', 'details', 'due_date', 'due_time', 'deadline_text', 'materials',
                'submission', 'location', 'contact'}
DATE_FIELDS = {'due_date', 'due_time', 'deadline_text'}


def workflow_record(conn, task):
    row = conn.execute('SELECT * FROM task_workflows WHERE task_id=?', (task['id'],)).fetchone()
    value = WorkflowData.model_validate(json.loads(row['data']) if row else {}).model_dump()
    value['prepared_materials'] = [s for s in value['prepared_materials'] if s in task['data']['materials']]
    return {'version': row['version'] if row else 0, 'data': value}


def enrich_tasks(conn, tasks):
    """Batch current dependency state; obsolete or deleted links never count as done."""
    if not tasks:
        return tasks
    uid = tasks[0]['user_id']
    owned = {r['id']: dict(r) for r in conn.execute('SELECT id,status,data FROM tasks WHERE user_id=?', (uid,))}
    workflows = {r['task_id']: dict(r) for r in conn.execute(
        'SELECT w.* FROM task_workflows w JOIN tasks t ON t.id=w.task_id WHERE t.user_id=?', (uid,))}
    changes = {}
    for row in conn.execute("SELECT * FROM notice_changes WHERE user_id=? AND state='pending'", (uid,)):
        data = json.loads(row['data'])
        target_ids = [t['task_id'] for t in data['targets']]
        for task in tasks:
            if task['notice_id'] == row['notice_id'] and (not target_ids or task['id'] in target_ids):
                changes.setdefault(task['id'], []).append({'id': row['id'], 'kind': data['kind']})
    checks = {r['task_id']: dict(r) for r in conn.execute(
        'SELECT c.* FROM calendar_checks c JOIN tasks t ON t.id=c.task_id WHERE t.user_id=?', (uid,))}
    reviews={r['task_id']:public_review(r) for r in conn.execute('SELECT r.* FROM task_reviews r JOIN tasks t ON t.id=r.task_id WHERE t.user_id=?',(uid,))}
    for task in tasks:
        row = workflows.get(task['id'])
        value = WorkflowData.model_validate(json.loads(row['data']) if row else {}).model_dump()
        value['prepared_materials'] = [s for s in value['prepared_materials'] if s in task['data']['materials']]
        dependencies = []
        for tid in value['dependencies']:
            dep = owned.get(tid)
            dependencies.append({'id': tid, 'title': json.loads(dep['data'])['title'] if dep else '前置事项缺失或尚未导入，请重新核对',
                                 'status': dep['status'] if dep else 'missing','review_required':bool(reviews.get(tid,{}).get('state')=='pending'),
                                 'conditions_blocked':bool(gate_issues(json.loads(workflows[tid]['data']))) if tid in workflows else False})
        task['workflow'] = {'version': row['version'] if row else 0, 'data': value,
                            'dependencies': dependencies, 'blocked': dependencies_blocked(dependencies,value['dependency_mode'])}
        task['execution_issues']=gate_issues(value)
        task['action_excluded']=value['action_kind']=='optional' and value['participation']=='declined'
        if task['action_excluded']:task['overdue']=task['due_soon']=False
        task['change_review']=reviews.get(task['id'])
        task['schedule_issues']=schedule_issues(task['data'])
        task['followup_due'] = bool(task['status'] == 'pending' and not task['action_excluded'] and value['followup_at'] and
                                   datetime.fromisoformat(value['followup_at']) <= datetime.now(timezone.utc))
        task['pending_changes'] = changes.get(task['id'], [])
        check = checks.get(task['id'])
        task['calendar_check'] = {**check, 'current': check['task_version'] == task['version']} if check else None
        task['calendar_check_required'] = task['exported_version'] is not None and not (
            check and check['task_version'] == task['version'] and check['result'] in {'imported', 'reminder_verified', 'removed'})
        if check and check['task_version'] == task['version'] and check['result'] == 'removed' and task['status'] == 'cancelled':
            task['needs_calendar_sync'] = False
    return tasks


def notice_changes(conn, nid, uid):
    history = change_history(conn, nid, uid)
    result = []
    for row in conn.execute('SELECT * FROM notice_changes WHERE notice_id=? AND user_id=? ORDER BY created_at DESC,rowid DESC', (nid, uid)):
        data = json.loads(row['data'])
        archived = data.get('imported_history')
        latest = history.get(row['id'], {})
        saved = {**(archived or {}), **latest}
        if archived and not latest.get('impact'):
            saved['impact'] = archived.get('impact', [])
        result.append({**dict(row), 'data': data, 'impact': saved.get('impact', []),
                       'decision_note': saved.get('decision_note', ''), 'decided_at': saved.get('decided_at'),
                       'imported': bool(archived), 'original_created_at': saved.get('created_at', row['created_at'])})
    return result


def change_history(conn, nid, uid):
    """The decision's own snapshot survives later edits and portable export."""
    result = {}
    for event in conn.execute("SELECT action,before_json,after_json,created_at FROM audit WHERE notice_id=? AND user_id=? AND action IN ('change_applied','change_decided') ORDER BY id", (nid, uid)):
        after = json.loads(event['after_json'])
        cid = after.get('change_id')
        if not cid:
            continue
        entry = result.setdefault(cid, {'impact': []})
        if event['action'] == 'change_decided':
            entry.update(decision_note=after.get('note', ''), decided_at=event['created_at'])
            continue
        before = json.loads(event['before_json'])
        diff = {k: {'before': before['data'].get(k), 'after': after['data'].get(k)} for k in sorted(PATCH_FIELDS)
                if before['data'].get(k) != after['data'].get(k)}
        if before['status'] != after['status']:
            diff['status'] = {'before': before['status'], 'after': after['status']}
        entry['impact'].append({'title': before['data']['title'], 'diff': diff,
                                'warnings': ['本人核实依据：' + after.get('verification_note', '')]})
    return result


def dependencies_blocked(dependencies, mode='all'):
    ready=[d['status']=='done' and not d.get('review_required') and not d.get('conditions_blocked') for d in dependencies]
    return bool(ready) and not (any(ready) if mode=='any' else all(ready))


def require_proposed_dependencies(conn, uid, data):
    dependencies=[]
    for dep in data.get('dependencies',[]):
        row=conn.execute('SELECT t.status,w.data FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.id=? AND t.user_id=?',(dep,uid)).fetchone()
        dependencies.append({'status':row['status'] if row else 'missing','review_required':pending(conn,dep),
                             'conditions_blocked':bool(gate_issues(json.loads(row['data']))) if row and row['data'] else False})
    if dependencies_blocked(dependencies,data.get('dependency_mode','all')):
        label='至少一个' if data.get('dependency_mode')=='any' else '全部'
        raise HTTPException(422, f'请先完成并核实{label}前置事项；已取消、删除或待复核的步骤不算完成')


def require_dependency_ready(conn, task_id, uid):
    require_task_gates(conn,task_id)
    row = conn.execute('SELECT data FROM task_workflows WHERE task_id=?', (task_id,)).fetchone()
    if not row:
        return
    data=json.loads(row['data'])
    require_proposed_dependencies(conn,uid,data)
    if any(not s['done'] for s in data.get('milestones',[])):
        raise HTTPException(422,'请先完成办理清单中的步骤，或核实后移除不需要的步骤')


def reconcile_materials(conn, tid, materials):
    """Removed requirements cannot become 'prepared' again when later reintroduced."""
    row = conn.execute('SELECT data FROM task_workflows WHERE task_id=?', (tid,)).fetchone()
    if row:
        data = json.loads(row['data'])
        prepared = [s for s in data['prepared_materials'] if s in materials]
        if prepared != data['prepared_materials']:
            data['prepared_materials'] = prepared
            conn.execute('UPDATE task_workflows SET data=?,version=version+1,updated_at=? WHERE task_id=?', (dumps(data), int(time.time()), tid))


def validate_dependencies(conn, tid, uid, dependencies):
    rows = conn.execute('SELECT t.id,w.data FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=?', (uid,)).fetchall()
    graph = {r['id']: json.loads(r['data'])['dependencies'] if r['data'] else [] for r in rows}
    # Existing missing links may be retained while preparing or following up.
    # They still block submission/completion; new foreign or invented links fail.
    retained_missing = set(graph.get(tid, [])) - graph.keys()
    if any(d not in graph and d not in retained_missing for d in dependencies):
        raise HTTPException(422, '前置事项不存在或无权访问')
    graph[tid] = dependencies
    try:
        validate_dependency_graph(graph, [tid])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def validate_dependency_graph(graph, roots=None):
    """Iterative DFS handles imported graphs without depending on Python recursion."""
    visited, active = set(), set()
    for root in graph if roots is None else roots:
        stack = [(root, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                active.discard(node)
                visited.add(node)
                continue
            if node in active:
                raise ValueError('前置事项不能依赖自身或形成循环')
            if node in visited or node not in graph:
                continue  # Missing predecessors remain visibly unresolved, never completed.
            active.add(node)
            stack.append((node, True))
            stack.extend((dep, False) for dep in reversed(graph[node]))


def install_workflow(app, db, user, own_notice, own_task, expect_version, serialize_task,
                     get_sources, store_source, invalidate, validate_task, update_task_record):
    def get_task(conn, tid, uid):
        return enrich_tasks(conn, [serialize_task(own_task(conn, tid, uid))])[0]

    @app.get('/api/tasks/{tid}/workflow')
    def read_workflow(tid: str, current=Depends(user)):
        with db.connect() as conn:
            task = get_task(conn, tid, current['id'])
            candidates = [{'id': r['id'], 'title': json.loads(r['data'])['title'], 'status': r['status'],
                           'notice_id': r['notice_id'],'review_required':r['review_state']=='pending',
                           'conditions_blocked':bool(gate_issues(json.loads(r['workflow']))) if r['workflow'] else False} for r in conn.execute(
                'SELECT t.id,t.data,t.status,t.notice_id,r.state AS review_state,w.data AS workflow FROM tasks t LEFT JOIN task_reviews r ON r.task_id=t.id LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=? AND t.id!=? ORDER BY t.updated_at DESC', (current['id'], tid))]
            history = [dict(r) for r in conn.execute('SELECT * FROM audit WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 100', (tid, current['id']))]
            return {'task': task, 'candidates': candidates, 'history': history}

    @app.put('/api/tasks/{tid}/workflow')
    def update_workflow(tid: str, payload: WorkflowUpdate, current=Depends(user)):
        with db.connect(write=True) as conn:
            task = serialize_task(own_task(conn, tid, current['id']))
            expect_version(task, payload.task_version)
            old = workflow_record(conn, task)
            expect_version(old, payload.version)
            data = payload.data.model_dump()
            prior_steps={step['id']:step for step in old['data']['milestones']}
            for step in data['milestones']:
                previous=prior_steps.get(step['id'])
                if previous and previous['title']!=step['title']:step['done']=False
            prior_conditions={item['id']:item for item in old['data']['conditions']}
            for item in data['conditions']:
                previous=prior_conditions.get(item['id'])
                if previous and previous['text']!=item['text']:
                    item['state']='unknown';item['note']=''
            if data['stage'] in {'submitted','accepted','recorded'} and data['stage']!=old['data']['stage']:
                require_reviewed(conn,tid)
            if any(s not in task['data']['materials'] for s in data['prepared_materials']):
                raise HTTPException(422, '材料清单已变化，请重新核对')
            validate_dependencies(conn, tid, current['id'], data['dependencies'])
            if data['stage'] in {'submitted', 'accepted','recorded'} and data['stage']!=old['data']['stage']:
                require_gates(data)
                require_proposed_dependencies(conn,current['id'],data)
                if data['stage'] in {'submitted','accepted'} and len(data['prepared_materials']) < len(set(task['data']['materials'])):
                    raise HTTPException(422, '请先核对并勾选全部所需材料')
                if data['stage'] in {'submitted','accepted'} and not data['receipt'] and not data['receipt_url']:
                    raise HTTPException(422, '请填写实际提交记录或回执链接')
            if data['stage'] in {'accepted', 'rejected', 'supplement', 'blocked','recorded'} and not data['outcome']:
                raise HTTPException(422, '请填写办理结果、补件要求或受阻原因')
            if data['participation'] == 'declined' and data['action_kind'] != 'optional':
                raise HTTPException(422, '只有已核实为可选的事项可以记录为不参加')
            if task['status'] == 'cancelled' and (payload.complete or data['stage'] in {'submitted', 'accepted','recorded'} and data['stage'] != old['data']['stage']):
                raise HTTPException(422, '该事项已取消；如已正式恢复，请先处理恢复变更')
            now = int(time.time())
            conn.execute('INSERT INTO task_workflows VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at',
                         (tid, dumps(data), payload.version + 1, now))
            if constraint_key(old['data'])!=constraint_key(data):
                conn.execute('UPDATE tasks SET version=version+1,updated_at=? WHERE id=?',(now,tid))
                task['version']+=1
            audit(conn, current['id'], task['notice_id'], 'workflow_update', before=old['data'], after=data, task_id=tid)
            record_workflow_change(conn,current['id'],task,old['data'],data)
            if payload.complete:
                update_task_record(conn,current['id'],tid,TaskUpdate(version=task['version'],data=TaskData.model_validate(task['data']),status='done',reason='本人保存办理记录并确认完成'))
            return get_task(conn, tid, current['id'])

    def impact(conn, proposal, uid, check_versions=True):
        result, seen = [], set()
        for target in proposal['targets']:
            tid = target['task_id']
            if tid in seen:
                raise HTTPException(422, '同一待办不能重复列入变更')
            seen.add(tid)
            old = own_task(conn, tid, uid)
            if old['notice_id'] != proposal['notice_id']:
                raise HTTPException(422, '变更只能影响本通知下明确选中的待办')
            if check_versions:
                expect_version(old, target['version'])
            before = json.loads(old['data'])
            patch = target['patch']
            if not set(patch).issubset(PATCH_FIELDS):
                raise HTTPException(422, '变更仅允许更新正式要求；个人计划、提醒和备注请单独编辑')
            action = target['action']
            if action != 'revise' and patch:
                raise HTTPException(422, '取消和恢复不能同时修改办理要求')
            if action == 'cancel' and old['status'] != 'pending':
                raise HTTPException(422, '只能取消待完成事项；已完成记录保持独立')
            if action == 'restore' and old['status'] != 'cancelled':
                raise HTTPException(422, '只能恢复已取消事项')
            if action == 'revise' and not patch:
                raise HTTPException(422, '请指定需要更正的字段')
            expected_action = {'cancellation': 'cancel', 'restoration': 'restore'}.get(proposal['kind'], 'revise')
            if action != expected_action:
                raise HTTPException(422, '变更类型与待办操作不一致')
            try:
                after = TaskData.model_validate({**before, **patch}).model_dump()
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            status = 'cancelled' if action == 'cancel' else 'pending' if action == 'restore' else old['status']
            effective_fields = set(patch)
            if DATE_FIELDS.intersection(patch) and 'deadline_text' not in patch:
                after['deadline_text'] = proposal['text'][:500]
                effective_fields.add('deadline_text')
            diffs = {k: {'before': before.get(k), 'after': after[k]} for k in effective_fields if before.get(k) != after[k]}
            if status != old['status']:
                diffs['status'] = {'before': old['status'], 'after': status}
            if not diffs:
                raise HTTPException(422, '该事项没有实际变化，请取消选择或修改目标值')
            warnings = []
            if DATE_FIELDS.intersection(patch):
                warnings.append('个人计划与提醒时间保留原值，请核对是否需要重排。')
            if old['exported_version'] is not None:
                warnings.append('已导出过日历，确认后须更新或删除目标日历中的旧事件。')
            affected=descendants(conn,uid,tid) if FORMAL_FIELDS.intersection(diffs) or status!=old['status'] else []
            result.append({'task_id': tid, 'title': before['title'], 'version': old['version'],
                           'before': before, 'after': after, 'old_status': old['status'], 'status': status,
                           'diff': diffs, 'warnings': warnings,'affected_steps':affected})
        return result

    @app.post('/api/notices/{nid}/changes')
    def propose(nid: str, payload: ChangeProposal, current=Depends(user)):
        with db.connect(write=True) as conn:
            record = own_notice(conn, nid, current['id'])
            expect_version(record, payload.notice_version)
            if conn.execute('SELECT COUNT(*) FROM notice_changes WHERE notice_id=?', (nid,)).fetchone()[0] >= 100:
                raise HTTPException(422, '每则通知最多保存 100 条变更记录')
            proposal = {**payload.model_dump(), 'notice_id': nid}
            if payload.kind == 'unverified' and payload.targets:
                raise HTTPException(422, '待核实线索不能携带正式修改操作')
            impacts = impact(conn, proposal, current['id'])
            if payload.kind != 'unverified' and not impacts:
                raise HTTPException(422, '请至少选择一项受影响的待办')
            # Identical retries recover the original proposal, including after a lost response.
            prior = conn.execute('SELECT * FROM notice_changes WHERE notice_id=? AND data=?', (nid, dumps(proposal))).fetchone()
            if prior:
                return {**dict(prior), 'data': proposal, 'impact': impacts, 'replayed': True}
            cid, now = ident(), int(time.time())
            conn.execute('INSERT INTO notice_changes VALUES(?,?,?,?,?,?,?,?)', (cid, nid, current['id'], dumps(proposal), 'pending', 1, now, now))
            audit(conn, current['id'], nid, 'change_proposed', after={'change_id': cid, 'kind': payload.kind, 'targets': [x['task_id'] for x in impacts]})
            return {'id': cid, 'notice_id': nid, 'data': proposal, 'state': 'pending', 'version': 1, 'created_at': now, 'impact': impacts}

    @app.get('/api/notices/{nid}/changes/{cid}')
    def read_change(nid: str, cid: str, current=Depends(user)):
        with db.connect() as conn:
            own_notice(conn, nid, current['id'])
            row = next((r for r in notice_changes(conn, nid, current['id']) if r['id'] == cid), None)
            if not row:
                raise HTTPException(404, '变更不存在或无权访问')
            data = row['data']
            stale = False
            try:
                impacts = impact(conn, data, current['id']) if row['state'] == 'pending' else row['impact']
                stale = own_notice(conn, nid, current['id'])['version'] != data['notice_version']
            except HTTPException as exc:
                if exc.status_code not in {409, 422}:
                    raise
                impacts, stale = [], True
            return {**dict(row), 'data': data, 'impact': impacts, 'stale': stale}

    @app.post('/api/notices/{nid}/changes/{cid}/decision')
    def decide(nid: str, cid: str, payload: ChangeDecision, current=Depends(user)):
        with db.connect(write=True) as conn:
            record = own_notice(conn, nid, current['id'])
            row = conn.execute('SELECT * FROM notice_changes WHERE id=? AND notice_id=? AND user_id=?', (cid, nid, current['id'])).fetchone()
            if not row:
                raise HTTPException(404, '变更不存在或无权访问')
            desired = 'applied' if payload.decision == 'apply' else 'dismissed'
            if row['state'] == desired:
                return {'id': cid, 'state': desired, 'replayed': True}
            expect_version(row, payload.version)
            if row['state'] != 'pending':
                raise HTTPException(409, '该变更已处理，不能重复变更其结论')
            data = json.loads(row['data'])
            if payload.decision == 'apply':
                if not payload.verified:
                    raise HTTPException(422, '请核实发布方、事项范围和变更原文后再确认')
                if data['kind'] == 'unverified' or not data['targets']:
                    raise HTTPException(422, '待核实线索不能直接改变正式安排；核实后请根据最新事项建立正式变更')
                expect_version(record, data['notice_version'])
                impacts = impact(conn, data, current['id'])
                source = text_source(data['text'], '变更依据：' + data['source_label'])
                existing = get_sources(conn, nid, True)
                if total_chars(existing + [source]) > MAX_CHARS:
                    raise HTTPException(422, '有效原文合计超过 10000 字，请先整理当前材料，再重新预览变更')
                evidence = [{'source_id': source['id'], 'locator': s['locator'], 'quote': s['text'][:1600]} for s in source['sections'][:10]]
                store_source(conn, nid, source)
                for item, target in zip(impacts, data['targets']):
                    after = item['after']
                    after['evidence'] = (after['evidence'] + evidence)[-30:]
                    if DATE_FIELDS.intersection(target['patch']):
                        after['deadline_confirmed'] = bool(after['due_date'])
                        after['deadline_evidence'] = evidence
                        after['resolution_note'] = payload.note
                    try:
                        # Official facts may invalidate a saved personal reminder.
                        # Save the confirmed facts and require a separate review;
                        # never reject a real date withdrawal just to keep an alarm.
                        validate_task(TaskData.model_validate({**after,'reminder_at':None}), get_sources(conn, nid), [], enforce_future=False)
                    except ValueError as exc:
                        raise HTTPException(422, str(exc)) from None
                    conn.execute('UPDATE tasks SET data=?,status=?,version=version+1,updated_at=? WHERE id=?',
                                 (dumps(after), item['status'], int(time.time()), item['task_id']))
                    reconcile_materials(conn, item['task_id'], after['materials'])
                    record_change(conn,current['id'],item['task_id'],item['before'],after,item['old_status'],item['status'],cid)
                    audit(conn, current['id'], nid, 'change_applied', before={'data': item['before'], 'status': item['old_status']},
                          after={'data': after, 'status': item['status'], 'change_id': cid, 'verification_note': payload.note}, task_id=item['task_id'])
                # Previously generated drafts must never reintroduce superseded facts.
                invalidate(conn, nid)
                conn.execute("UPDATE notices SET status='confirmed' WHERE id=?", (nid,))
            conn.execute('UPDATE notice_changes SET state=?,version=version+1,updated_at=? WHERE id=?', (desired, int(time.time()), cid))
            audit(conn, current['id'], nid, 'change_decided', after={'change_id': cid, 'state': desired, 'note': payload.note})
            return {'id': cid, 'state': desired, 'replayed': False}

    @app.post('/api/tasks/{tid}/calendar-check')
    def calendar_check(tid: str, payload: CalendarCheck, current=Depends(user)):
        with db.connect(write=True) as conn:
            task = own_task(conn, tid, current['id'])
            expect_version(task, payload.task_version)
            if task['exported_version'] != task['version'] and payload.result != 'removed':
                raise HTTPException(422, '请先导出当前版本，再记录目标设备验证结果')
            if payload.result == 'removed' and task['status'] != 'cancelled':
                raise HTTPException(422, '移除确认用于已取消的事项')
            conn.execute('INSERT INTO calendar_checks VALUES(?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET task_version=excluded.task_version,device=excluded.device,result=excluded.result,note=excluded.note,checked_at=excluded.checked_at',
                         (tid, task['version'], payload.device, payload.result, payload.note, int(time.time())))
            audit(conn, current['id'], task['notice_id'], 'calendar_check', after=payload.model_dump(), task_id=tid)
            return get_task(conn, tid, current['id'])

    from .action_review import install as install_review
    install_review(app,db,user,own_task,expect_version,get_task)
