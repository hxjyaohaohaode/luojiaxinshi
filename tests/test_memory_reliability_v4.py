"""Version-bound evidence, contextual derivation and durable user intent."""
import json
import time
import uuid
import pytest

from app.db import ident
from app.memory import Memory,recall
from app.memory_store import insert_memory
from app.memory_policy import rows_for
from app.memory_lifecycle import remember_exposure,filter_history
from app.memory_context import runtime_fields
from test_workflow import env,account
from test_workspace import conversation
from test_memory_context import memory,uid,ACCESS
from test_memory_engine import message,items


def edit(c,item,**changes):
    return c.put('/api/memory/items/'+item['id'],json={**{k:item[k] for k in Memory.model_fields if k in item},'version':item['version'],**changes})


def exposure(env,c,chat,item):
    mid=message(env,c,chat,'请结合当前的记忆回答。')
    aid=ident()
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant',?,'complete',?,?)",
            (aid,chat['id'],'工程夹具：'+item['content'],mid,int(time.time())))
        remember_exposure(conn,uid(c),aid,[{'evidence_kind':'memory','memory_id':item['id']}])
    return aid


def test_feedback_cannot_credit_a_version_the_answer_never_saw(env):
    c=account(env);chat=conversation(c);saved=memory(c,content='旧版写作偏好')
    aid=exposure(env,c,chat,saved)
    updated=edit(c,saved,content='新版写作偏好').json()
    response=c.post('/api/memory/items/'+saved['id']+'/feedback',json={'version':updated['version'],'message_id':aid,'outcome':'helpful'})
    assert response.status_code==409
    trace=c.get(f"/api/conversations/{chat['id']}/messages/{aid}/memory-trace").json()['items'][0]
    assert trace['content']=='旧版写作偏好' and not trace['can_feedback']


def test_plain_edit_preserves_archived_state(env):
    c=account(env);saved=memory(c,content='待归档的手工资料')
    saved=c.put('/api/memory/items/'+saved['id']+'/lifecycle',json={'version':saved['version'],'tier':'long_term','status':'archived'}).json()
    changed=edit(c,saved,content='归档资料的文字修订')
    assert changed.status_code==200
    assert changed.json()['status']=='archived'


def test_natural_forget_matches_original_without_capture_prefix_and_punctuation(env):
    c=account(env);chat=conversation(c)
    message(env,c,chat,'记住，我喜欢黑咖啡。')
    assert any('黑咖啡' in item['content'] for item in items(c))
    message(env,c,chat,'请忘记我喜欢黑咖啡')
    assert not any('黑咖啡' in item['content'] for item in items(c))


def test_derived_memory_inherits_source_applicability(env):
    c=account(env);chat=conversation(c);parent=memory(c,content='核对原始来源',kind='constraint')
    parent=c.put('/api/memory/items/'+parent['id']+'/lifecycle',json={'version':parent['version'],'tier':'long_term','applies_to':['论文']}).json()
    with env[0].state.db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'申请材料核对原始来源的建议'},
            origin='agent',locked=False,parents=[parent])
    assert child not in {item['id'] for item in recall(env[0].state.db,uid(c),chat['id'],'申请材料核对',ACCESS)[0]}
    assert child in {item['id'] for item in recall(env[0].state.db,uid(c),chat['id'],'论文申请材料核对',ACCESS)[0]}


def test_forgetting_retires_answers_that_used_it_in_other_conversations(env):
    c=account(env);a=conversation(c);b=conversation(c)
    saved=memory(c,content='旧称呼为工程同学')
    aid=exposure(env,c,b,saved)
    assert c.request('DELETE','/api/memory/items/'+saved['id'],json={'version':saved['version']}).status_code==200
    with env[0].state.db.connect() as conn:
        result=filter_history(conn,uid(c),[{'id':aid,'content':'工程夹具：旧称呼为工程同学'}])
    assert '工程同学' not in result[0]['content']


