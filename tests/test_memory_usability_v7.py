"""Adversarial owner/version/search/layout tests against the real HTTP + DB."""
import time
import pytest
from app.db import dumps
from app.memory import recall
from app.memory_learning import drain_jobs
from app.memory_tree import catalog,ancestry,place
from test_workflow import env,account,notice
from test_workspace import conversation
from test_memory_context import memory,project,uid,ACCESS
from test_memory_engine import message,actions
from test_memory_tree_v6 import tree,entries,supplied_source


def folder(c,parent,title):
    r=c.post('/api/memory/tree/folders',json={'parent_id':parent,'title':title});assert r.status_code==200,r.text
    return r.json()


def test_project_folder_labels_and_multiple_terms_are_searchable(env):
    c=account(env);p=project(c,'极光竞赛');m=memory(c,scope='project',project_id=p['id'],content='使用作者年份引用',labels=['论文写作'])
    root=tree(c)['root_id'];target=folder(c,root,'待整理的资料')
    assert c.put('/api/memory/items/'+m['id']+'/placement',json={'node_id':target['id'],'version':1}).status_code==200
    for query in ['极光竞赛','论文写作','待整理的资料','极光竞赛 作者年份']:
        assert [r['id'] for r in entries(c,q=query)['memories']]==[m['id']]
    assert not entries(c,q='不存在 作者年份')['memories']
    assert entries(c,target['id'],q='作者年份')['memories'][0]['path'].endswith('待整理的资料')


def test_mixed_result_pages_are_exact_stable_and_filtered(env):
    c=account(env);db=env[0].state.db
    for i in range(6):memory(c,content=f'个人记录 {i}')
    notice(c,text='极光标记。'*650);drain_jobs(db,uid=uid(c));tree(c)
    full=entries(c,limit=100);ids=[]
    for offset in range(0,full['matched'],3):
        page=entries(c,limit=3,offset=offset);assert len(page['memories'])+len(page['passages'])<=3
        ids.extend(r['id'] for r in page['order'])
    assert len(ids)==len(set(ids))==full['matched']
    assert set(ids)=={r['id'] for r in full['order']}
    assert not entries(c,view='memories')['passages']
    assert not entries(c,view='passages')['memories']
    assert entries(c,view='passages',q='通知原文 极光')['passages']
    assert not entries(c,state='inactive')['passages']
    reverse=entries(c,sort='oldest',limit=100)
    times={m['id']:m['updated_at'] for m in reverse['memories']}|{p['id']:p['created_at'] for p in reverse['passages']}
    assert [times[r['id']] for r in reverse['order']]==sorted(times.values())


def test_locations_find_unopened_nested_duplicate_names_and_exclude_subtree(env):
    c=account(env);other=account(env,'other');root=tree(c)['root_id'];foreign=tree(other)['root_id']
    a=folder(c,root,'论文');b=folder(c,root,'课程');x=folder(c,a['id'],'资料');y=folder(c,b['id'],'资料');folder(c,x['id'],'调研')
    got=c.get('/api/memory/tree/locations',params={'q':'论文 资料'}).json()
    assert {r['title'] for r in got['nodes']}=={'资料','调研'}
    assert all(r['path'].startswith('全部记忆 / 论文 / 资料') for r in got['nodes'])
    filtered=c.get('/api/memory/tree/locations',params={'exclude':a['id']}).json()
    assert x['id'] not in {r['id'] for r in filtered['nodes']} and y['id'] in {r['id'] for r in filtered['nodes']}
    assert c.get('/api/memory/tree/locations',params={'exclude':foreign}).status_code==404


def test_folder_rename_then_recreate_does_not_reuse_stale_path_key(env):
    c=account(env);root=tree(c)['root_id'];a=folder(c,root,'草稿')
    r=c.put('/api/memory/tree/folders/'+a['id'],json={'title':'定稿','parent_id':root,'version':1});assert r.status_code==200
    b=folder(c,root,'草稿');assert b['id']!=a['id'] and b['title']=='草稿'
    assert folder(c,root,'草稿')['id']==b['id']
    assert c.put('/api/memory/tree/folders/'+b['id'],json={'title':'定稿','parent_id':root,'version':1}).status_code==409


