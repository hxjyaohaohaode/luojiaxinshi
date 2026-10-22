import asyncio
import json
import sqlite3
import time

import pytest

from app import grounding,work_summary,chat_ai
from app.backups import restore_database
from app.context_engine import pack_history
from app.db import Database,ident
from app.harness import CURRENT,Trace,start_call,finish_call
from app.memory import recall,memory_access
from test_workflow import env,account
from test_workspace import conversation


ACCESS=dict.fromkeys(('library','schedule','profile','attachments'),True)


def project(c,name='试验项目'):
    r=c.post('/api/memory/projects',json={'name':name,'description':'合成工程测试'});assert r.status_code==200,r.text
    return r.json()


def memory(c,**values):
    r=c.post('/api/memory/items',json={'content':'回答先给下一步','kind':'preference',**values});assert r.status_code==200,r.text
    return r.json()


def context(c,chat,**values):
    current=c.get(f"/api/conversations/{chat['id']}/context").json()
    r=c.put(f"/api/conversations/{chat['id']}/context",json={**current,**values});assert r.status_code==200,r.text
    return r.json()


def uid(c):return c.get('/api/session').json()['user']['id']


def test_memory_is_owner_scoped_and_project_topic_selection_is_explicit(env):
    c=account(env);other=account(env,'other');chat=conversation(c);p=project(c);q=project(c,'第二项目')
    shared=memory(c);scoped=memory(c,scope='project',project_id=p['id'],content='此项目先核对成本')
    memory(c,scope='project',project_id=q['id'],content='不应进入第一项目')
    topic=memory(c,scope='topic',topic='论文',content='引用原始论文')
    memory(other,content='绝不跨账号')
    context(c,chat,project_id=p['id'],topics=['论文'])
    rows,meta=recall(env[0].state.db,uid(c),chat['id'],'帮助我',ACCESS)
    assert {r['id'] for r in rows if not r.get('project_context')}=={shared['id'],scoped['id'],topic['id']} and meta['selected']==3
    assert any(r.get('project_context') and p['name'] in r['content'] for r in rows)
    context(c,chat,project_id=q['id'],topics=[])
    rows,_=recall(env[0].state.db,uid(c),chat['id'],'帮助我',ACCESS)
    assert scoped['id'] not in {r['id'] for r in rows} and topic['id'] not in {r['id'] for r in rows}
    assert other.put(f"/api/conversations/{chat['id']}/context",json={'version':0}).status_code==404
    assert other.post('/api/memory/items',json={'scope':'project','project_id':p['id'],'content':'越权'}).status_code==404


def test_disabling_memory_and_private_profile_scope_revoke_recall(env):
    c=account(env);chat=conversation(c);memory(c)
    for access,question in [({**ACCESS,'profile':False},'正常问题'),(ACCESS,'不要使用记忆，回答当前问题')]:
        assert recall(env[0].state.db,uid(c),chat['id'],question,access)[0]==[]
    context(c,chat,memory_enabled=False)
    assert recall(env[0].state.db,uid(c),chat['id'],'正常问题',ACCESS)[0]==[]


def test_memory_restriction_persists_until_user_explicitly_allows_it():
    history=[{'role':'user','content':'不要使用记忆。'},{'role':'assistant','content':'允许使用记忆'},{'role':'user','content':'继续回答。'}]
    assert not memory_access(history)
    assert memory_access(history+[{'role':'user','content':'现在允许使用记忆。'}])


@pytest.mark.parametrize('cited',[True,False])
def test_current_memory_keeps_followup_context_but_edit_removes_stale_assertion(env,monkeypatch,cited):
    c=account(env);chat=conversation(c);item=memory(c);db=env[0].state.db;parent=ident();mid=ident()
    cite={'source_id':'memory-'+item['id'],'locator':'记忆','quote':item['content']}
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user','按我的偏好回答','complete',?)",(parent,chat['id'],int(time.time())))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,citations,created_at) VALUES(?,?,'assistant','可追问的旧答复','complete',?,?,?)",(mid,chat['id'],parent,json.dumps([cite] if cited else []),int(time.time())))
        conn.execute('INSERT INTO reply_grounding(message_id,sources,report) VALUES(?,?,?)',(mid,json.dumps([{'id':cite['source_id'],'evidence_kind':'memory','memory_version':1}]),'{}'))
    seen=[];env[1].ai_api_key='synthetic'
    def reply(settings,sources,messages,profile):
        seen.append(messages)
        return {'answer':'合成回复','citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',reply)
    import uuid
    def send():
        current=c.get('/api/conversations/'+chat['id']).json()
        return c.post(f"/api/conversations/{chat['id']}/messages",json={'version':current['version'],'content':'把上面的内容说清楚','request_id':uuid.uuid4().hex,'allow_external_processing':True})
    assert send().status_code==200 and any(m['content']=='可追问的旧答复' for m in seen[-1])
    assert c.put('/api/memory/items/'+item['id'],json={'version':1,'content':'现在先给依据'}).status_code==200
    assert send().status_code==200 and not any(m['content']=='可追问的旧答复' for m in seen[-1])


