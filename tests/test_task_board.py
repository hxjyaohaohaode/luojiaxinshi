from test_workflow import env,account,notice,manual,task
from concurrent.futures import ThreadPoolExecutor


def seed(client):
    n=manual(client,notice(client))
    response=client.post(f"/api/notices/{n['id']}/confirm",json={
        'version':n['version'],'reviewed':True,
        'tasks':[task(n,title=f'看板事项 {i}') for i in range(3)]})
    assert response.status_code==200,response.text
    # Read the same bounded projection that supplies the visible board.
    return client.get('/api/tasks/page',params={'status':'all'}).json()['items']


def body(record,lane='action',**kwargs):
    return {'task_version':record['version'],'workflow_version':record['workflow']['version'],'lane':lane,**kwargs}


def move(client,record,lane='action',**kwargs):
    return client.post(f"/api/tasks/{record['id']}/move",json=body(record,lane,**kwargs))


def seed_paged_board(client):
    # Two ordinary confirmations create an actual second page. Distinct notice
    # bodies avoid collapsing the batches into an idempotent intake replay.
    for batch in range(2):
        n=manual(client,notice(client,text=f'跨页看板夹具批次 {batch}：本人整理事项，不外发。'))
        response=client.post(f"/api/notices/{n['id']}/confirm",json={
            'version':n['version'],'reviewed':True,
            'tasks':[task(n,title=f'跨页看板 {batch*30+i:02d}') for i in range(30)]})
        assert response.status_code==200,response.text
    first=client.get('/api/tasks/page',params={'status':'all','limit':50}).json()
    second=client.get('/api/tasks/page',params={'status':'all','limit':50,'cursor':first['next_cursor']}).json()
    assert first['total']==60 and len(first['items'])==50 and len(second['items'])==10
    assert not second['has_more']
    return first['items']+second['items']


def test_second_page_card_moved_to_top_survives_the_board_first_page_reload(env):
    c=account(env);before=seed_paged_board(c);original_ids=[t['id'] for t in before]
    first=c.get('/api/tasks/page',params={'status':'all','sort':'board','limit':50})
    assert first.status_code==200,first.text
    old_cursor=first.json()['next_cursor'];target=before[55]
    assert target['id'] not in [t['id'] for t in first.json()['items']]
    saved=move(c,target,before_id=before[0]['id'])
    assert saved.status_code==200,saved.text
    # This is the real post-move reload, not sorting the 60-item move response.
    # The old implementation returned 200 but selected the original 50 records,
    # so the successfully prioritized second-page card disappeared from view.
    reloaded=c.get('/api/tasks/page',params={'status':'all','sort':'board','limit':50})
    assert reloaded.status_code==200,reloaded.text
    page=reloaded.json()
    assert page['items'][0]['id']==target['id'], 'The prioritized second-page card must be on the refreshed first board page'
    rest=c.get('/api/tasks/page',params={'status':'all','sort':'board','limit':50,'cursor':page['next_cursor']})
    assert rest.status_code==200,rest.text
    records=page['items']+rest.json()['items'];ids=[t['id'] for t in records]
    assert ids==[target['id']]+[tid for tid in original_ids if tid!=target['id']]
    assert len(ids)==len(set(ids))==60 and not rest.json()['has_more']
    assert {t['id']:(t['data'],t['version'],t['status']) for t in records}=={
        t['id']:(t['data'],t['version'],t['status']) for t in before}
    # Personal priority must not silently change the ordinary list contract.
    plain=c.get('/api/tasks/page',params={'status':'all','limit':50}).json()
    assert [t['id'] for t in plain['items']]==original_ids[:50]
    stale=c.get('/api/tasks/page',params={'status':'all','sort':'board','limit':50,'cursor':old_cursor})
    assert stale.status_code==409 and stale.json()['detail']['code']=='list_changed'


def test_board_page_cursor_binds_owner_filters_and_explicit_sort_mode(env):
    c=account(env);records=seed(c);other=account(env,'bob');foreign=seed(other)
    params={'status':'all','limit':1}
    plain=c.get('/api/tasks/page',params=params).json()
    board=c.get('/api/tasks/page',params={**params,'sort':'board'}).json()
    assert plain['order']=='created_at_desc_id_desc' and 'sort' not in plain['filters']
    assert board['order']=='board_order_asc_created_at_desc_id_desc'
    assert board['filters']['sort']=='board'
    assert c.get('/api/tasks/page',params={**params,'cursor':board['next_cursor']}).status_code==422
    assert c.get('/api/tasks/page',params={**params,'sort':'board','cursor':plain['next_cursor']}).status_code==422
    assert c.get('/api/tasks/page',params={**params,'sort':'board','q':'看板','cursor':board['next_cursor']}).status_code==422
    assert other.get('/api/tasks/page',params={**params,'sort':'board','cursor':board['next_cursor']}).status_code==422
    assert c.get('/api/tasks/page',params={**params,'sort':'invalid'}).status_code==422
    # Naming the established sort is equivalent to omitting it, including for
    # an already issued list cursor. It does not accidentally opt into priority.
    explicit=c.get('/api/tasks/page',params={**params,'sort':'created','cursor':plain['next_cursor']})
    assert explicit.status_code==200,explicit.text
    assert explicit.json()['items'][0]['id']==records[1]['id']
    selected=c.get('/api/tasks/page',params={'sort':'board','ids':','.join(t['id'] for t in [records[0],foreign[0]])})
    assert selected.status_code==200,selected.text
    assert [t['id'] for t in selected.json()['items']]==[records[0]['id']]


