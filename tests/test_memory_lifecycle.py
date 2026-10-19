import json
import time

import pytest

from app import grounding
from app.ai import AIError
from app.context_snapshot import capture,assert_current,publication_current
from app.memory import recall,eligible_versions
from app.memory_policy import effective
from test_workflow import env,account
from test_workspace import conversation
from test_memory_context import memory,project,context,uid,ACCESS,import_export
from test_genui_transport import payload,events
from test_grounding import mocks


def test_exact_duplicates_reuse_the_record_but_distinct_provenance_stays_separate(env):
    c=account(env);first=memory(c,content='先给结论 ABC',semantic_key=' 写作方式 ')
    same=memory(c,content='先给结论  abc',semantic_key='写作方式')
    assert same['id']==first['id'] and same['version']==1
    chat=conversation(c)
    linked=memory(c,content='先给结论 ABC',semantic_key='写作方式',source_conversation_id=chat['id'])
    assert linked['id']!=first['id']


def test_expiry_scheduled_and_disabled_never_enter_recall_or_eligible_versions(env):
    c=account(env);chat=conversation(c);now=int(time.time());good=memory(c)
    memory(c,content='过期内容',expires_at=now)
    memory(c,content='未来内容',valid_from=now+3600)
    memory(c,content='停用内容',active=False)
    selected,report=recall(env[0].state.db,uid(c),chat['id'],'帮助我',ACCESS)
    assert [m['id'] for m in selected]==[good['id']]
    assert {r['reason'] for r in report['excluded']}=={'inactive','expired','scheduled'}
    with env[0].state.db.connect() as conn:
        assert eligible_versions(conn,uid(c),chat['id'],True)=={'memory-'+good['id']:1}


def test_specificity_conflict_and_atomic_resolution(env):
    c=account(env);chat=conversation(c);p=project(c)
    general=memory(c,content='用英文',semantic_key='写作语言')
    memory(c,scope='topic',topic='论文',content='用中文',semantic_key='写作语言')
    chosen=memory(c,scope='project',project_id=p['id'],content='中英对照',semantic_key='写作语言')
    context(c,chat,project_id=p['id'],topics=['论文'])
    selected,report=recall(env[0].state.db,uid(c),chat['id'],'写作',ACCESS)
    assert chosen['id'] in {m['id'] for m in selected} and general['id'] not in {m['id'] for m in selected}
    assert len([r for r in report['excluded'] if r['reason']=='shadowed'])==2
    conflict=memory(c,scope='project',project_id=p['id'],content='只用德文',semantic_key='写作语言')
    selected,report=recall(env[0].state.db,uid(c),chat['id'],'写作',ACCESS)
    assert not [m for m in selected if not m.get('project_context')]
    assert len([r for r in report['excluded'] if r['reason']=='conflict'])==2
    versions={chosen['id']:chosen['version'],conflict['id']:conflict['version']}
    wrong={**versions,conflict['id']:99}
    assert c.post('/api/memory/items/'+chosen['id']+'/resolve',json={'versions':wrong}).status_code==409
    assert c.get('/api/memory').json()['memories'][-1]['active']
    r=c.post('/api/memory/items/'+chosen['id']+'/resolve',json={'versions':versions});assert r.status_code==200,r.text
    assert r.json()['kept']['version']==2 and r.json()['deactivated']==[conflict['id']]
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'写作',ACCESS)
    assert chosen['id'] in {m['id'] for m in selected}


def test_cross_topic_conflicts_are_visible_and_cross_owner_resolve_is_denied(env):
    c=account(env);other=account(env,'other');chat=conversation(c)
    a=memory(c,scope='topic',topic='甲',content='值甲',semantic_key='同一事实')
    b=memory(c,scope='topic',topic='乙',content='值乙',semantic_key='同一事实')
    context(c,chat,topics=['甲','乙'])
    preview=c.get('/api/conversations/'+chat['id']+'/memory-preview').json()
    assert preview['eligible']==[] and {r['reason'] for r in preview['excluded']}=={'conflict'}
    assert other.get('/api/conversations/'+chat['id']+'/memory-preview').status_code==404
    assert other.post('/api/memory/items/'+a['id']+'/resolve',json={'versions':{a['id']:1,b['id']:1}}).status_code==404
    assert c.post('/api/memory/items/'+a['id']+'/resolve',json={'versions':{a['id']:1,b['id']:1}}).status_code==409


