"""Portable migration must preserve history without granting it current authority."""
from copy import deepcopy

import pytest

from test_action_workflow import setup_tasks, workflow, proposal, propose, decide
from test_workflow import account, env, notice, manual, task


def import_file(client, data):
    preview = client.post('/api/import', json={'data': data})
    assert preview.status_code == 200, preview.text
    return client.post('/api/import', json={'data': data, 'confirm': True, 'digest': preview.json()['digest']})


def separate_steps(client):
    notices, ids = [], []
    for i in range(2):
        n = manual(client, notice(client, text=f'虚构迁移测试 {i}：本人于2027年10月20日17:00前提交申请表。'))
        r = client.post('/api/notices/'+n['id']+'/confirm', json={'version': n['version'], 'reviewed': True,
                        'tasks': [task(n, title=f'跨通知步骤 {i}')]})
        assert r.status_code == 200
        ids.append(r.json()['task_ids'][0]); notices.append(n['id'])
    assert workflow(client, ids[1], dependencies=[ids[0]]).status_code == 200
    return notices, ids, client.get('/api/export').json()


@pytest.mark.parametrize('predecessor_first', [True, False])
def test_split_import_resolves_dependencies_in_both_orders(env, predecessor_first):
    author = account(env); notice_ids, ids, exported = separate_steps(author)
    reader = account(env, 'reader')
    order = [0, 1] if predecessor_first else [1, 0]
    for index in order:
        part = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[index]]}
        response = import_file(reader, part)
        assert response.status_code == 200, response.text
    tasks = reader.get('/api/tasks').json()
    first = next(t for t in tasks if t['data']['title'] == '跨通知步骤 0')
    second = next(t for t in tasks if t['data']['title'] == '跨通知步骤 1')
    assert second['workflow']['data']['dependencies'] == [first['id']]
    assert second['workflow']['blocked']
    assert first['id'] not in ids
    assert import_file(reader, exported).json()['added'] == 0
    if not predecessor_first:
        history = reader.get('/api/tasks/'+second['id']+'/workflow').json()['history']
        assert any(h['action'] == 'import_dependencies_resolved' for h in history)


def test_resolving_a_split_import_cycle_rolls_back_every_change(env):
    author = account(env); notice_ids, ids, exported = separate_steps(author)
    reader = account(env, 'reader')
    later = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[1]]}
    assert import_file(reader, later).status_code == 200
    before = reader.get('/api/tasks').json()
    earlier = deepcopy({**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[0]]})
    earlier['notices'][0]['tasks'][0]['workflow']['data']['dependencies'] = [ids[1]]
    assert import_file(reader, earlier).status_code == 422
    after = reader.get('/api/tasks').json()
    assert len(after) == 1 and after[0]['workflow'] == before[0]['workflow']
    assert after[0]['workflow']['dependencies'][0]['status'] == 'missing'
    # The rejected batch did not reserve import IDs or poison subsequent valid retries.
    earlier['notices'][0]['tasks'][0]['workflow']['data']['dependencies'] = []
    assert import_file(reader, earlier).status_code == 200


def test_portable_change_history_survives_two_migrations_and_later_edits(env):
    author = account(env); n, ids = setup_tasks(author)
    change = propose(author, n, proposal(n, ids[0]))
    assert decide(author, n, change).status_code == 200
    current = author.get('/api/tasks/'+ids[0]+'/workflow').json()['task']
    assert author.put('/api/tasks/'+ids[0], json={'version': current['version'], 'status': current['status'],
                      'data': {**current['data'], 'due_date': '2027-11-01'}, 'reason': '后续独立调整'}).status_code == 200
    exported = author.get('/api/export').json()
    expected = exported['notices'][0]['changes'][0]
    assert expected['impact'][0]['diff']['due_date'] == {'before': '2027-10-20', 'after': '2027-10-25'}
    for name in ['reader', 'nextreader']:
        reader = account(env, name)
        assert import_file(reader, exported).status_code == 200
        exported = reader.get('/api/export').json()
        imported = exported['notices'][0]['changes'][0]
        assert imported['state'] == 'applied' and imported['imported']
        assert imported['impact'] == expected['impact']
        assert imported['decision_note'] == expected['decision_note']
        assert imported['original_created_at'] == expected['original_created_at']
        assert imported['data']['targets'] == []
        assert all(not t['data']['deadline_confirmed'] for t in exported['notices'][0]['tasks'])
        nid = exported['notices'][0]['id']
        detail = reader.get(f"/api/notices/{nid}/changes/{imported['id']}").json()
        assert detail['impact'] == expected['impact']