def test_dissolve_preserves_children_placements_versions_and_contents(env):
    c=account(env);root=tree(c)['root_id'];a=folder(c,root,'容器');child=folder(c,a['id'],'同名');peer=folder(c,root,'同名')
    m=memory(c,content='必须保留的人工正文');tree(c)
    c.put('/api/memory/items/'+m['id']+'/placement',json={'node_id':a['id'],'version':1})
    n=memory(c,content='子目录正文');tree(c);c.put('/api/memory/items/'+n['id']+'/placement',json={'node_id':child['id'],'version':1})
    h={'Idempotency-Key':'dissolve-once'};body={'version':1}
    r=c.request('DELETE','/api/memory/tree/folders/'+a['id'],json=body,headers=h);assert r.status_code==200,r.text
    assert r.json()['preserved_memories']==1 and r.json()['preserved_folders']==1
    assert c.request('DELETE','/api/memory/tree/folders/'+a['id'],json=body,headers=h).json()['replayed']
    assert c.get('/api/memory/items/'+m['id']).json()['content']=='必须保留的人工正文'
    assert c.get('/api/memory/items/'+n['id']).json()['content']=='子目录正文'
    with env[0].state.db.connect() as conn:
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert conn.execute('SELECT node_id FROM memory_node_items WHERE memory_id=?',(m['id'],)).fetchone()[0]==root
        renamed=conn.execute('SELECT * FROM memory_nodes WHERE id=?',(child['id'],)).fetchone()
        assert renamed['parent_id']==root and renamed['title']=='同名（2）'
    assert folder(c,root,'容器')['id']!=a['id']


def test_dissolve_system_foreign_and_stale_guards(env):
    c=account(env);other=account(env,'other');root=tree(c)['root_id'];a=folder(c,root,'个人')
    assert c.request('DELETE','/api/memory/tree/folders/'+root,json={'version':1}).status_code==422
    assert c.request('DELETE','/api/memory/tree/folders/'+a['id'],json={'version':2}).status_code==409
    assert other.request('DELETE','/api/memory/tree/folders/'+a['id'],json={'version':1}).status_code==404
    assert c.get('/api/memory/tree',params={'parent_id':a['id']}).status_code==200


def test_batch_move_checks_every_version_before_mutating_and_replays(env):
    c=account(env);other=account(env,'other');a=memory(c,content='A');b=memory(c,content='B');root=tree(c)['root_id'];target=folder(c,root,'目标');foreign=tree(other)['root_id']
    body={'node_id':target['id'],'items':[{'id':a['id'],'version':1},{'id':b['id'],'version':2}]}
    assert c.put('/api/memory/tree/placements',json=body).status_code==409
    assert c.get('/api/memory/items/'+a['id']).json()['version']==1
    body['items'][1]['version']=1
    assert c.put('/api/memory/tree/placements',json={**body,'node_id':foreign}).status_code==404
    h={'Idempotency-Key':'move-entire-selection'}
    r=c.put('/api/memory/tree/placements',json=body,headers=h);assert r.status_code==200,r.text
    assert not r.json()['permissions_changed']
    assert c.put('/api/memory/tree/placements',json=body,headers=h).json()['replayed']
    assert all(m['version']==2 for m in entries(c,target['id'])['memories'])
    assert c.put('/api/memory/tree/placements',json={**body,'items':[body['items'][0]]*2}).status_code==422


def test_folder_create_edit_and_single_move_have_durable_receipts(env):
    c=account(env);root=tree(c)['root_id'];body={'parent_id':root,'title':'草稿'};h={'Idempotency-Key':'new-folder-retry'}
    a=c.post('/api/memory/tree/folders',json=body,headers=h).json()
    assert c.post('/api/memory/tree/folders',json=body,headers=h).json()['replayed']
    edit={**body,'title':'新名称','version':1};h={'Idempotency-Key':'edit-folder-retry'}
    assert c.put('/api/memory/tree/folders/'+a['id'],json=edit,headers=h).status_code==200
    assert c.put('/api/memory/tree/folders/'+a['id'],json=edit,headers=h).json()['replayed']
    m=memory(c);body={'node_id':a['id'],'version':1};h={'Idempotency-Key':'single-move-retry'}
    assert c.put('/api/memory/items/'+m['id']+'/placement',json=body,headers=h).status_code==200
    assert c.put('/api/memory/items/'+m['id']+'/placement',json=body,headers=h).json()['replayed']