def test_locked_working_memory_does_not_hide_independent_session_conditions(env):
    c=account(env);chat=conversation(c)
    current=c.get('/api/conversations/'+chat['id']+'/working-memory').json()
    assert c.put('/api/conversations/'+chat['id']+'/working-memory',json={'version':current['version'],'content':'本人固定的工作目标','locked':True}).status_code==200
    mid=message(env,c,chat,'我计划今天核对申请材料。')
    with env[0].state.db.connect() as conn:
        fields=runtime_fields(conn,uid(c),chat['id'],[{'id':mid,'role':'user','content':'我计划今天核对申请材料。'}])
    assert fields['_working_memory']=='本人固定的工作目标'
    assert '申请材料' in json.dumps(fields['_session_memory'],ensure_ascii=False)


def test_mutation_receipt_replays_once_without_resurrecting_forgotten_content(env):
    c=account(env);headers={'Idempotency-Key':str(uuid.uuid4())};body={'content':'人工唯一核对条件','kind':'constraint'}
    saved=c.post('/api/memory/items',json=body,headers=headers).json()
    assert c.post('/api/memory/items',json=body,headers=headers).json()['id']==saved['id']
    assert c.post('/api/memory/items',json={**body,'content':'另一个意图'},headers=headers).status_code==409
    update_headers={'Idempotency-Key':str(uuid.uuid4())}
    update={**body,'version':saved['version'],'content':'修订后的条件'}
    first=c.put('/api/memory/items/'+saved['id'],json=update,headers=update_headers)
    second=c.put('/api/memory/items/'+saved['id'],json=update,headers=update_headers)
    assert first.status_code==second.status_code==200 and first.json()['version']==second.json()['version']
    delete_headers={'Idempotency-Key':str(uuid.uuid4())}
    for _ in range(2):assert c.request('DELETE','/api/memory/items/'+saved['id'],json={'version':first.json()['version']},headers=delete_headers).status_code==200
    assert c.post('/api/memory/items',json=body,headers=headers).status_code==410
    with env[0].state.db.connect() as conn:
        assert all('条件' not in row['result'] for row in conn.execute('SELECT result FROM memory_mutation_receipts'))


def test_batch_version_conflict_rolls_back_every_selected_item(env):
    c=account(env);a=memory(c,content='批量条件甲');b=memory(c,content='批量条件乙')
    newer=edit(c,b,content='条件乙修订').json()
    body={'action':'archive','items':[{'id':item['id'],'version':item['version']} for item in (a,b)]}
    assert c.post('/api/memory/bulk',json=body).status_code==409
    assert c.get('/api/memory/items/'+a['id']).json()['status']=='active'
    body['items'][1]['version']=newer['version'];headers={'Idempotency-Key':str(uuid.uuid4())}
    first=c.post('/api/memory/bulk',json=body,headers=headers)
    assert first.status_code==200 and first.json()['count']==2
    assert c.post('/api/memory/bulk',json=body,headers=headers).json()['replayed']
    other=account(env,'batch-other')
    assert other.post('/api/memory/bulk',json={'action':'forget','items':body['items']}).status_code==404


def test_batch_cannot_enable_expired_records_or_silently_approve_proposals(env):
    c=account(env);a=memory(c,content='可以恢复的资料');b=memory(c,content='过期资料',expires_at=int(time.time())-1)
    payload={'action':'activate','items':[{'id':item['id'],'version':item['version']} for item in (a,b)]}
    assert c.post('/api/memory/bulk',json=payload).status_code==409
    assert c.get('/api/memory/items/'+a['id']).json()['version']==a['version']


