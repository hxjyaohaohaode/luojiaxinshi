from test_workflow import env,account,notice,manual,task
from concurrent.futures import ThreadPoolExecutor


def seed(client):
    n=manual(client,notice(client))
    response=client.post(f"/api/notices/{n['id']}/confirm",json={
        'version':n['version'],'reviewed':True,
        'tasks':[task(n,title=f'看板事项 {i}') for i in range(3)]})
    assert response.status_code==200,response.text
    return client.get('/api/tasks').json()


def body(record,lane='action',**kwargs):
    return {'task_version':record['version'],'workflow_version':record['workflow']['version'],'lane':lane,**kwargs}


def move(client,record,lane='action',**kwargs):
    return client.post(f"/api/tasks/{record['id']}/move",json=body(record,lane,**kwargs))


def test_board_order_survives_refresh_without_changing_requirements(env):
    c=account(env);a,b,d=seed(c)
    response=move(c,d,before_id=a['id'])
    assert response.status_code==200,response.text
    records=c.get('/api/tasks').json()
    ordered=sorted(records,key=lambda t:t['workflow']['data']['board_order'])
    assert [t['id'] for t in ordered]==[d['id'],a['id'],b['id']]
    assert next(t for t in records if t['id']==d['id'])['data']==d['data']
    # Original task version / calendar export is unaffected by a priority-only move.
    assert [t['version'] for t in ordered]==[1,1,1]


def test_move_completion_and_undo_are_atomic_and_do_not_claim_submission(env):
    c=account(env);a,b,d=seed(c)
    response=move(c,a,'closed');assert response.status_code==200,response.text
    result=response.json();changed=next(t for t in result['tasks'] if t['id']==a['id'])
    assert changed['status']=='done'
    assert changed['workflow']['data']['stage']=='preparing'
    restored=c.post(f"/api/tasks/{a['id']}/move",json=result['undo'])
    assert restored.status_code==200,restored.text
    result=restored.json();changed=next(t for t in result['tasks'] if t['id']==a['id'])
    assert changed['status']=='pending'
    assert changed['workflow']['data']['board_lane'] is None
    assert changed['data']==a['data']


def test_followup_is_personal_placement_and_can_be_reordered(env):
    c=account(env);a,b,d=seed(c)
    assert c.get('/api/session').json()['task_board_contract']==1
    response=move(c,a,'followup');assert response.status_code==200,response.text
    current=next(t for t in response.json()['tasks'] if t['id']==a['id'])
    assert current['workflow']['data']['board_lane']=='followup'
    assert current['workflow']['data']['stage']=='preparing' and current['status']=='pending'
    response=move(c,b,'followup',before_id=a['id']);assert response.status_code==200,response.text
    records=response.json()['tasks']
    following=sorted((t for t in records if t['workflow']['data']['board_lane']=='followup'),key=lambda t:t['workflow']['data']['board_order'])
    assert [t['id'] for t in following]==[b['id'],a['id']]
    summary=c.get('/api/insights').json()
    assert next(g for g in summary['dimensions']['progress'] if g['key']=='followup')['count']==2


def test_completion_gate_failure_keeps_both_order_and_status(env):
    c=account(env);a,b,d=seed(c)
    workflow=dict(a['workflow']['data']);workflow['dependencies']=[b['id']]
    saved=c.put(f"/api/tasks/{a['id']}/workflow",json={'version':a['workflow']['version'],'task_version':a['version'],'data':workflow})
    assert saved.status_code==200,saved.text
    before=c.get('/api/tasks').json()
    response=move(c,saved.json(),'closed')
    assert response.status_code==422,response.text
    assert c.get('/api/tasks').json()==before


def test_stale_move_and_stale_undo_cannot_overwrite_new_progress(env):
    c=account(env);a,b,d=seed(c)
    first=move(c,a,'followup').json()
    current=next(t for t in first['tasks'] if t['id']==a['id'])
    second=move(c,current,'action')
    assert second.status_code==200,second.text
    assert move(c,a,'closed').status_code==409
    assert c.post(f"/api/tasks/{a['id']}/move",json=first['undo']).status_code==409
    assert c.get('/api/tasks').json()==second.json()['tasks']


def test_board_anchor_is_owner_scoped_and_filtered_moves_preserve_hidden_cards(env):
    c=account(env);a,b,d=seed(c)
    other=account(env,'bob');foreign=seed(other)[0]
    before=c.get('/api/tasks').json()
    assert move(c,d,before_id=foreign['id']).status_code==404
    assert move(other,a).status_code==404
    assert c.get('/api/tasks').json()==before
    response=move(c,d,before_id=b['id'])
    assert response.status_code==200,response.text
    assert [t['id'] for t in sorted(response.json()['tasks'],key=lambda t:t['workflow']['data']['board_order'])]==[a['id'],d['id'],b['id']]


def test_cancelled_card_cannot_be_reopened_by_drag(env):
    c=account(env);a,b,d=seed(c)
    cancelled=c.put(f"/api/tasks/{a['id']}",json={'version':a['version'],'data':a['data'],'status':'cancelled','reason':'测试取消'}).json()
    response=move(c,cancelled,'action')
    assert response.status_code==422
    assert next(t for t in c.get('/api/tasks').json() if t['id']==a['id'])['status']=='cancelled'


def test_undo_survives_a_moved_neighbor_without_overwriting_it(env):
    c=account(env);a,b,d=seed(c)
    result=move(c,a,'closed').json()
    neighbor=next(t for t in result['tasks'] if t['id']==b['id'])
    assert move(c,neighbor,'followup').status_code==200
    response=c.post(f"/api/tasks/{a['id']}/move",json=result['undo'])
    assert response.status_code==200,response.text
    restored={t['id']:t for t in response.json()['tasks']}
    assert restored[a['id']]['status']=='pending'
    assert restored[b['id']]['workflow']['data']['board_lane']=='followup'


def test_concurrent_moves_of_the_same_card_have_one_winner(env):
    c=account(env);a,b,d=seed(c)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda lane:move(c,a,lane),['followup','closed']))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert len(c.get('/api/tasks').json())==3
