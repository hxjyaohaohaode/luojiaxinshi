"""Automatic selection, user-directed changes and non-chat event learning.

Model edits use deterministic fixtures. No external model or accuracy score.
"""
import asyncio
import json
import time
from dataclasses import replace
import pytest
from app.db import dumps,ident
from app.memory import recall
from app.memory_learning import drain_jobs
from app.memory_resources import ingest_resource
from test_workflow import env,account,notice
from test_workspace import conversation
from test_memory_context import project,memory,context,uid,ACCESS
from test_memory_engine import message,items,actions,setting


def test_auto_selects_named_projects_and_ignores_foreign_catalog_ids(env):
    c=account(env);other=account(env,'other');chat=conversation(c)
    p=project(c,'论文');q=project(c,'竞赛');foreign=project(other,'他人项目')
    a=memory(c,scope='project',project_id=p['id'],content='论文采用作者年份格式。')
    b=memory(c,scope='project',project_id=q['id'],content='竞赛需要演示视频。')
    assert c.get(f"/api/conversations/{chat['id']}/context").json()['selection_mode']=='auto'
    got,_=recall(env[0].state.db,uid(c),chat['id'],'论文采用什么格式',ACCESS)
    assert a['id'] in {m['id'] for m in got} and b['id'] not in {m['id'] for m in got}
    got,_=recall(env[0].state.db,uid(c),chat['id'],'怎么准备演示视频',{**ACCESS,'_memory_selection':{'project_ids':[q['id'],foreign['id']]}})
    assert b['id'] in {m['id'] for m in got} and a['id'] not in {m['id'] for m in got}
    context(c,chat,project_id=p['id'])
    got,_=recall(env[0].state.db,uid(c),chat['id'],'竞赛演示视频',{**ACCESS,'_memory_selection':{'project_ids':[q['id']]}})
    assert b['id'] not in {m['id'] for m in got}


def test_explicit_correction_can_update_locked_memory_without_another_confirmation(env):
    c=account(env);chat=conversation(c);old=memory(c,content='我的名字是小林。',semantic_key='个人称呼',kind='fact')
    quote='更正，我的名字改为小陈。';mid=message(env,c,chat,quote,learn=False)
    result=actions(env,c,chat,mid,{'operation':'update','target_id':old['id'],'expected_version':1,
        'content':'我的名字是小陈。','kind':'fact','basis':'explicit','source_quote':quote})[0]
    assert result['status']=='updated'
    current=c.get('/api/memory/items/'+old['id']).json()
    assert current['content']=='我的名字是小陈。' and current['locked'] and current['version']==2
    assert len(current['revisions'])==2 and len(items(c))==1


@pytest.mark.parametrize('basis,status',[('explicit','accepted'),('inferred','pending')])
def test_faithful_paraphrase_can_be_saved_automatically_but_inference_stays_pending(env,basis,status):
    c=account(env);chat=conversation(c);quote='我以后一直希望你先给结论，再解释理由。';mid=message(env,c,chat,quote,learn=False)
    result=actions(env,c,chat,mid,{'content':'回答先给结论，再解释理由。','kind':'preference','basis':basis,'source_quote':quote,'lifetime':'long_term'})[0]
    assert result['status']==status


def test_temporary_update_never_overwrites_long_term_preference(env):
    c=account(env);chat=conversation(c);old=memory(c,content='我喜欢详细回答。',kind='preference',semantic_key='回答篇幅')
    quote='这次请把我的回答要求改成简短回答。';mid=message(env,c,chat,quote,learn=False)
    result=actions(env,c,chat,mid,{'operation':'update','target_id':old['id'],'expected_version':1,
        'content':quote,'kind':'preference','basis':'explicit','source_quote':quote,'lifetime':'long_term'})[0]
    assert result['status']=='session_saved'
    assert c.get('/api/memory/items/'+old['id']).json()['content']==old['content']
    other=conversation(c)
    got,_=recall(env[0].state.db,uid(c),other['id'],'回答',ACCESS)
    assert old['id'] in {m['id'] for m in got}


