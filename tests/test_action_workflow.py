"""Real SQLite transactions; no model or external platform is contacted."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.backups import restore_database
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.workflow import WorkflowData
from test_workflow import account, env, notice, manual, task, confirm, PASSWORD, ORIGIN


def setup_tasks(c):
    n = manual(c, notice(c))
    payload = {'version': n['version'], 'reviewed': True,
               'tasks': [task(n, title='准备申请表'), task(n, title='提交材料')]}
    ids = c.post(f"/api/notices/{n['id']}/confirm", json=payload).json()['task_ids']
    return c.get(f"/api/notices/{n['id']}").json(), ids


def workflow(c, tid, **changes):
    current = c.get(f'/api/tasks/{tid}/workflow').json()['task']
    return c.put(f'/api/tasks/{tid}/workflow', json={
        'version': current['workflow']['version'], 'task_version': current['version'],
        'data': {**current['workflow']['data'], **changes}})


def proposal(n, tid, **changes):
    return {'notice_version': n['version'], 'kind': 'postponement',
            'text': '正式更正：本人提交申请表的截止日期延期至2027年10月25日。',
            'source_label': '学院测试办公室',
            'targets': [{'task_id': tid, 'version': 1, 'action': 'revise', 'patch': {'due_date': '2027-10-25'}}], **changes}


def propose(c, n, p):
    r = c.post(f"/api/notices/{n['id']}/changes", json=p)
    assert r.status_code == 200, r.text
    return r.json()


def decide(c, n, change, **kw):
    return c.post(f"/api/notices/{n['id']}/changes/{change['id']}/decision", json={
        'version': change['version'], 'decision': 'apply', 'verified': True,
        'note': '已对照正式更正原文核实本人范围及日期', **kw})


def test_material_receipt_and_followup_lifecycle(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[1]
    assert workflow(c, tid, stage='submitted').status_code == 422
    r = workflow(c, tid, stage='submitted', prepared_materials=['申请表'], receipt='本人已在测试窗口提交，编号 TEST-01',
                 next_step='查询受理结果', followup_at='2020-01-01T10:00:00+08:00')
    assert r.status_code == 200, r.text
    assert r.json()['followup_due']
    assert r.json()['status'] == 'pending'  # submission is not completion or acceptance
    assert workflow(c, tid, stage='accepted').status_code == 422
    accepted = workflow(c, tid, stage='accepted', outcome='已核实学院受理回执 TEST-02')
    assert accepted.status_code == 200
    assert accepted.json()['workflow']['data']['receipt'].endswith('TEST-01')
    assert accepted.json()['version'] == 1  # material ticks do not dirty the calendar snapshot


def test_dependency_cycles_isolation_and_completion_guard(env):
    c = account(env); n, ids = setup_tasks(c)
    assert workflow(c, ids[1], dependencies=[ids[0]]).status_code == 200
    assert workflow(c, ids[0], dependencies=[ids[1]]).status_code == 422
    assert workflow(c, ids[0], dependencies=[ids[0]]).status_code == 422
    other = account(env, 'bob'); other_n, other_ids = setup_tasks(other)
    assert workflow(c, ids[0], dependencies=[other_ids[0]]).status_code == 422
    current = c.get('/api/tasks').json()[0]
    current = next(t for t in c.get('/api/tasks').json() if t['id'] == ids[1])
    assert c.put('/api/tasks/'+ids[1], json={'version': current['version'], 'data': current['data'], 'status': 'done', 'reason': '测试完成'}).status_code == 422
    first = next(t for t in c.get('/api/tasks').json() if t['id'] == ids[0])
    assert c.put('/api/tasks/'+ids[0], json={'version': first['version'], 'data': first['data'], 'status': 'done', 'reason': '测试完成'}).status_code == 200
    assert not c.get('/api/tasks/'+ids[1]+'/workflow').json()['task']['workflow']['blocked']


def test_workflow_conflict_and_foreign_access(env):
    c = account(env); n, ids = setup_tasks(c)
    payload = {'version': 0, 'task_version': 1, 'data': WorkflowData(next_step='保留新记录').model_dump()}
    assert c.put('/api/tasks/'+ids[0]+'/workflow', json=payload).status_code == 200
    assert c.put('/api/tasks/'+ids[0]+'/workflow', json=payload).status_code == 409
    b = account(env, 'bob')
    assert b.get('/api/tasks/'+ids[0]+'/workflow').status_code == 404
    assert b.put('/api/tasks/'+ids[0]+'/workflow', json=payload).status_code == 404


def test_change_preview_apply_preserves_personal_records_and_idempotency(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[1]
    workflow(c, tid, prepared_materials=['申请表'], next_step='等待回执')
    c.post('/api/calendar/export', json={'task_ids': [tid], 'versions': {tid: 1}})
    change = propose(c, n, proposal(n, tid))
    assert change['impact'][0]['diff']['due_date']['before'] == '2027-10-20'
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['data']['due_date'] == '2027-10-20'
    assert decide(c, n, change, verified=False).status_code == 422
    r = decide(c, n, change); assert r.status_code == 200, r.text
    assert decide(c, n, change).json()['replayed']
    updated = c.get('/api/tasks/'+tid+'/workflow').json()['task']
    assert updated['data']['due_date'] == '2027-10-25'
    assert updated['data']['notes'] == '保留我的备注'
    assert updated['workflow']['data']['next_step'] == '等待回执'
    assert updated['needs_calendar_sync']
    assert updated['data']['deadline_evidence'][0]['source_id'] != n['sources'][0]['id']
    assert c.get('/api/notices/'+n['id']).json()['draft'] is None


def test_unknown_change_keeps_last_confirmed_deadline(env):
    c = account(env); n, ids = setup_tasks(c)
    change = propose(c, n, proposal(n, ids[0], kind='unverified', targets=[], text='群中转述可能延期，尚未确认。'))
    assert decide(c, n, change).status_code == 422
    rows = c.get('/api/tasks').json()
    assert all(t['data']['due_date'] == '2027-10-20' and t['pending_changes'] for t in rows)
    assert decide(c, n, change, decision='dismiss', verified=False, note='已核实转述不适用于本人').status_code == 200
    assert all(not t['pending_changes'] for t in c.get('/api/tasks').json())


def test_change_conflict_rolls_back_all_targets(env):
    c = account(env); n, ids = setup_tasks(c)
    p = proposal(n, ids[0]); p['targets'].append({**p['targets'][0], 'task_id': ids[1]})
    change = propose(c, n, p)
    t = c.get('/api/tasks/'+ids[1]+'/workflow').json()['task']
    c.put('/api/tasks/'+ids[1], json={'version': t['version'], 'data': {**t['data'], 'notes': '另一个窗口新备注'}, 'status': 'pending', 'reason': '更新备注'})
    assert decide(c, n, change).status_code == 409
    assert all(t['data']['due_date'] == '2027-10-20' for t in c.get('/api/tasks').json())
    assert c.get(f"/api/notices/{n['id']}/changes/{change['id']}").json()['stale']


def test_cancellation_restoration_and_completed_protection(env):
    c = account(env); n, ids = setup_tasks(c)
    cancel = proposal(n, ids[0], kind='cancellation', targets=[{'task_id': ids[0], 'version': 1, 'action': 'cancel'}])
    change = propose(c, n, cancel); assert decide(c, n, change).status_code == 200
    latest = c.get('/api/notices/'+n['id']).json()
    restore = proposal(latest, ids[0], kind='restoration', targets=[{'task_id': ids[0], 'version': 2, 'action': 'restore'}])
    change = propose(c, latest, restore); assert decide(c, latest, change).status_code == 200
    t = c.get('/api/tasks/'+ids[1]+'/workflow').json()['task']
    c.put('/api/tasks/'+ids[1], json={'version': t['version'], 'data': t['data'], 'status': 'done', 'reason': '完成'})
    latest = c.get('/api/notices/'+n['id']).json()
    bad = proposal(latest, ids[1], kind='cancellation', targets=[{'task_id': ids[1], 'version': 2, 'action': 'cancel'}])
    assert c.post('/api/notices/'+n['id']+'/changes', json=bad).status_code == 422


def test_calendar_verification_is_user_report_and_version_bound(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[0]
    body = {'task_version': 1, 'device': '测试手机／测试日历', 'result': 'reminder_verified', 'note': '工程夹具，不是真机验证'}
    assert c.post('/api/tasks/'+tid+'/calendar-check', json=body).status_code == 422
    assert c.post('/api/calendar/export', json={'task_ids': [tid], 'versions': {tid: 1}}).status_code == 200
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['calendar_check_required']
    r = c.post('/api/tasks/'+tid+'/calendar-check', json=body)
    assert r.status_code == 200, r.text
    assert r.json()['calendar_check']['current']
    assert not r.json()['calendar_check_required']
    change = propose(c, n, proposal(n, tid)); decide(c, n, change)
    assert not c.get('/api/tasks/'+tid+'/workflow').json()['task']['calendar_check']['current']
    assert c.post('/api/calendar/export', json={'task_ids': [tid], 'versions': {tid: 2}}).status_code == 200
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['calendar_check_required']  # exporting alone is not re-importing


def test_change_kind_must_match_selected_operation(env):
    c = account(env); n, ids = setup_tasks(c)
    for kind, action in [('correction', 'cancel'), ('unverified', 'revise')]:
        p = proposal(n, ids[0], kind=kind)
        p['targets'][0].update(action=action, patch={} if action == 'cancel' else {'location': '新地点'})
        assert c.post(f"/api/notices/{n['id']}/changes", json=p).status_code == 422


def test_export_and_cascade_cleanup(env):
    c = account(env); n, ids = setup_tasks(c)
    workflow(c, ids[0], next_step='查询处理结果')
    change = propose(c, n, proposal(n, ids[0]))
    data = c.get('/api/export').json()
    assert data['notices'][0]['tasks'][0]['workflow']['data']['next_step'] == '查询处理结果'
    assert data['notices'][0]['changes'][0]['id'] == change['id']
    c.request('DELETE', '/api/notices/'+n['id'], json={'version': n['version']})
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM task_workflows').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM notice_changes').fetchone()[0] == 0


def test_import_preserves_execution_and_rebinds_dependencies(env):
    a = account(env); n, ids = setup_tasks(a)
    workflow(a, ids[1], dependencies=[ids[0]], receipt='历史回执，不代表新受理', next_step='核实新学期安排')
    propose(a, n, proposal(n, ids[1]))
    exported = a.get('/api/export').json()
    b = account(env, 'importer')
    preview = b.post('/api/import', json={'data': exported}).json()
    r = b.post('/api/import', json={'data': exported, 'confirm': True, 'digest': preview['digest']})
    assert r.status_code == 200, r.text
    rows = b.get('/api/tasks').json()
    target = next(t for t in rows if t['data']['title'] == '提交材料')
    dependency = next(t for t in rows if t['data']['title'] == '准备申请表')
    assert target['workflow']['data']['dependencies'] == [dependency['id']]
    assert target['workflow']['data']['receipt'] == '历史回执，不代表新受理'
    assert target['workflow']['blocked'] and target['pending_changes']
    assert not target['data']['deadline_confirmed'] and target['calendar_check'] is None
    assert not {t['id'] for t in rows}.intersection(ids)


def test_material_changes_do_not_resurrect_old_checkmarks(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[0]
    assert workflow(c, tid, prepared_materials=['申请表']).status_code == 200
    current = c.get('/api/tasks/'+tid+'/workflow').json()['task']
    for material in ['新版申请表', '申请表']:
        r = c.put('/api/tasks/'+tid, json={'version': current['version'], 'data': {**current['data'], 'materials': [material]}, 'status': 'pending', 'reason': '正式要求变化'})
        assert r.status_code == 200
        current = r.json()
    assert current['workflow']['data']['prepared_materials'] == []


def test_workflow_draft_owner_and_version_are_checked(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[0]
    key = f'workflow:{tid}:1:0'
    payload = {'revision': 0, 'payload': {'data': WorkflowData(next_step='未提交的草稿').model_dump()}}
    assert c.put('/api/edit-cache/'+key, json=payload).status_code == 200
    b = account(env, 'bob')
    assert b.get('/api/edit-cache/'+key).status_code == 404
    workflow(c, tid, next_step='正式保存的新记录')
    assert c.put('/api/edit-cache/'+key, json={**payload, 'revision': 1}).status_code == 409


def test_regenerated_requirements_preserve_personal_schedule(env):
    c = account(env); n, ids = setup_tasks(c); tid = ids[0]
    current = c.get('/api/tasks/'+tid+'/workflow').json()['task']
    personal = {**current['data'], 'planned_at': '2030-10-18T10:00:00+08:00', 'reminder_at': '2030-10-19T10:00:00+08:00'}
    assert c.put('/api/tasks/'+tid, json={'version': 1, 'data': personal, 'status': 'pending', 'reason': '本人安排'}).status_code == 200
    fresh = manual(c, c.get('/api/notices/'+n['id']).json())
    confirm(c, fresh, task(fresh, title='补件后更新要求'), replacements={0: tid}, target_versions={tid: 2})
    saved = c.get('/api/tasks/'+tid+'/workflow').json()['task']['data']
    assert saved['planned_at'] == personal['planned_at'] and saved['reminder_at'] == personal['reminder_at']


def test_backup_restores_receipts_changes_dependencies_and_device_records(env, tmp_path):
    c = account(env); n, ids = setup_tasks(c)
    workflow(c, ids[1], dependencies=[ids[0]], receipt='真实恢复测试使用的虚构回执')
    change = propose(c, n, proposal(n, ids[0]))
    c.post('/api/calendar/export', json={'task_ids': [ids[0]], 'versions': {ids[0]: 1}})
    c.post('/api/tasks/'+ids[0]+'/calendar-check', json={'task_version': 1, 'device': '虚构设备', 'result': 'imported'})
    backup = tmp_path/'workflow-backup.sqlite3'
    env[0].state.db.backup(backup)
    destination = tmp_path/'restored'/'campus.sqlite3'
    restore_database(backup, destination)
    restored = TestClient(create_app(Settings(destination.parent, origin=ORIGIN)), base_url=ORIGIN)
    restored.headers.update({'Origin': ORIGIN, 'X-Requested-With': 'campus-notice'})
    assert restored.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    current = restored.get('/api/notices/'+n['id']).json()
    second = next(t for t in current['tasks'] if t['id'] == ids[1])
    first = next(t for t in current['tasks'] if t['id'] == ids[0])
    assert second['workflow']['data']['dependencies'] == [ids[0]]
    assert second['workflow']['data']['receipt'] == '真实恢复测试使用的虚构回执'
    assert first['calendar_check']['result'] == 'imported'
    assert current['changes'][0]['id'] == change['id']
    assert current['changes'][0]['state'] == 'pending'


def test_additive_migration_and_future_version_rejection(tmp_path):
    path = tmp_path/'legacy.sqlite3'
    Database(path)
    with sqlite3.connect(path) as conn:
        for table in ['task_workflows', 'notice_changes', 'calendar_checks']:
            conn.execute('DROP TABLE '+table)
        conn.execute("DELETE FROM meta WHERE key='workflow_schema_version'")
    migrated = Database(path)
    with migrated.connect() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone()[0] == '2'
        assert conn.execute('PRAGMA foreign_key_check').fetchone() is None
        conn.execute("UPDATE meta SET value='999' WHERE key='workflow_schema_version'")
    with pytest.raises(RuntimeError, match='禁止直接降级'):
        Database(path)
    target = tmp_path/'rejected'/'campus.sqlite3'
    with pytest.raises(ValueError, match='版本不兼容'):
        restore_database(path, target)
    assert not target.exists()