def test_memory_edit_stale_write_disable_delete_and_source_lifecycle(env):
    c=account(env);chat=conversation(c);item=memory(c,source_conversation_id=chat['id'])
    body={k:item[k] for k in ['scope','project_id','topic','kind','content','source_conversation_id','version']}
    assert c.put('/api/memory/items/'+item['id'],json={**body,'content':'改为先给结论','active':False}).status_code==200
    assert c.put('/api/memory/items/'+item['id'],json=body).status_code==409
    assert recall(env[0].state.db,uid(c),chat['id'],'回答',ACCESS)[0]==[]
    assert c.request('DELETE','/api/memory/items/'+item['id'],json={'version':1}).status_code==409
    assert c.request('DELETE','/api/conversations/'+chat['id'],json={'version':chat['version']}).status_code==200
    assert c.get('/api/memory').json()['memories']==[]


def test_project_delete_preserves_chat_global_memory_and_invalidates_context_version(env):
    c=account(env);chat=conversation(c);p=project(c);shared=memory(c);memory(c,scope='project',project_id=p['id'])
    saved=context(c,chat,project_id=p['id'])
    assert c.request('DELETE','/api/memory/projects/'+p['id'],json={'version':p['version']}).status_code==200
    new=c.get(f"/api/conversations/{chat['id']}/context").json()
    assert new['project_id'] is None and new['version']==saved['version']+1
    assert {m['id'] for m in c.get('/api/memory').json()['memories']}=={shared['id']}
    assert c.get('/api/conversations/'+chat['id']).status_code==200


@pytest.mark.parametrize('body',[{'scope':'project'},{'scope':'global','topic':'杂项'},{'content':'sk-SYNTHETIC_TEST_SECRET_1234567890'},{'scope':'topic','topic':' '}])
def test_invalid_scope_or_credential_is_rejected_without_persisting(env,body):
    c=account(env)
    assert c.post('/api/memory/items',json={'content':'普通偏好',**body}).status_code==422
    assert c.get('/api/memory').json()['memories']==[]


def test_context_cannot_cross_owner_or_change_during_generation(env):
    c=account(env);other=account(env,'other');chat=conversation(c);p=project(other)
    assert c.put(f"/api/conversations/{chat['id']}/context",json={'version':0,'project_id':p['id']}).status_code==404
    with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE conversations SET processing_token=? WHERE id=?',('synthetic-live',chat['id']))
    assert c.put(f"/api/conversations/{chat['id']}/context",json={'version':0}).status_code==409


def test_export_import_keeps_scopes_and_activation_without_review_inbox(env):
    c=account(env);dest=account(env,'dest');chat=conversation(c);p=project(c);context(c,chat,project_id=p['id'],topics=['论文'])
    memory(c,scope='project',project_id=p['id'],source_conversation_id=chat['id']);memory(c,scope='topic',topic='论文')
    exported=c.get('/api/export').json()
    preview=dest.post('/api/import',json={'data':exported}).json()
    r=dest.post('/api/import',json={'data':exported,'digest':preview['digest'],'confirm':True});assert r.status_code==200,r.text
    imported=dest.get('/api/memory').json()
    assert len(imported['projects'])==1 and len(imported['memories'])==2
    assert all(m['active'] for m in imported['memories'])
    assert all(m['source_conversation_id'] is None for m in imported['memories'])
    assert next(m for m in imported['memories'] if m['scope']=='project')['project_id']==imported['projects'][0]['id']
    again=dest.post('/api/import',json={'data':exported,'digest':preview['digest'],'confirm':True}).json()
    assert again['added']==0 and len(dest.get('/api/memory').json()['memories'])==2


def import_export(client,data):
    preview=client.post('/api/import',json={'data':data});assert preview.status_code==200,preview.text
    return client.post('/api/import',json={'data':data,'digest':preview.json()['digest'],'confirm':True})