def test_layout_restore_restores_owned_location_and_does_not_recreate_deleted_folder(env):
    c=account(env);root=tree(c)['root_id'];a=folder(c,root,'A');b=folder(c,root,'B');m=memory(c);tree(c)
    c.put('/api/memory/items/'+m['id']+'/placement',json={'node_id':a['id'],'version':1})
    c.put('/api/memory/items/'+m['id']+'/placement',json={'node_id':b['id'],'version':2})
    assert c.post('/api/memory/items/'+m['id']+'/restore',json={'version':3,'revision':2}).status_code==200
    assert len(entries(c,a['id'])['memories'])==1
    c.request('DELETE','/api/memory/tree/folders/'+a['id'],json={'version':1})
    saved=c.get('/api/memory/items/'+m['id']).json()
    assert c.post('/api/memory/items/'+m['id']+'/restore',json={'version':saved['version'],'revision':2}).status_code==200
    assert c.get('/api/memory/tree',params={'parent_id':a['id']}).status_code==404
    assert len(entries(c)['memories'])==1


def test_text_free_change_token_tracks_edits_and_sessions_but_is_stable_on_reads(env):
    c=account(env);tree(c);url='/api/memory/tree/status';before=c.get(url).json()['token']
    assert c.get(url).json()['token']==before
    m=memory(c,content='secret body not returned by status');after=c.get(url).json()
    assert after['token']!=before and 'secret body' not in dumps(after)
    tree(c);before=c.get(url).json()['token'];assert c.get(url).json()['token']==before
    chat=conversation(c);message(env,c,chat,'这次只需要中文回答。');drain_jobs(env[0].state.db,uid=uid(c))
    assert c.get(url).json()['token']!=before


def test_tree_catalog_ranks_relevant_full_paths_beyond_first_page(env):
    c=account(env);root=tree(c)['root_id']
    for i in range(40):folder(c,root,f'无关 {i}')
    a=folder(c,root,'极光观测');b=folder(c,a['id'],'实验方案')
    m=memory(c,content='极光实验使用蓝色标签');tree(c)
    c.put('/api/memory/items/'+m['id']+'/placement',json={'node_id':b['id'],'version':m['version']})
    with env[0].state.db.connect() as conn:
        got=catalog(conn,uid(c),4,'极光观测实验方案')
    assert b['id'] in {n['id'] for n in got} and any('极光观测 / 实验方案' in n['path'] for n in got)


def test_source_claim_cannot_be_converted_into_entire_index_by_source_sync(env):
    c=account(env);chat=conversation(c);text='极光观测地点是光学楼。';n=notice(c,text=text);sid=n['sources'][0]['id'];mid=message(env,c,chat,'整理一下',learn=False)
    supplied_source(env,c,chat,mid,sid,text)
    result=actions(env,c,chat,mid,{'operation':'source_remember','content':text,'source_evidence':{'source_id':sid,'locator':'第1段','quote':text}})[0]
    assert c.post('/api/memory/items/'+result['id']+'/source-sync',json={'version':1}).status_code==422
    assert c.get('/api/memory/items/'+result['id']).json()['content']==text


def test_forgetting_source_index_stops_other_source_claims_and_passage_api(env):
    c=account(env);chat=conversation(c);text='极光观测地点是光学楼。';n=notice(c,text=text);sid=n['sources'][0]['id'];mid=message(env,c,chat,'整理一下',learn=False)
    supplied_source(env,c,chat,mid,sid,text)
    claim=actions(env,c,chat,mid,{'operation':'source_remember','content':text,'source_evidence':{'source_id':sid,'locator':'第1段','quote':text}})[0]['id']
    drain_jobs(env[0].state.db,uid=uid(c));all=entries(c);unit=all['passages'][0]
    index=next(m for m in all['memories'] if m['origin']=='resource')
    assert c.request('DELETE','/api/memory/items/'+index['id'],json={'version':index['version']}).status_code==200
    assert c.get('/api/memory/passages/'+unit['id']).status_code==409
    assert c.get('/api/memory/items/'+claim).json()['state']=='source_changed'
    got,_=recall(env[0].state.db,uid(c),chat['id'],'极光观测地点',ACCESS)
    assert not any(m['id']==claim or m['origin']=='source_passage' for m in got)


@pytest.mark.parametrize('second',['Case Sensitive','case sensitive','Case  Sensitive'])
def test_idempotent_payloads_preserve_case_and_interior_spaces(env,second):
    c=account(env);root=tree(c)['root_id'];headers={'Idempotency-Key':'exact-payload-hash'}
    first=c.post('/api/memory/tree/folders',json={'parent_id':root,'title':'Case Sensitive'},headers=headers)
    assert first.status_code==200
    got=c.post('/api/memory/tree/folders',json={'parent_id':root,'title':second},headers=headers)
    assert got.status_code==(200 if second=='Case Sensitive' else 409)


