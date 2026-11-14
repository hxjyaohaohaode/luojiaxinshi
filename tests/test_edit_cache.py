import pytest

from test_workflow import env, account, notice, manual, confirm, task


def test_cache_round_trip_is_private_and_durable(env):
    alice=account(env);bob=account(env,'bob')
    route='/api/edit-cache/new-notice'
    assert alice.get(route).json()=={'revision':0,'payload':None}
    saved=alice.put(route,json={'revision':0,'payload':{'fields':{'title':'未提交的草稿'}}})
    assert saved.status_code==200
    assert alice.get(route).json()==saved.json()
    assert bob.get(route).json()=={'revision':0,'payload':None}


def test_stale_tab_cannot_overwrite_or_resurrect_cleared_draft(env):
    c=account(env);route='/api/edit-cache/new-notice'
    assert c.put(route,json={'revision':0,'payload':{'text':'当前内容'}}).status_code==200
    assert c.put(route,json={'revision':0,'payload':{'text':'旧内容'}}).status_code==409
    assert c.put(route,json={'revision':1,'payload':None}).status_code==200
    assert c.put(route,json={'revision':1,'payload':{'text':'迟到的自动保存'}}).status_code==409
    assert c.get(route).json()=={'revision':2,'payload':None}


def test_notice_cache_ownership_version_and_delete_cascade(env):
    a=account(env);b=account(env,'bob');n=notice(a)
    path=f"/api/edit-cache/notice:{n['id']}:{n['version']}"
    assert b.get(path).status_code==404
    assert b.put(path,json={'revision':0,'payload':{}}).status_code==404
    assert a.put(path,json={'revision':0,'payload':{'tasks':[]}}).status_code==200
    changed=a.post(f"/api/notices/{n['id']}/materials",json={'version':n['version'],'complete':False}).json()
    assert a.put(path,json={'revision':1,'payload':{'tasks':[]}}).status_code==409
    # Successful formal writes may retire caches from the previous version.
    assert a.put(path,json={'revision':1,'payload':None}).status_code==200
    assert a.request('DELETE',f"/api/notices/{n['id']}",json={'version':changed['version']}).status_code==200
    with env[0].state.db.connect() as db:
        assert db.execute('SELECT count(*) FROM edit_caches').fetchone()[0]==0


def test_task_form_cache_retired_after_versioned_save(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n)
    route=f'/api/edit-cache/task:{tid}:1'
    assert c.put(route,json={'revision':0,'payload':{'data':task(n)}}).status_code==200
    assert c.put('/api/tasks/'+tid,json={'version':1,'data':task(n),'status':'done','reason':'已完成'}).status_code==200
    assert c.get(route).status_code==409
    assert c.put(route,json={'revision':1,'payload':None}).status_code==200


@pytest.mark.parametrize('key',['arbitrary','notice:not-an-id:1','new-notice-2','task:'+'a'*32+':0'])
def test_cache_keys_are_bounded_and_validated(env,key):
    c=account(env)
    assert c.put('/api/edit-cache/'+key,json={'revision':0,'payload':{}}).status_code in {404,422}


def test_cache_payload_limit(env):
    c=account(env)
    assert c.put('/api/edit-cache/new-notice',json={'revision':0,'payload':{'body':'a'*180001}}).status_code==413


def test_pending_campus_publication_cache_is_private_versioned_and_not_authorization(env):
    alice=account(env);bob=account(env,'bob')
    route='/api/edit-cache/campus-publication'
    payload={'request_id':'publication_retry_2026','draft_id':'draft_retry_2026','draft_version':2,
             'title':'本人待核对的发布','body':'尚未确认是否发布成功的原始内容','audience':'college',
             'grade':'','class_name':'','audience_review':'a'*64}
    assert alice.get(route).json()=={'revision':0,'payload':None}
    saved=alice.put(route,json={'revision':0,'payload':payload})
    assert saved.status_code==200
    assert saved.json()=={'revision':1,'payload':payload}
    assert alice.get(route).json()==saved.json()
    assert bob.get(route).json()=={'revision':0,'payload':None}
    assert alice.put(route,json={'revision':0,'payload':{'request_id':'stale-replacement'}}).status_code==409
    # Saving an owner's recovery payload does not grant a campus publisher role.
    assert alice.post('/api/campus/publications',json=payload).status_code==403
    assert alice.put(route,json={'revision':1,'payload':None}).status_code==200
    assert alice.put(route,json={'revision':1,'payload':payload}).status_code==409
    assert alice.get(route).json()=={'revision':2,'payload':None}