def test_agent_partial_edit_preserves_unrelated_text(env):
    c=account(env);chat=conversation(c);body='我的名字是小林。我的专业是物理。'
    old=memory(c,content=body,kind='fact',locked=False)
    quote='请把我的名字改成小陈。';mid=message(env,c,chat,quote,learn=False)
    start=body.index('小林');end=start+2
    result=actions(env,c,chat,mid,{'operation':'update','target_id':old['id'],'expected_version':1,'content':'小陈',
        'kind':'fact','basis':'explicit','source_quote':quote,'edit_start':start,'edit_end':end})[0]
    assert result['status']=='updated',result
    assert c.get('/api/memory/items/'+old['id']).json()['content']=='我的名字是小陈。我的专业是物理。'


def resource_rows(c):return [m for m in items(c) if m['origin']=='resource']


def test_notice_forms_memory_without_chat_updates_and_forgetting_blocks_relearning(env):
    c=account(env);n=notice(c,text='申请地点是行政楼 201。');db=env[0].state.db
    drain_jobs(db,uid=uid(c));old=next(m for m in resource_rows(c) if '201' in m['content'])
    sid=n['sources'][0]['id']
    with db.connect(write=True) as conn:
        conn.execute('UPDATE sources SET sections=? WHERE id=?',(dumps([{'locator':'第1段','text':'申请地点是行政楼 301。'}]),sid))
    assert c.get('/api/memory/items/'+old['id']).json()['state']=='source_changed'
    drain_jobs(db,uid=uid(c));current=c.get('/api/memory/items/'+old['id']).json()
    assert '301' in current['content'] and '201' not in current['content'] and current['version']==2
    assert current['evidence'][0]['source_kind']=='resource_notice' and current['evidence'][0]['source_status']=='available'
    assert c.request('DELETE','/api/memory/items/'+old['id'],json={'version':2}).status_code==200
    with db.connect(write=True) as conn:
        conn.execute('UPDATE sources SET sections=? WHERE id=?',(dumps([{'text':'申请地点是行政楼 401。'}]),sid))
    drain_jobs(db,uid=uid(c));assert resource_rows(c)==[]


def test_project_description_forms_source_bound_memory_without_messages(env):
    c=account(env);p=project(c,'校园实践');db=env[0].state.db;drain_jobs(db,uid=uid(c))
    old=resource_rows(c)[0];assert old['scope']=='project' and old['project_id']==p['id']
    r=c.put('/api/memory/projects/'+p['id'],json={'version':p['version'],'name':p['name'],'description':'目标是完成实践演示。'})
    assert r.status_code==200
    assert c.get('/api/memory/items/'+old['id']).json()['state']=='source_changed'
    drain_jobs(db,uid=uid(c));assert '实践演示' in c.get('/api/memory/items/'+old['id']).json()['content']


def test_resource_permissions_propagate_to_derived_memories(env):
    from app.memory_store import insert_memory
    c=account(env);n=notice(c);chat=conversation(c);db=env[0].state.db;drain_jobs(db,uid=uid(c))
    old=resource_rows(c)[0]
    with db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'申请资料的整理经验。'},origin='organizer',locked=False,parents=[old])
    got,report=recall(db,uid(c),chat['id'],'申请资料',{**ACCESS,'library':False,'attachments':False})
    assert old['id'] not in {m['id'] for m in got} and child not in {m['id'] for m in got}
    with db.connect(write=True) as conn:conn.execute('DELETE FROM sources WHERE id=?',(n['sources'][0]['id'],))
    assert c.get('/api/memory/items/'+old['id']).status_code==404
    assert c.get('/api/memory/items/'+child).status_code==404


@pytest.mark.parametrize('mode',['manual','off','review'])
def test_resource_learning_obeys_settings_and_resumes_automatically(env,mode):
    c=account(env);setting(c,mode);notice(c);db=env[0].state.db;drain_jobs(db,uid=uid(c))
    if mode=='review':assert resource_rows(c)[0]['review_status']=='pending'
    else:
        assert resource_rows(c)==[];setting(c,'auto');drain_jobs(db,uid=uid(c));assert resource_rows(c)[0]['active']