def test_updated_export_does_not_overwrite_or_duplicate_existing_project(env):
    c=account(env);dest=account(env,'dest');p=project(c,'原项目名称');memory(c,scope='project',project_id=p['id'])
    assert import_export(dest,c.get('/api/export').json()).status_code==200
    assert c.put('/api/memory/projects/'+p['id'],json={'version':p['version'],'name':'后来修改的名称'}).status_code==200
    r=import_export(dest,c.get('/api/export').json());assert r.status_code==200,r.text
    imported=dest.get('/api/memory').json()
    assert len(imported['projects'])==1 and imported['projects'][0]['name']=='原项目名称'
    assert len(imported['memories'])==1


def test_missing_memory_project_rolls_back_entire_import(env):
    c=account(env);dest=account(env,'dest');p=project(c);memory(c);memory(c,scope='project',project_id=p['id'])
    data=c.get('/api/export').json();data['memory_projects']=[]
    assert import_export(dest,data).status_code==422
    result=dest.get('/api/memory').json()
    assert result['projects']==[] and result['memories']==[] and result['total']==0
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM import_receipts WHERE user_id=?',(uid(dest),)).fetchone()[0]==0


@pytest.mark.parametrize('kind,limit',[('project',100),('memory',10000)])
def test_import_respects_existing_account_memory_capacity(env,kind,limit):
    c=account(env);dest=account(env,'dest');project(c);memory(c);owner=uid(dest);now=int(time.time())
    with env[0].state.db.connect(write=True) as conn:
        for i in range(limit):
            if kind=='project':conn.execute('INSERT INTO memory_projects VALUES(?,?,?,?,1,?,?)',(ident(),owner,'已有项目 '+str(i),'',now,now))
            else:conn.execute("INSERT INTO personal_memories VALUES(?,?,'global',NULL,'','preference','已有记忆',NULL,1,0,1,?,?)",(ident(),owner,now,now))
    r=import_export(dest,c.get('/api/export').json());assert r.status_code==422,r.text
    catalog=dest.get('/api/memory').json()
    assert len(catalog['projects'])==(limit if kind=='project' else 0)
    assert catalog['total']==(limit if kind=='memory' else 0)
    assert len(catalog['memories'])==min(catalog['total'],200)


def test_branch_preserves_project_topics_and_disabled_memory_independently(env):
    c=account(env);chat=conversation(c);p=project(c);context(c,chat,project_id=p['id'],topics=['论文'],memory_enabled=False)
    mid=ident();parent=ident()
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user','原对话问题','complete',?)",(parent,chat['id'],int(time.time())))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant','原对话回答','complete',?,?)",(mid,chat['id'],parent,int(time.time())))
    current=c.get('/api/conversations/'+chat['id']).json()
    r=c.post(f"/api/conversations/{chat['id']}/messages/{mid}/branch",json={'version':current['version']});assert r.status_code==200,r.text
    branch=r.json();assert branch['context']=={'project_id':p['id'],'topics':['论文'],'memory_enabled':False,'version':1,'selection_mode':'manual'}
    context(c,branch,project_id=None,topics=[],memory_enabled=True)
    original=c.get('/api/conversations/'+chat['id']).json()['context']
    assert original['project_id']==p['id'] and not original['memory_enabled'] and original['topics']==['论文']


def test_memory_backup_restore_and_future_version_rejection(env,tmp_path):
    c=account(env);p=project(c);memory(c,scope='project',project_id=p['id'])
    backup=tmp_path/'backup.sqlite3';env[0].state.db.backup(backup)
    restored=tmp_path/'restored.sqlite3';restore_database(backup,restored)
    db=Database(restored)
    with db.connect() as conn:assert conn.execute('SELECT count(*) FROM personal_memories').fetchone()[0]==1
    with sqlite3.connect(backup) as conn:conn.execute("UPDATE meta SET value='999' WHERE key='memory_schema_version'")
    with pytest.raises(ValueError,match='记忆'):restore_database(backup,tmp_path/'denied.sqlite3')
    with pytest.raises(RuntimeError,match='记忆'):Database(backup)


def test_compression_retrieves_early_constraint_and_keeps_latest_whole():
    original=[{'id':'early','role':'user','content':'必须保留申请期限未知，不要补造日期。'}]
    original += [{'id':str(i),'role':'assistant','content':'旧助手推测并不是事实。'*500} for i in range(30)]
    latest={'id':'new','role':'user','content':'现在请根据我的约束核对申请期限。'};original.append(latest)
    packed,excerpts,report=pack_history(original,budget=6000)
    assert report['compressed'] and report['packed_bytes']<=6000
    assert packed[-1]==latest and any(e['message_id']=='early' and e['text']==original[0]['content'] for e in excerpts)
    assert all('旧助手' not in e['text'] for e in excerpts)
    assert len(original)==32 and original[1]['content'].endswith('旧助手推测并不是事实。')