def test_session_edits_keep_original_evidence_and_reject_stale_edit_or_promotion(env):
    c=account(env);chat=conversation(c);message(env,c,chat,'我计划今天核对原始材料。')
    entry=next(item for item in c.get('/api/memory/session-items').json()['items'] if item['kind']=='intention')
    body={'version':0,'content':'本会话改为先核对课程材料。','lifetime':'session'}
    edited=c.put('/api/memory/session-items/'+entry['id'],json=body)
    assert edited.status_code==200,edited.text
    assert edited.json()['original_content']==entry['content'] and edited.json()['edit_version']==1
    assert c.put('/api/memory/session-items/'+entry['id'],json=body).status_code==409
    assert c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'global','session_version':0}).status_code==409
    saved=c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'global','session_version':1})
    assert saved.status_code==200,saved.text
    actual=c.get('/api/memory/items/'+saved.json()['id']).json()
    assert actual['content']==body['content'] and actual['evidence'][0]['quote']==entry['content']


def test_metadata_edits_preserve_derived_sources_but_fact_changes_invalidate_them(env):
    c=account(env);chat=conversation(c);parent=memory(c,content='先核对来源',kind='constraint')
    with env[0].state.db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'核对来源的归纳'},origin='agent',parents=[parent],locked=False)
    updated=edit(c,parent,pinned=True,labels=['核对']).json()
    assert c.get('/api/memory/items/'+child).json()['state']=='active'
    assert child in {item['id'] for item in recall(env[0].state.db,uid(c),chat['id'],'核对来源',ACCESS)[0]}
    assert edit(c,updated,content='改为核对其他依据').status_code==200
    assert c.get('/api/memory/items/'+child).status_code==404


def test_feedback_history_does_not_carry_votes_to_new_content(env):
    c=account(env);chat=conversation(c);saved=memory(c,content='初版偏好')
    aid=exposure(env,c,chat,saved)
    assert c.post('/api/memory/items/'+saved['id']+'/feedback',json={'version':saved['version'],'message_id':aid,'outcome':'helpful'}).status_code==200
    newer=edit(c,saved,content='修订偏好').json()
    assert newer['positive']==0
    aid2=exposure(env,c,chat,newer)
    assert c.post('/api/memory/items/'+saved['id']+'/feedback',json={'version':newer['version'],'message_id':aid2,'outcome':'helpful'}).status_code==200
    assert c.get('/api/memory/items/'+saved['id']).json()['positive']==1


def test_selected_snapshot_includes_conflicting_peers_and_source_ancestors(env):
    from app.context_snapshot import capture,assert_current
    from app.ai import AIError
    c=account(env);chat=conversation(c);parent=memory(c,content='核对依据',semantic_key='办理方式')
    with env[0].state.db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'办理方法概览'},origin='agent',parents=[parent],locked=False)
    with env[0].state.db.connect() as conn:snapshot=capture(conn,uid(c),chat['id'],{'memory':True}, {'memory-'+child})
    memory(c,content='采用相反的依据',semantic_key='办理方式')
    with env[0].state.db.connect() as conn:
        with pytest.raises(AIError):assert_current(conn,uid(c),chat['id'],snapshot)


def test_health_and_server_filters_cover_full_catalog_and_are_owner_scoped(env):
    c=account(env);a=memory(c,content='正常条件');b=memory(c,content='归档条件')
    c.post('/api/memory/bulk',json={'action':'archive','items':[{'id':b['id'],'version':b['version']}]})
    response=c.get('/api/memory?status=archived&limit=1').json()
    assert response['matched']==1 and response['memories'][0]['id']==b['id']
    health=c.get('/api/memory/health').json()
    assert health['states']['active']==health['states']['archived']==1
    other=account(env,'health-other');assert other.get('/api/memory/health').json()['total']==0