def test_upload_fulltext_update_invalidates_before_worker_and_is_account_scoped(env):
    c=account(env);other=account(env,'other');chat=conversation(c);db=env[0].state.db;sid=ident()
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,chat['id'],'我的材料.txt','text','','synthetic','ok',dumps([{'text':'材料原文。'}]),'',int(time.time())))
        conn.execute('INSERT INTO material_library VALUES(?,?,?,?)',(sid,'测试',dumps([{'text':'完整材料内容。'}]),8))
    drain_jobs(db,uid=uid(c));old=resource_rows(c)[0];assert '完整材料内容' in old['content']
    assert resource_rows(other)==[]
    got,_=recall(db,uid(c),chat['id'],'完整材料',{**ACCESS,'library':False})
    assert old['id'] in {m['id'] for m in got}
    another=conversation(c)
    got,_=recall(db,uid(c),another['id'],'完整材料',{**ACCESS,'library':False})
    assert old['id'] not in {m['id'] for m in got}
    with db.connect(write=True) as conn:conn.execute('UPDATE material_library SET full_sections=? WHERE source_id=?',(dumps([{'text':'最新材料内容。'}]),sid))
    assert c.get('/api/memory/items/'+old['id']).json()['state']=='source_changed'
    drain_jobs(db,uid=uid(c));assert '最新材料内容' in c.get('/api/memory/items/'+old['id']).json()['content']


def enable_assist(env,monkeypatch,replacement='小陈'):
    from app import memory_assist
    env[0].state.settings=replace(env[0].state.settings,ai_api_key='synthetic-fixture-only')
    calls=[]
    async def propose(settings,selection,instruction):calls.append((selection,instruction));return replacement
    monkeypatch.setattr(memory_assist,'propose',propose)
    return calls


def edit(c,item,**extra):
    payload={'version':item['version'],'instruction':'将称呼改为小陈','start':0,'end':len(item['content']),'allow_external_processing':True,**extra}
    return c.post('/api/memory/items/'+item['id']+'/assist',json=payload,headers={'Idempotency-Key':'fixture-edit-1234'})


def test_assist_unicode_partial_single_flight_replay_and_version_history(env,monkeypatch):
    c=account(env);old=memory(c,content='😀我的名字是小林。其他内容保持原样。',kind='fact');calls=enable_assist(env,monkeypatch)
    start=old['content'].index('小林');r=edit(c,old,start=start,end=start+2)
    assert r.status_code==200,r.text
    assert r.json()['content']=='😀我的名字是小陈。其他内容保持原样。'
    again=edit(c,old,start=start,end=start+2)
    assert again.status_code==200 and again.json()['replayed'] and calls==[('小林','将称呼改为小陈')]
    assert edit(c,old,start=0,end=1).status_code==409 and len(calls)==1
    assert len(c.get('/api/memory/items/'+old['id']).json()['revisions'])==2


@pytest.mark.parametrize('extra,status',[
    ({'allow_external_processing':False},422),({'version':99},409),({'start':2000,'end':2000},422),
    ({'instruction':'   '},422),({'instruction':'密码：must-not-send'},422)])
def test_assist_invalid_requests_never_call_provider(env,monkeypatch,extra,status):
    c=account(env);old=memory(c);calls=enable_assist(env,monkeypatch)
    assert edit(c,old,**extra).status_code==status and not calls


def test_assist_does_not_overwrite_concurrent_changes_or_rebill_failed_intent(env,monkeypatch):
    from app import memory_assist
    c=account(env);old=memory(c);calls=enable_assist(env,monkeypatch)
    async def concurrent(settings,selection,instruction):
        calls.append(selection)
        with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE personal_memories SET content=?,version=version+1 WHERE id=?',('人工更新的内容',old['id']))
        return '过时结果'
    monkeypatch.setattr(memory_assist,'propose',concurrent)
    assert edit(c,old).status_code==409
    assert c.get('/api/memory/items/'+old['id']).json()['content']=='人工更新的内容'
    assert edit(c,old).status_code==502 and len(calls)==1