def test_lifecycle_metadata_survives_json_export_import_without_enabling_it(env):
    c=account(env);other=account(env,'other');now=int(time.time())
    memory(c,semantic_key='约束',valid_from=now,expires_at=now+3600)
    assert import_export(other,c.get('/api/export').json()).status_code==200
    imported=other.get('/api/memory').json()['memories'][0]
    assert imported['semantic_key']=='约束' and imported['valid_from']==now and imported['expires_at']==now+3600
    assert imported['state']=='inactive'


@pytest.mark.parametrize('value',[{'valid_from':10,'expires_at':10},{'valid_from':11,'expires_at':10},{'expires_at':-1}])
def test_invalid_lifecycle_is_atomic(env,value):
    c=account(env)
    assert c.post('/api/memory/items',json={'content':'正常内容',**value}).status_code==422
    assert c.get('/api/memory').json()['memories']==[]


@pytest.mark.parametrize('mutation',['edit','delete','conflict','expire','project'])
def test_context_changes_block_old_snapshots(env,monkeypatch,mutation):
    c=account(env);chat=conversation(c);now=int(time.time());item=memory(c,semantic_key='同类键',expires_at=now+50)
    p=project(c);context(c,chat,project_id=p['id'])
    owner=uid(c);db=env[0].state.db
    with db.connect() as conn:snapshot=capture(conn,owner,chat['id'],{**ACCESS,'memory':True})
    if mutation=='edit':assert c.put('/api/memory/items/'+item['id'],json={'version':1,'content':'新的内容'}).status_code==200
    elif mutation=='delete':assert c.request('DELETE','/api/memory/items/'+item['id'],json={'version':1}).status_code==200
    elif mutation=='conflict':memory(c,content='另一个互斥值',semantic_key='同类键')
    elif mutation=='project':assert c.put('/api/memory/projects/'+p['id'],json={'version':1,'name':'新项目名称'}).status_code==200
    else:monkeypatch.setattr('app.memory_policy.time.time',lambda:now+51)
    with db.connect() as conn:
        with pytest.raises(AIError,match='生成期间'):assert_current(conn,owner,chat['id'],snapshot)
    assert item['content'] not in json.dumps(snapshot,ensure_ascii=False)


def test_irrelevant_disabled_memory_and_other_owners_do_not_invalidate_context(env):
    c=account(env);other=account(env,'other');chat=conversation(c);owner=uid(c);db=env[0].state.db
    with db.connect() as conn:snapshot=capture(conn,owner,chat['id'],{**ACCESS,'memory':True})
    memory(other,content='别人的记忆');memory(c,content='停用记忆',active=False)
    with db.connect() as conn:assert_current(conn,owner,chat['id'],snapshot)


def test_change_during_verification_publishes_no_answer_and_retains_retry(env,monkeypatch):
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic'
    c=account(env);chat=conversation(c);item=memory(c)
    async def verify(*args):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE personal_memories SET active=0,version=version+1 WHERE id=?',(item['id'],))
        return [],{},['synthetic review']
    monkeypatch.setattr(grounding,'verify',verify)
    packets=events(c.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat)))
    assert not any(p['type']=='delta' for p in packets)
    final=packets[-1]['data']['conversation'];message=final['messages'][-1]
    assert not final['processing'] and message['status']=='failed' and '生成期间' in message['error']
    assert message['grounding']['harness']['stop_reason']=='context_changed'


def test_final_transaction_revalidates_even_after_the_verifier_returns(env,monkeypatch):
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic'
    c=account(env);chat=conversation(c);item=memory(c)
    original=grounding.events
    async def changed_after_complete(*args):
        async for event in original(*args):
            yield event
            if event['type']=='complete':
                with env[0].state.db.connect(write=True) as conn:
                    conn.execute('UPDATE personal_memories SET active=0,version=version+1 WHERE id=?',(item['id'],))
    monkeypatch.setattr(grounding,'events',changed_after_complete)
    packets=events(c.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat)))
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='failed' and message['content']=='' and not message['genui']['validated']
    assert message['grounding']['status']=='not_published'


def test_profile_changed_before_initial_snapshot_is_not_used(env,monkeypatch):
    from app import context_snapshot
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic'
    c=account(env);chat=conversation(c)
    original=context_snapshot.capture
    def change_before_snapshot(conn,owner,cid,access):
        conn.execute('UPDATE users SET profile=? WHERE id=?',(json.dumps({'college':'新学院'}),owner))
        return original(conn,owner,cid,access)
    monkeypatch.setattr(context_snapshot,'capture',change_before_snapshot)
    async def forbidden(*args):raise AssertionError('Stale profile must be rejected before a model call')
    monkeypatch.setattr(grounding,'plan',forbidden)
    packets=events(c.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat)))
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='failed' and '生成期间' in message['error']
    assert message['grounding']['harness']['call_count']==0