def test_reflection_quota_waits_without_charging_or_marking_provider_failure(env,monkeypatch):
    from app.memory_reflection import enqueue,run_one
    from test_memory_lifecycle_v3 import reflection_fixture
    from app import security
    from fastapi import HTTPException
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    def unavailable(*args,**kwargs):raise HTTPException(429,'quota',headers={'Retry-After':'3600'})
    monkeypatch.setattr(security,'rate_limit',unavailable)
    def provider(*args):raise AssertionError('No provider call is permitted')
    assert run_one(env[0].state.db,env[1],provider)['deferred']
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT state FROM memory_reflection_jobs').fetchone()[0]=='queued'
        assert conn.execute('SELECT not_before FROM memory_reflection_leases').fetchone()[0]>int(time.time())
        assert not conn.execute('SELECT 1 FROM memory_reflection_attempts').fetchone()


def test_forgetting_job_snapshot_does_not_reset_reflection_budget(env):
    from app.memory_reflection import enqueue,run_one
    from test_memory_lifecycle_v3 import reflection_fixture
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    assert run_one(env[0].state.db,env[1],lambda *_:({'proposals':[]},{}))['processed']==1
    assert c.request('DELETE','/api/memory/items/'+a['id'],json={'version':a['version']}).status_code==200
    memory(c,content='新的来源条件',kind='constraint')
    with env[0].state.db.connect(write=True) as conn:assert enqueue(conn,uid(c))==1
    def forbidden(*args):raise AssertionError('The consumed daily budget survives forgetting')
    assert run_one(env[0].state.db,env[1],forbidden)['processed']==0


def test_language_negation_and_business_description_do_not_become_wrong_style_defaults():
    from app.memory_lifecycle import canonical,facet
    assert canonical('以后不要用英文回答，只用中文回答。')=='zh'
    assert canonical('以后不要中文回答。')=='avoid_zh'
    assert facet('本项目使用英文材料。')!='style.language'
    assert facet('这份资料很简洁。')!='style.length'


def test_explicit_reflection_retry_is_idempotent_and_requires_new_billing_intent(env):
    from app.memory_reflection import enqueue,run_one
    from test_memory_lifecycle_v3 import reflection_fixture
    c,chat,a,b=reflection_fixture(env)
    options=c.get('/api/memory/lifecycle').json()['settings']
    assert c.put('/api/memory/lifecycle/settings',json={**options,'reflection_budget':2}).status_code==200
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    def fail(*args):raise TimeoutError('fixture')
    assert run_one(env[0].state.db,env[1],fail)['failed']
    job=c.get('/api/memory/lifecycle').json()['reflection_jobs'][0]
    url='/api/memory/reflections/'+job['id']+'/retry'
    assert c.post(url,json={'finished_at':job['finished_at']}).status_code==422
    body={'finished_at':job['finished_at'],'allow_external_processing':True}
    assert c.post(url,json=body).status_code==200
    assert c.post(url,json=body).json()['already_queued']
    assert run_one(env[0].state.db,env[1],lambda *_:({'proposals':[]},{}))['processed']==1
    with env[0].state.db.connect() as conn:assert conn.execute('SELECT count(*) FROM memory_reflection_attempts').fetchone()[0]==2


def test_v3_migration_preserves_data_and_requires_complete_v4_tables(env):
    from app.db import Database
    from app.memory_reliability_schema import TABLES
    c=account(env);saved=memory(c,content='迁移前本人资料')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE meta SET value='3' WHERE key='memory_engine_schema_version'")
        for table in TABLES:conn.execute('DROP TABLE '+table)
    reopened=Database(env[0].state.db.path)
    with reopened.connect() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='memory_engine_schema_version'").fetchone()[0]=='4'
        assert conn.execute('SELECT content FROM personal_memories WHERE id=?',(saved['id'],)).fetchone()[0]=='迁移前本人资料'
    with reopened.connect(write=True) as conn:conn.execute('DROP TABLE memory_mutation_receipts')
    with pytest.raises(RuntimeError):Database(reopened.path)