def test_assist_provider_failure_is_durable_and_empty_whole_edit_cannot_erase_memory(env,monkeypatch):
    from app import memory_assist
    c=account(env);old=memory(c);calls=enable_assist(env,monkeypatch)
    async def fail(*args):calls.append('failed');raise TimeoutError()
    monkeypatch.setattr(memory_assist,'propose',fail)
    assert edit(c,old).status_code==502 and edit(c,old).status_code==502 and len(calls)==1
    another=memory(c,content='独立的测试记忆');enable_assist(env,monkeypatch,'')
    r=c.post('/api/memory/items/'+another['id']+'/assist',json={'version':1,'instruction':'删除全部内容','start':0,'end':len(another['content']),'allow_external_processing':True},headers={'Idempotency-Key':'fixture-empty-1234'})
    assert r.status_code==502
    assert c.get('/api/memory/items/'+another['id']).json()['content']==another['content']


def test_workflow_outcome_is_learned_without_a_chat_and_old_version_stops_immediately(env):
    from test_workflow import confirm,manual
    c=account(env);tid=confirm(c,manual(c,notice(c)));db=env[0].state.db;drain_jobs(db,uid=uid(c))
    old=next(m for m in items(c) if m['origin']=='task')
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO task_workflows VALUES(?,?,1,?)',(tid,dumps({'stage':'blocked','outcome':'缺少本人签字','next_step':'补齐签字后提交'}),int(time.time())))
    assert c.get('/api/memory/items/'+old['id']).json()['state']=='source_changed'
    drain_jobs(db,uid=uid(c));current=c.get('/api/memory/items/'+old['id']).json()
    assert '缺少本人签字' in current['content'] and '补齐签字后提交' in current['content'] and current['state']=='active'
    with db.connect(write=True) as conn:conn.execute('UPDATE task_workflows SET data=?,version=version+1 WHERE task_id=?',(dumps({'stage':'preparing','outcome':'签字已补齐','next_step':'本人提交'}),tid))
    assert c.get('/api/memory/items/'+old['id']).json()['state']=='source_changed'
    drain_jobs(db,uid=uid(c));assert '签字已补齐' in c.get('/api/memory/items/'+old['id']).json()['content']


def test_same_turn_normalization_does_not_duplicate_the_original_memory(env):
    c=account(env);chat=conversation(c);quote='我喜欢简短回答。';mid=message(env,c,chat,quote)
    original=items(c)[0]
    result=actions(env,c,chat,mid,{'kind':'preference','content':'回答保持简短。','source_quote':quote,'basis':'explicit','lifetime':'long_term'})[0]
    assert result['status']=='accepted' and result['id']==original['id'] and len(items(c))==1


@pytest.mark.parametrize('content',['我的名字是小王。','我喜欢每次回答不少于 3000 字。'])
def test_explicit_flag_alone_cannot_approve_changed_identity_or_new_numbers(env,content):
    c=account(env);chat=conversation(c);quote='我的名字是小林。';mid=message(env,c,chat,quote,learn=False)
    result=actions(env,c,chat,mid,{'kind':'fact','content':content,'source_quote':quote,'basis':'explicit','lifetime':'long_term'})[0]
    assert result['status']=='pending'


def test_local_correction_cannot_erase_other_sentences_and_partial_agent_edit_finishes_it(env):
    c=account(env);chat=conversation(c);old=memory(c,content='我的名字是小林。我的专业是物理。',semantic_key='个人称呼',kind='fact')
    quote='记住，我的名字改为小陈。';mid=message(env,c,chat,quote)
    assert c.get('/api/memory/items/'+old['id']).json()['content']==old['content']
    start=old['content'].index('小林')
    result=actions(env,c,chat,mid,{'operation':'update','target_id':old['id'],'expected_version':1,
        'kind':'fact','content':'小陈','source_quote':quote,'basis':'explicit','edit_start':start,'edit_end':start+2})[0]
    assert result['status']=='updated' and len(items(c))==1
    assert c.get('/api/memory/items/'+old['id']).json()['content']=='我的名字是小陈。我的专业是物理。'