def test_board_pages_preserve_each_complete_lane_and_filtered_hidden_cards(env):
    c=account(env);before=seed_paged_board(c);original_ids=[t['id'] for t in before]
    action,following,last=before[55:58]
    response=move(c,action,before_id=before[0]['id'])
    assert response.status_code==200,response.text
    current={t['id']:t for t in response.json()['tasks']}
    response=move(c,current[following['id']],'followup')
    assert response.status_code==200,response.text
    current={t['id']:t for t in response.json()['tasks']}
    response=move(c,current[last['id']],'followup',before_id=following['id'])
    assert response.status_code==200,response.text
    expected_action=[action['id']]+[tid for tid in original_ids if tid not in {action['id'],following['id'],last['id']}]
    expected_followup=[last['id'],following['id']]
    # Walk small pages so each lane crosses several boundaries, including tied
    # priorities from different lanes. Every card must appear exactly once.
    cursor='';records=[]
    while True:
        response=c.get('/api/tasks/page',params={'sort':'board','status':'all','limit':7,'cursor':cursor})
        assert response.status_code==200,response.text
        page=response.json();assert page['total']==60 and len(page['items'])<=7
        records.extend(page['items'])
        assert len(records)<=60
        if not page['has_more']:break
        assert page['items'] and page['next_cursor'] and page['next_cursor']!=cursor
        cursor=page['next_cursor']
    ids=[t['id'] for t in records]
    assert len(ids)==len(set(ids))==60 and set(ids)==set(original_ids)
    assert [t['id'] for t in records if t['workflow']['data'].get('board_lane')!='followup']==expected_action
    assert [t['id'] for t in records if t['workflow']['data'].get('board_lane')=='followup']==expected_followup
    # Semantic filtering and explicit lane filtering must choose from that same
    # complete order, not reorder only an already selected creation-first page.
    for params in ({'status':'pending'},{'status':'followup'},{'lane':'followup'}):
        response=c.get('/api/tasks/page',params={'sort':'board','limit':100,**params})
        assert response.status_code==200,response.text
        assert [t['id'] for t in response.json()['items']]==(ids if params=={'status':'pending'} else expected_followup)
    selection=[action['id'],before[30]['id'],before[-1]['id']]
    response=c.get('/api/tasks/page',params={'sort':'board','ids':','.join(reversed(selection)),'limit':2})
    assert response.status_code==200,response.text
    selected=response.json()
    assert selected['total']==3 and [t['id'] for t in selected['items']]==selection[:2]
    tail=c.get('/api/tasks/page',params={'sort':'board','ids':','.join(reversed(selection)),'limit':2,'cursor':selected['next_cursor']})
    assert tail.status_code==200,tail.text
    assert [t['id'] for t in tail.json()['items']]==selection[2:] and not tail.json()['has_more']
    # Filtering never changes the persisted priority of cards hidden by it.
    unchanged=c.get('/api/tasks/page',params={'sort':'board','status':'all','limit':100}).json()
    assert [t['id'] for t in unchanged['items']]==ids


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


def test_first_move_preserves_paged_order_when_legacy_update_order_differs(env):
    c=account(env);seed(c)
    before=c.get('/api/tasks/page',params={'status':'all'}).json()['items']
    a,b,d=before
    # Force the full legacy list into the reverse of the visible page without
    # changing the created_at/id order or the original requirements.
    with env[0].state.db.connect(write=True) as conn:
        base=max(item['updated_at'] for item in before)+1
        for index,item in enumerate(before):
            conn.execute('UPDATE tasks SET updated_at=? WHERE id=?',(base+index,item['id']))
    assert [t['id'] for t in c.get('/api/tasks').json()]==[d['id'],b['id'],a['id']]
    result=move(c,d,before_id=a['id'])
    assert result.status_code==200,result.text
    persisted=c.get('/api/tasks/page',params={'status':'all'}).json()['items']
    ordered=sorted(persisted,key=lambda t:t['workflow']['data']['board_order'])
    assert [t['id'] for t in ordered]==[d['id'],a['id'],b['id']]
    assert {t['id']:t['data'] for t in persisted}=={t['id']:t['data'] for t in before}


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