@pytest.mark.parametrize('status',['archived','cooling'])
def test_paused_project_override_does_not_hide_usable_general_default(env,status):
    from test_memory_context import project,context
    c=account(env);chat=conversation(c);p=project(c)
    general=memory(c,content='一般回答使用中文',semantic_key='语言')
    override=memory(c,content='这个项目回答使用英文',semantic_key='语言',scope='project',project_id=p['id'])
    context(c,chat,project_id=p['id'])
    c.put('/api/memory/items/'+override['id']+'/lifecycle',json={'version':override['version'],'tier':'long_term','status':status})
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'材料回答',ACCESS)
    assert general['id'] in {item['id'] for item in selected}
    assert override['id'] not in {item['id'] for item in selected}
    assert general['id'] in {item['id'] for item in c.get('/api/conversations/'+chat['id']+'/memory-preview').json()['eligible']}


def test_scenario_override_only_blocks_default_in_its_actual_scenario(env):
    from test_memory_context import project,context
    c=account(env);chat=conversation(c);p=project(c)
    general=memory(c,content='回答先核对材料',semantic_key='办理方式')
    specific=memory(c,content='论文材料需要学校模板',semantic_key='办理方式',scope='project',project_id=p['id'])
    c.put('/api/memory/items/'+specific['id']+'/lifecycle',json={'version':specific['version'],'tier':'long_term','applies_to':['论文']})
    context(c,chat,project_id=p['id'])
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'核对课程材料',ACCESS)
    assert general['id'] in {item['id'] for item in selected}
    assert specific['id'] not in {item['id'] for item in selected}


def test_conflict_resolution_does_not_include_paused_peers(env):
    c=account(env);a=memory(c,content='采用甲方案',semantic_key='方案');b=memory(c,content='采用乙方案',semantic_key='方案')
    paused=memory(c,content='旧方案已停止',semantic_key='方案')
    c.post('/api/memory/bulk',json={'action':'archive','items':[{'id':paused['id'],'version':paused['version']}]})
    group=c.get('/api/memory/items/'+a['id']+'/conflicts').json()
    assert group['total']==2 and set(group['versions'])=={a['id'],b['id']}
    result=c.post('/api/memory/items/'+a['id']+'/resolve',json={'versions':group['versions']})
    assert result.status_code==200 and result.json()['deactivated']==[b['id']]
    assert c.get('/api/memory/items/'+paused['id']).json()['status']=='archived'


def test_session_goal_exposure_can_be_withdrawn_and_detail_is_owner_scoped(env):
    from app.context_snapshot import bind_sessions
    c=account(env);chat=conversation(c);text='请帮我安排专项工程目标'
    message(env,c,chat,text)
    short=c.get('/api/memory/session-items').json()['items'];goal=next(item for item in short if item['kind']=='goal')
    with env[0].state.db.connect() as conn:fields=runtime_fields(conn,uid(c),chat['id'],[{'role':'user','content':text}])
    assert goal['id'] in bind_sessions({},fields)['session_ids']
    assert c.get('/api/memory/session-items/'+goal['id']).json()['edit_version']==0
    other=account(env,'session-detail-other');assert other.get('/api/memory/session-items/'+goal['id']).status_code==404


def test_restarting_v4_does_not_double_reflection_attempt_count(env):
    from app.db import Database
    from app.memory_reflection import enqueue,run_one
    from test_memory_lifecycle_v3 import reflection_fixture
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    run_one(env[0].state.db,env[1],lambda *_:({'proposals':[]},{}))
    reopened=Database(env[0].state.db.path)
    with reopened.connect() as conn:assert conn.execute('SELECT count(*) FROM memory_reflection_attempts').fetchone()[0]==1


def test_late_reflection_claim_cannot_publish_a_proposal(env):
    from app.memory_reflection import enqueue,run_one
    from test_memory_lifecycle_v3 import reflection_fixture
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    def stolen_claim(*args):
        with env[0].state.db.connect(write=True) as conn:conn.execute("UPDATE memory_reflection_leases SET token='newer-claim'")
        return {'proposals':[{'content':'不能写入的迟到提议','source_memory_ids':[a['id'],b['id']],'kind':'skill'}]},{}
    assert run_one(env[0].state.db,env[1],stolen_claim)['cancelled']
    assert not any(item['content']=='不能写入的迟到提议' for item in items(c))