def test_human_resource_edit_survives_until_explicit_source_sync_and_keeps_history(env,monkeypatch):
    c=account(env);n=notice(c);db=env[0].state.db;drain_jobs(db,uid=uid(c));old=resource_rows(c)[0]
    enable_assist(env,monkeypatch,'本人修订的资料索引。')
    edited=edit(c,old);assert edited.status_code==200 and edited.json()['locked']
    with db.connect(write=True) as conn:conn.execute('UPDATE sources SET sections=? WHERE id=?',(dumps([{'text':'更新后的资料原文。'}]),n['sources'][0]['id']))
    drain_jobs(db,uid=uid(c));current=c.get('/api/memory/items/'+old['id']).json()
    assert current['content']=='本人修订的资料索引。' and current['state']=='source_changed'
    synced=c.post('/api/memory/items/'+old['id']+'/source-sync',json={'version':current['version']})
    assert synced.status_code==200 and '更新后的资料原文' in synced.json()['content'] and not synced.json()['locked']
    assert any(revision['snapshot']['content']=='本人修订的资料索引。' for revision in c.get('/api/memory/items/'+old['id']).json()['revisions'])
    assert c.post('/api/memory/items/'+old['id']+'/source-sync',json={'version':current['version']}).status_code==409


def test_forget_all_also_blocks_old_queued_resources_but_allows_new_sources(env):
    c=account(env);chat=conversation(c);notice(c);project(c)
    message(env,c,chat,'忘记我的全部记忆。')
    drain_jobs(env[0].state.db,uid=uid(c));assert items(c)==[]
    notice(c,text='这是遗忘之后新上传的课程资料。')
    drain_jobs(env[0].state.db,uid=uid(c));assert len(resource_rows(c))==1


def test_planner_selection_takes_precedence_over_a_project_merely_mentioned_in_question(env):
    from app.memory_reliability import candidates
    c=account(env);chat=conversation(c);p=project(c,'论文');q=project(c,'竞赛')
    a=memory(c,scope='project',project_id=p['id'],content='论文要求。');b=memory(c,scope='project',project_id=q['id'],content='竞赛要求。')
    with env[0].state.db.connect() as conn:
        selected,_=candidates(conn,uid(c),chat['id'],{**ACCESS,'_memory_selection':{'project_ids':[q['id']]}},scenario='论文的要求先不考虑，竞赛应该做什么')
    assert b['id'] in {row['id'] for row in selected} and a['id'] not in {row['id'] for row in selected}


@pytest.mark.parametrize('name,text,expected',[('AI','邮件 mail',False),('AI','请继续 AI 项目',True),('甲','甲方的通知',False),('甲','项目甲的通知',True)])
def test_short_names_do_not_match_inside_unrelated_words(name,text,expected):
    from app.memory_autonomy import mentions
    assert mentions(name,text)==expected


@pytest.mark.parametrize('response,valid',[
    ('{"replacement":"小陈"}',True),
    ('{"type":"object","properties":{"replacement":{"type":"string"}}}',False),
    ('{"replacement":123}',False),
    ('{"replacement":"小陈","note":"额外字段"}',False),
    ('```json\n{"replacement":"小陈"}\n```',False),
    ('小陈',False),
])
def test_provider_edit_protocol_accepts_only_the_instance_and_never_retries(env,monkeypatch,response,valid):
    from app import memory_assist,evidence_web
    from pydantic import ValidationError
    calls=[]
    async def completion(settings,payload,max_bytes):
        calls.append(payload)
        assert payload['response_format']=={'type':'json_object'}
        assert '唯一字段是 replacement' in payload['messages'][0]['content']
        assert json.loads(payload['messages'][1]['content'])=={'selection':'小林','instruction':'改成小陈'}
        return {'content':response},{}
    monkeypatch.setattr(evidence_web,'completion',completion)
    if valid:assert asyncio.run(memory_assist.propose(env[1],'小林','改成小陈'))=='小陈'
    else:
        with pytest.raises(ValidationError):asyncio.run(memory_assist.propose(env[1],'小林','改成小陈'))
    assert len(calls)==1