def test_imported_pending_line_retains_new_dismissal_reason(env):
    author = account(env); n, ids = setup_tasks(author)
    propose(author, n, proposal(n, ids[0], kind='unverified', targets=[], text='可能变更，尚未核实。'))
    reader = account(env, 'reader')
    assert import_file(reader, author.get('/api/export').json()).status_code == 200
    n = reader.get('/api/export').json()['notices'][0]
    change = n['changes'][0]
    assert decide(reader, n, change, decision='dismiss', verified=False, note='在新环境核实后排除旧线索').status_code == 200
    current = reader.get(f"/api/notices/{n['id']}/changes/{change['id']}").json()
    assert current['decision_note'] == '在新环境核实后排除旧线索'


@pytest.mark.parametrize('field,value', [('workflow', None), ('workflow', []), ('sources', ['broken']),
                                        ('change_data', None), ('impact', [{'diff': {'notes': {'before': '', 'after': 'override'}}}])])
def test_malformed_portable_records_are_rejected_without_server_errors(env, field, value):
    author = account(env); n, ids = setup_tasks(author)
    propose(author, n, proposal(n, ids[0]))
    payload = author.get('/api/export').json()
    if field == 'workflow':payload['notices'][0]['tasks'][0]['workflow'] = value
    elif field == 'sources':payload['notices'][0]['sources'] = value
    elif field == 'change_data':payload['notices'][0]['changes'][0]['data'] = value
    else:payload['notices'][0]['changes'][0]['impact'] = value
    reader = account(env, 'reader')
    assert reader.post('/api/import', json={'data': payload}).status_code == 422
    assert reader.get('/api/tasks').json() == []


def test_import_rejects_in_file_cycles_and_never_links_other_accounts(env):
    author = account(env); notice_ids, ids, exported = separate_steps(author)
    one = account(env, 'reader'); two = account(env, 'otherreader')
    first = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[0]]}
    assert import_file(one, first).status_code == 200
    second = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[1]]}
    assert import_file(two, second).status_code == 200
    assert two.get('/api/tasks').json()[0]['workflow']['dependencies'][0]['status'] == 'missing'
    broken = deepcopy(exported)
    next(n for n in broken['notices'] if n['id'] == notice_ids[0])['tasks'][0]['workflow']['data']['dependencies'] = [ids[1]]
    assert one.post('/api/import', json={'data': broken}).status_code == 422


def test_unresolved_branch_can_be_annotated_and_reexported_before_predecessor_arrives(env):
    author = account(env); notice_ids, ids, exported = separate_steps(author)
    reader = account(env, 'reader')
    later = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[1]]}
    assert import_file(reader, later).status_code == 200
    imported = reader.get('/api/tasks').json()[0]
    missing = imported['workflow']['data']['dependencies']
    saved = workflow(reader, imported['id'], next_step='等待前置通知迁移后继续准备')
    assert saved.status_code == 200, saved.text
    assert saved.json()['workflow']['data']['dependencies'] == missing
    denied = workflow(reader, imported['id'], stage='submitted', receipt='合成提交记录',
                      prepared_materials=imported['data']['materials'])
    assert denied.status_code == 422
    assert workflow(reader, imported['id'], dependencies=['invented-link']).status_code == 422
    next_reader = account(env, 'nextreader')
    assert import_file(next_reader, reader.get('/api/export').json()).status_code == 200
    earlier = {**exported, 'notices': [n for n in exported['notices'] if n['id'] == notice_ids[0]]}
    assert import_file(next_reader, earlier).status_code == 200
    tasks = next_reader.get('/api/tasks').json()
    first = next(t for t in tasks if t['data']['title'] == '跨通知步骤 0')
    second = next(t for t in tasks if t['data']['title'] == '跨通知步骤 1')
    assert second['workflow']['data']['dependencies'] == [first['id']]
    assert second['workflow']['data']['next_step'] == '等待前置通知迁移后继续准备'