def test_evidence_links_each_actual_conversation_and_retains_parent_revision_body(env):
    c=account(env);a=conversation(c);b=conversation(c)
    first=message(env,c,a,'第一处工程来源');second=message(env,c,b,'第二处工程来源')
    with env[0].state.db.connect(write=True) as conn:
        key=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'fact','content':'两处来源的工程归纳'},origin='agent',locked=False,
            evidence=[{'source_kind':'message','source_id':first,'quote':'第一处工程来源'},
                      {'source_kind':'message','source_id':second,'quote':'第二处工程来源'}])
    detail=c.get('/api/memory/items/'+key).json()
    assert {row['conversation_id'] for row in detail['evidence']}=={a['id'],b['id']}
    parent=memory(c,content='形成时的依据正文')
    with env[0].state.db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'有版本依据的概览'},origin='agent',parents=[parent],locked=False)
    edit(c,parent,pinned=True)
    link=c.get('/api/memory/items/'+child).json()['links'][0]
    assert link['content']=='形成时的依据正文' and link['parent_version']==1 and link['current_version']==2 and link['source_current']


def test_reflection_dribbling_response_has_an_overall_deadline(env,monkeypatch):
    from app import memory_reflection,notice_stream
    class Response:
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_bytes(self):yield b'first';yield b'late'
    class Client(Response):
        def __init__(self,*args,**kwargs):pass
        def stream(self,*args,**kwargs):return Response()
    ticks=iter([0,1,100])
    monkeypatch.setattr(memory_reflection.httpx,'Client',Client)
    monkeypatch.setattr(memory_reflection.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(notice_stream,'read_reply',lambda response,trace:(b''.join(response.iter_bytes()),'stop'))
    with pytest.raises(TimeoutError):memory_reflection.provider_call(env[1],{})


def test_ten_thousand_conflicting_values_have_a_bounded_catalog_preview():
    from app.memory_policy import catalog
    entries=[{'id':str(index),'content':'方案 '+str(index),'semantic_key':'方案','scope':'global','project_id':None,'topic':'','active':True} for index in range(10000)]
    result=catalog(entries)
    assert len(result)==10000 and all(item['state']=='conflict' and item['conflict_count']==9999 for item in result)
    assert all(len(item['conflicts'])<=20 and item['id'] not in item['conflicts'] for item in result)


@pytest.mark.parametrize('state',['archived','cooling','inactive'])
def test_restore_changes_content_without_reactivating_paused_memory(env,state):
    c=account(env);saved=memory(c,content='最初的工程条件')
    if state=='inactive':saved=edit(c,saved,active=False).json()
    else:saved=c.put('/api/memory/items/'+saved['id']+'/lifecycle',json={'version':saved['version'],'tier':'long_term','status':state}).json()
    saved=edit(c,saved,content='后来修订的工程条件').json()
    restored=c.post('/api/memory/items/'+saved['id']+'/restore',json={'version':saved['version'],'revision':1})
    assert restored.status_code==200
    assert restored.json()['content']=='最初的工程条件' and restored.json()['state']==state


def test_markdown_edit_refreshes_semantics_and_preserves_cooling(env):
    c=account(env);saved=memory(c,content='我希望使用中文回答',kind='preference')
    saved=c.put('/api/memory/items/'+saved['id']+'/lifecycle',json={'version':saved['version'],'tier':'long_term','status':'cooling'}).json()
    text=c.get('/api/memory/items/'+saved['id']+'/markdown').text.replace('我希望使用中文回答','我希望使用英文回答')
    assert c.post('/api/memory/import',json={'format':'markdown','text':text}).status_code==200
    current=c.get('/api/memory/items/'+saved['id']).json()
    assert current['status']=='cooling' and current['canonical_value']=='en'