def test_parent_counts_include_descendants_and_discard_blocked_source_passages(env):
    c=account(env);memory(c,content='人工记忆');notice(c,text='来源材料');drain_jobs(env[0].state.db,uid=uid(c))
    result=tree(c);all=entries(c)
    assert result['total_items']==all['matched']==sum(n['subtree_count'] for n in result['nodes'])
    assert next(n for n in result['nodes'] if n['node_key']=='layer:long')['subtree_count']>=1


def test_session_search_pagination_and_edited_text_are_consistent(env):
    c=account(env);chat=conversation(c);db=env[0].state.db;owner=uid(c);now=int(time.time())
    from app.db import ident
    # Three independent conversations keep this below the per-conversation
    # working-context retention bound while testing the global browser list.
    chats=[chat,conversation(c),conversation(c)]
    with db.connect(write=True) as conn:
        for i in range(125):
            cid=chats[i//50]['id'];mid=ident();sid=ident()
            conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",(mid,cid,f'条件 {i:03d}',now))
            conn.execute("INSERT INTO memory_session_items(id,user_id,conversation_id,source_message_id,kind,content,lifetime,created_at,expires_at) VALUES(?,?,?,?,'constraint',?,'session',?,?)",(sid,owner,cid,mid,f'条件 {i:03d}',now+i,now+86400))
    a=c.get('/api/memory/session-items',params={'q':'条件','limit':50,'offset':100}).json()
    assert a['matched']==125 and len(a['items'])==25
    sid=a['items'][0]['id'];edit=c.put('/api/memory/session-items/'+sid,json={'version':0,'content':'中文修订正文','lifetime':'session'})
    assert edit.status_code==200
    assert c.get('/api/memory/session-items',params={'q':'中文修订'}).json()['matched']==1
    assert c.get('/api/memory/session-items',params={'q':'条件'}).json()['matched']==124


def test_append_only_ai_edits_leave_every_original_character_untouched(env,monkeypatch):
    from test_memory_autonomy_v5 import enable_assist
    c=account(env);m=memory(c,content='😀原始要求不变。',kind='constraint');calls=enable_assist(env,monkeypatch,'补充申请材料。')
    r=c.post('/api/memory/items/'+m['id']+'/assist',json={'version':1,'start':len(m['content']),'end':len(m['content']),'instruction':'只补充申请材料','allow_external_processing':True},headers={'Idempotency-Key':'append-one-request'})
    assert r.status_code==200,r.text
    assert r.json()['content']==m['content']+'补充申请材料。' and len(calls)==1


def test_full_memory_rejects_append_before_requesting_ai(env,monkeypatch):
    from test_memory_autonomy_v5 import enable_assist
    c=account(env);m=memory(c,content='字'*2000);calls=enable_assist(env,monkeypatch,'补充')
    r=c.post('/api/memory/items/'+m['id']+'/assist',json={'version':1,'start':2000,'end':2000,'instruction':'继续补充','allow_external_processing':True},headers={'Idempotency-Key':'append-over-capacity'})
    assert r.status_code==422 and not calls


def test_progressive_view_keeps_full_source_searchable_without_flooding_overview(env):
    c=account(env);notice(c,text='背景材料。'*1800+'末尾完整信息：蓝光标志。');drain_jobs(env[0].state.db,uid=uid(c))
    overview=entries(c,view='auto');assert overview['memories'] and not overview['passages']
    search=entries(c,view='auto',q='蓝光标志');assert search['passages']
    file=entries(c,search['passages'][0]['node_id'],view='auto');assert file['passages'] and not file['memories']


def test_source_sync_cannot_bypass_a_source_forgetting_boundary(env):
    c=account(env);n=notice(c,text='资料来源必须尊重遗忘。');drain_jobs(env[0].state.db,uid=uid(c));m=entries(c)['memories'][0]
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('INSERT OR IGNORE INTO memory_blocked_sources VALUES(?,?,?,?)',(uid(c),'resource_notice',n['sources'][0]['id'],int(time.time())))
    assert c.post('/api/memory/items/'+m['id']+'/source-sync',json={'version':m['version']}).status_code==409


def test_tree_lifecycle_counts_are_complete_and_owner_scoped(env):
    c=account(env);other=account(env,'other');memory(c,content='本人的长期记录');memory(other,content='另一个账号的记录')
    result=tree(c);assert result['lifecycle_counts']=={'long_term':1}
    assert result['session_count']==0 and result['settings']['mode']=='auto'


@pytest.mark.parametrize('change',['content','deactivate','scope','forget'])
def test_directory_only_revisions_keep_conversation_context_but_real_changes_revoke_it(env,monkeypatch,change):
    from app import chat_ai
    from app.db import ident
    import uuid
    c=account(env);chat=conversation(c);m=memory(c,content='记录事实：极光实验使用蓝色标签。',kind='fact');db=env[0].state.db
    root=tree(c)['root_id'];target=folder(c,root,'目录整理');source=message(env,c,chat,'请解释实验记录',learn=False);aid=ident()
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant','应当保留的旧回答','complete',?,?)",(aid,chat['id'],source,int(time.time())))
        conn.execute('INSERT INTO reply_grounding VALUES(?,?,?)',(aid,dumps([{'id':'memory-'+m['id'],'evidence_kind':'memory','memory_version':1}]),'{}'))
        conn.execute("INSERT INTO memory_usage VALUES(?,?,1,'used',?)",(aid,m['id'],int(time.time())))
    assert c.put('/api/memory/items/'+m['id']+'/placement',json={'version':1,'node_id':target['id']}).status_code==200
    # Include a second location-only revision, from dissolving its container.
    assert c.request('DELETE','/api/memory/tree/folders/'+target['id'],json={'version':1}).status_code==200
    seen=[];env[1].ai_api_key='fixture'
    def reply(settings,sources,messages,profile):
        seen.append(messages);return {'answer':'fixture reply','citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',reply)
    def send():
        saved=c.get('/api/conversations/'+chat['id']).json()
        r=c.post('/api/conversations/'+chat['id']+'/messages',json={'version':saved['version'],'content':'继续解释前一条记录','request_id':uuid.uuid4().hex,'allow_external_processing':True})
        assert r.status_code==200,r.text
    send();assert any(row['content']=='应当保留的旧回答' for row in seen[-1])
    live=c.get('/api/memory/items/'+m['id']).json()
    if change=='forget':assert c.request('DELETE','/api/memory/items/'+m['id'],json={'version':live['version']}).status_code==200
    else:
        payload={key:live[key] for key in ('scope','project_id','topic','kind','content','source_conversation_id','active','pinned','version','locked','labels','semantic_key','valid_from','expires_at')}
        if change=='content':payload['content']='事实已改为红色标签。'
        if change=='deactivate':payload['active']=False
        if change=='scope':payload.update(scope='project',project_id=project(c,'无关项目')['id'])
        assert c.put('/api/memory/items/'+m['id'],json=payload).status_code==200
    send();assert not any(row['content']=='应当保留的旧回答' for row in seen[-1])


def test_model_memory_payload_redacts_credential_metadata_and_legacy_notes(env):
    from app.memory_context import runtime_fields
    from app.memory_tree import reconcile
    from test_memory_context import context
    c=account(env);chat=conversation(c);r=c.post('/api/memory/projects',json={'name':'api_key:catalog_secret_1','description':'password:catalog_secret_2'});assert r.status_code==200
    p=r.json()
    m=memory(c,scope='project',project_id=p['id'],content='课程申请资料必须齐全。密码：legacy_secret_3',labels=['token:label_secret_4'])
    context(c,chat,selection_mode='manual',project_id=p['id'])
    folder(c,tree(c)['root_id'],'client_secret:folder_secret_5')
    with env[0].state.db.connect() as conn:
        fields=runtime_fields(conn,uid(c),chat['id'],[{'role':'user','content':'课程申请需要什么'}])
    got,report=recall(env[0].state.db,uid(c),chat['id'],'课程申请',ACCESS)
    payload=dumps([fields,got])
    assert all(secret not in payload for secret in ('catalog_secret_1','catalog_secret_2','legacy_secret_3','label_secret_4','folder_secret_5'))
    assert '[凭证已省略]' in payload and report['context_bytes']<=8000
    # Only the model projection changes; owner-editable stored text is intact.
    assert c.get('/api/memory/items/'+m['id']).json()['content'].endswith('legacy_secret_3')


@pytest.mark.parametrize('kind',['long_token','pem'])
def test_full_section_mask_prevents_prefixless_secret_continuations(env,kind):
    from app.memory_resources import ingest_resource
    c=account(env);chat=conversation(c);db=env[0].state.db
    hidden='QZXSECRET'*400
    secret='sk-'+hidden if kind=='long_token' else '-----BEGIN RSA PRIVATE KEY-----\n'+hidden+'\n-----END RSA PRIVATE KEY-----'
    n=notice(c,text='safe fixture');sid=n['sources'][0]['id']
    with db.connect(write=True) as conn:
        conn.execute('UPDATE sources SET sections=? WHERE id=?',(dumps([{'locator':'第1段','text':'普通背景。'*90+secret+'\n有效的课程信息仍然保留。'}]),sid))
        ingest_resource(conn,uid(c),'resource_notice',sid)
    passages=entries(c,view='passages',limit=100)['passages'];assert len(passages)>=3
    assert all('QZXSECRET' not in p['content'] and 'PRIVATE KEY' not in p['content'] for p in passages)
    assert any('有效的课程信息' in p['content'] for p in passages)
    assert all(p['start_offset']%1200==0 for p in passages)


def test_old_cache_is_fenced_before_once_only_privacy_reindex(env):
    from app.db import Database
    c=account(env);db=env[0].state.db;n=notice(c,text='旧缓存重建后仍有有效内容。');drain_jobs(db,uid=uid(c))
    with db.connect(write=True) as conn:
        conn.execute("DELETE FROM meta WHERE key='memory_source_privacy_seed_v7'")
        conn.execute("UPDATE memory_source_units SET content='unmasked_old_cache'")
    reopened=Database(db.path)
    assert not entries(c,view='passages')['passages']
    drain_jobs(reopened,uid=uid(c));rebuilt=entries(c,view='passages')['passages']
    assert rebuilt and all('unmasked_old_cache' not in p['content'] for p in rebuilt)
    again=Database(db.path)
    with again.connect() as conn:
        assert conn.execute("SELECT count(*) FROM memory_jobs WHERE state='queued'").fetchone()[0]==0
        assert conn.execute("SELECT min(fingerprint) FROM memory_source_units").fetchone()[0]>0


def test_snapshot_dict_order_is_not_a_context_change_but_versions_still_are(env,monkeypatch):
    from app import context_snapshot
    from app.ai import AIError
    c=account(env);chat=conversation(c);db=env[0].state.db;ids={'memory-A','memory-B'};versions={'memory-A':1,'memory-B':2}
    monkeypatch.setattr(context_snapshot,'eligible_versions',lambda *args:dict(versions))
    access={**ACCESS,'memory':True}
    with db.connect() as conn:snap=context_snapshot.capture(conn,uid(c),chat['id'],access,ids)
    versions={'memory-B':2,'memory-A':1}
    with db.connect() as conn:context_snapshot.assert_current(conn,uid(c),chat['id'],snap)
    versions['memory-B']=3
    with db.connect() as conn:
        with pytest.raises(AIError):context_snapshot.assert_current(conn,uid(c),chat['id'],snap)


def test_legacy_snapshot_can_still_be_checked_without_rewriting_saved_reports(env):
    from app.context_snapshot import capture,assert_current
    c=account(env);chat=conversation(c)
    with env[0].state.db.connect() as conn:
        snap=capture(conn,uid(c),chat['id'],{**ACCESS,'memory':True},set(),canonical=False)
        assert snap['version']=='context-snapshot-v1';assert_current(conn,uid(c),chat['id'],snap)


def test_agent_catalog_does_not_reintroduce_forgotten_source_titles_or_empty_paths(env):
    from app.memory_resources import ingest_resource
    c=account(env);db=env[0].state.db;n=notice(c,text='用于检验目录隐私的资料。');sid=n['sources'][0]['id']
    with db.connect(write=True) as conn:
        conn.execute('UPDATE sources SET name=? WHERE id=?',('原始标题含有小林的个人信息',sid))
        ingest_resource(conn,uid(c),'resource_notice',sid)
    root=tree(c)['root_id'];folder(c,root,'空目录不应当作事实提示')
    with db.connect() as conn:before=catalog(conn,uid(c),100)
    assert any('小林' in n['path'] for n in before) and not any('空目录' in n['path'] for n in before)
    m=next(m for m in entries(c)['memories'] if m['origin']=='resource')
    assert c.request('DELETE','/api/memory/items/'+m['id'],json={'version':m['version']}).status_code==200
    with db.connect() as conn:after=catalog(conn,uid(c),100)
    assert not any('小林' in n['path'] for n in after)