def test_context_keeps_current_selection_once_and_does_not_truncate_newest():
    messages=[{'role':'user','content':'仅使用当前消息。'}]
    packed,excerpts,report=pack_history(messages)
    assert packed==messages and not report['compressed'] and excerpts==[]
    from app.ai import AIError
    with pytest.raises(AIError,match='本条消息'):
        pack_history([{'role':'user','content':'很长'*1000}],budget=1000)


def test_compaction_keeps_turn_pairs_and_deduplicates_exact_constraints():
    history=[]
    for i in range(12):
        history.extend([{'id':f'u{i}','role':'user','content':'必须核对办理期限。'},
                        {'id':f'a{i}','role':'assistant','content':'很长的历史说明。'*100}])
    latest={'id':'current','role':'user','content':'继续核对办理期限'};history.append(latest)
    packed,excerpts,meta=pack_history(history,budget=5000)
    ids={m.get('id') for m in packed}
    assert all('u'+m['id'][1:] in ids for m in packed if m['role']=='assistant')
    assert len(excerpts)==1 and excerpts[0]['text']=='必须核对办理期限。'
    assert packed[-1]==latest and meta['packed_bytes']<=5000


def test_historical_relative_dates_keep_their_original_time_anchor():
    history=[{'id':'old','role':'user','content':'明天交申请表。','created_at':1792195200},
             {'role':'assistant','content':'历史说明。'*1000},
             {'id':'next','role':'user','content':'明天交申请表。','created_at':1792281600},
             {'role':'assistant','content':'历史说明。'*1000},
             {'id':'current','role':'user','content':'我之前说过哪天提交？'}]
    packed,excerpts,meta=pack_history(history,budget=3000)
    assert len(excerpts)==2 and len({e['locator'] for e in excerpts})==2
    assert all('+08:00' in e['locator'] for e in excerpts)
    assert meta['temporal_anchors']==2 and packed[-1]==history[-1]
    short,_,_=pack_history([history[0],history[-1]])
    assert '相对日期以当时为准' in short[0]['content']
    assert history[0]['content']=='明天交申请表。'


def test_harness_counts_calls_and_usage_without_private_text():
    trace=Trace();token=CURRENT.set(trace)
    try:
        trace.phase('writing');call=start_call({'model':'test','messages':[{'content':'private memory'}]})
        finish_call(call,{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':80}})
        snap=trace.snapshot()
        assert snap['call_count']==1 and snap['cached_input_tokens']==80
        assert 'private memory' not in json.dumps(snap) and '_start' not in json.dumps(snap)
        assert trace.progress(['wrong date'],'same draft')
        assert not trace.progress(['wrong date'],'same draft')
        assert trace.snapshot()['stop_reason']=='no_progress'
        assert trace.progress(['wrong date'],'changed draft')
    finally:CURRENT.reset(token)


@pytest.mark.parametrize('mode,expected',[('local','local-test-key'),('production','inherited-test-key')])
def test_local_file_credential_precedes_stale_parent_but_production_does_not(env,tmp_path,monkeypatch,mode,expected):
    import os
    from app.config import load_environment
    path=tmp_path/'isolated.env';path.write_text('MIMO_API_KEY=local-test-key\nDATA_DIR=wrong-dir\n',encoding='utf-8')
    monkeypatch.setenv('APP_ENV',mode);monkeypatch.setenv('MIMO_API_KEY','inherited-test-key');monkeypatch.setenv('DATA_DIR','keep-dir')
    load_environment(path)
    assert os.environ['MIMO_API_KEY']==expected and os.environ['DATA_DIR']=='keep-dir'


def test_stage_status_never_needs_optional_model_by_default(env,monkeypatch):
    c=account(env);chat=conversation(c);db=env[0].state.db;mid=ident()
    with db.connect(write=True) as conn:conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'assistant','','processing',?)",(mid,chat['id'],int(time.time())))
    async def forbidden(*args):raise AssertionError('stage label must not spend a model call')
    monkeypatch.setattr(work_summary,'summarize',forbidden)
    async def source():
        yield {'type':'phase','phase':'planning','label':'确认范围'}
        await asyncio.sleep(.01)
        yield {'type':'complete','result':{}}
    async def run():return [e async for e in work_summary.stream(env[1],db,mid,source())]
    assert asyncio.run(run())[-1]['type']=='complete'
    with db.connect() as conn:report=json.loads(conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(mid,)).fetchone()[0])
    assert report['summary_model'] is None and report['summary_usage']=={'input_tokens':0,'output_tokens':0}
