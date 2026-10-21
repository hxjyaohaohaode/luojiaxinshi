"""Lifecycle scenarios use real SQLite/HTTP; no external-model quality is implied."""
import json
import time

import pytest

from app.db import Database,dumps,ident
from app.memory import recall
from app.memory_store import forget_memory,insert_memory
from app.memory_learning import apply_actions,ingest_message,update_working
from app.memory_lifecycle import (session_state,session_item,maintain,checkpoint,working_for,
    filter_history,feedback,remember_exposure,config)
from app.context_snapshot import capture,bind_memories,assert_current
from app.ai import AIError
from test_workflow import env,account
from test_workspace import conversation
from test_memory_context import memory,project,context,uid,ACCESS
from test_memory_engine import message,items,actions,setting


def short(client):return client.get('/api/memory/session-items').json()['items']


def test_goal_accumulates_and_new_question_does_not_replace_it(env):
    c=account(env);chat=conversation(c)
    message(env,c,chat,'请帮我准备交换生申请材料。')
    message(env,c,chat,'再帮我检查材料清单。')
    state=c.get('/api/conversations/'+chat['id']+'/memory-state').json()['state']
    assert '交换生' in state['goal'] and '检查' in state['current_request']
    assert items(c)==[]


def test_checkpoint_sections_merge_and_claims_need_user_support(env):
    c=account(env);chat=conversation(c)
    mid=message(env,c,chat,'我决定先核对原文。我已经阅读原文。')
    with env[0].state.db.connect(write=True) as conn:
        v=checkpoint(conn,uid(c),chat['id'],mid,{'decisions':['我决定先核对原文。']})
        checkpoint(conn,uid(c),chat['id'],mid,{'next_steps':['拟检查材料，尚未执行。']},v)
        state=session_state(conn,uid(c),chat['id'])
        assert state['decisions']==['我决定先核对原文。'] and state['next_steps']
        with pytest.raises(ValueError):checkpoint(conn,uid(c),chat['id'],mid,{},v)
    rejected=actions(env,c,chat,mid,{'operation':'checkpoint','source_quote':'我决定先核对原文。',
        'working_sections':{'completed_steps':['学校已经批准了申请。']}})
    assert rejected[0]['status']=='rejected'


def test_temporary_preference_is_not_long_term_or_cross_session(env):
    c=account(env);chat=conversation(c)
    mid=message(env,c,chat,'仅本次，我希望用英文回答。')
    assert not items(c)
    state=c.get('/api/conversations/'+chat['id']+'/memory-state').json()['state']
    assert any(e['lifetime']=='turn' for e in state['facts'])
    other=conversation(c)
    assert not c.get('/api/conversations/'+other['id']+'/memory-state').json()['state']['facts']
    message(env,c,chat,'请继续核对原文。')
    assert not c.get('/api/conversations/'+chat['id']+'/memory-state').json()['state']['facts']


def test_today_and_unsupported_project_stay_in_session(env):
    c=account(env);chat=conversation(c)
    message(env,c,chat,'我计划今天提交申请。')
    message(env,c,chat,'这个项目必须使用离线资料。')
    assert not items(c)
    assert any('离线资料' in e['content'] for e in short(c))


def test_selected_project_not_widened_by_usually_and_topic_is_scoped(env):
    c=account(env);chat=conversation(c);p=project(c)
    context(c,chat,project_id=p['id'])
    message(env,c,chat,'我通常喜欢先给结论再给依据。')
    assert items(c)[0]['scope']=='project'
    other=conversation(c)
    assert not recall(env[0].state.db,uid(c),other['id'],'回答结构',ACCESS)[0]
    context(c,other,topics=['论文'])
    message(env,c,other,'记住，我希望用中文回答。')
    assert next(e for e in items(c) if '中文' in e['content'])['scope']=='topic'


def test_multiple_topics_do_not_guess_a_global_audience(env):
    c=account(env);chat=conversation(c)
    context(c,chat,topics=['论文','申请'])
    message(env,c,chat,'记住，我希望先核对材料。')
    assert not items(c) and short(c)


def test_working_frames_and_short_facts_do_not_cross_project_switch(env):
    c=account(env);chat=conversation(c);a=project(c,'项目甲');b=project(c,'项目乙')
    context(c,chat,project_id=a['id'])
    message(env,c,chat,'我需要准备甲项目材料。')
    first=c.get('/api/conversations/'+chat['id']+'/working-memory').json()
    r=c.put('/api/conversations/'+chat['id']+'/working-memory',json={'version':first['version'],'content':'甲项目人工锁定记录','locked':True})
    assert r.status_code==200
    context(c,chat,project_id=b['id'])
    assert c.get('/api/conversations/'+chat['id']+'/working-memory').json()['content']==''
    message(env,c,chat,'我需要准备乙项目材料。')
    state=c.get('/api/conversations/'+chat['id']+'/memory-state').json()['state']
    assert '乙项目' in state['goal'] and '甲项目' not in dumps(state)
    context(c,chat,project_id=a['id'])
    assert c.get('/api/conversations/'+chat['id']+'/working-memory').json()['content']=='甲项目人工锁定记录'


def test_manual_promotion_uses_captured_scope_and_validates_import_like_content(env):
    c=account(env);chat=conversation(c);a=project(c,'甲');b=project(c,'乙')
    context(c,chat,project_id=a['id'])
    message(env,c,chat,'我计划今天提交甲的材料。')
    item=next(i for i in short(c) if i['kind']=='intention')
    context(c,chat,project_id=b['id'])
    result=c.post('/api/memory/session-items/'+item['id']+'/promote',json={'scope':'current'})
    assert result.status_code==200,result.text
    saved=c.get('/api/memory/items/'+result.json()['id']).json()
    assert saved['project_id']==a['id'] and saved['locked'] and saved['admission']=='manual'
    assert c.post('/api/memory/session-items/'+item['id']+'/promote',json={}).json()['already_promoted']


def test_two_conversations_promote_but_single_conversation_repeats_do_not(env):
    c=account(env);a=conversation(c);b=conversation(c)
    phrase='我希望回答先给结论再解释。'
    for chat in (a,a):
        mid=message(env,c,chat,phrase)
        with env[0].state.db.connect(write=True) as conn:
            session_item(conn,uid(c),chat['id'],mid,phrase,'preference')
            maintain(conn,uid(c))
    assert items(c)==[]
    mid=message(env,c,b,phrase)
    with env[0].state.db.connect(write=True) as conn:
        session_item(conn,uid(c),b['id'],mid,phrase,'preference')
        report=maintain(conn,uid(c))
    assert report['promoted']==1
    assert items(c)[0]['admission']=='repeated'


def test_cross_session_switch_and_individual_sharing_are_enforced(env):
    c=account(env);a=conversation(c);b=conversation(c)
    mid=message(env,c,a,'记住，我的名字是小林。')
    item=items(c)[0]
    r=c.put('/api/memory/items/'+item['id']+'/lifecycle',json={'version':item['version'],'tier':'long_term','shared':False})
    assert r.status_code==200,r.text
    assert not recall(env[0].state.db,uid(c),b['id'],'怎么称呼我',ACCESS)[0]
    assert recall(env[0].state.db,uid(c),a['id'],'怎么称呼我',ACCESS)[0]
    settings=c.get('/api/memory/lifecycle').json()['settings']
    assert c.put('/api/memory/lifecycle/settings',json={**settings,'cross_session':False}).status_code==200


def test_irrelevant_pinned_fact_is_not_a_universal_instruction(env):
    c=account(env);chat=conversation(c)
    irrelevant=memory(c,content='我喜欢仙人掌和盆栽。',kind='fact',pinned=True)
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'请分析奖学金申请材料。',ACCESS)
    assert irrelevant['id'] not in {i['id'] for i in selected}


def test_applicability_limits_style_and_facets_find_paraphrased_identity(env):
    c=account(env);chat=conversation(c)
    style=memory(c,content='我希望论文回答详细。',kind='preference')
    c.put('/api/memory/items/'+style['id']+'/lifecycle',json={'version':1,'tier':'long_term','applies_to':['论文']})
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'请分析奖学金申请。',ACCESS)
    assert style['id'] not in {e['id'] for e in selected}
    person=memory(c,content='我的名字是小林。',kind='fact')
    selected,report=recall(env[0].state.db,uid(c),chat['id'],'怎么称呼我',ACCESS)
    assert person['id'] in {e['id'] for e in selected} and 'identity.name' in report['requested_facets']


def test_ageing_retains_original_but_stops_automatic_use_and_manual_is_protected(env):
    c=account(env);chat=conversation(c);mid=message(env,c,chat,'记住，我喜欢简短回答。')
    auto=items(c)[0];human=memory(c,content='人工确认的稳定信息',kind='fact')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE memory_semantics SET review_after=? WHERE memory_id IN (?,?)',(1,auto['id'],human['id']))
        report=maintain(conn,uid(c))
    assert report['cooled']==1
    assert c.get('/api/memory/items/'+auto['id']).json()['state']=='cooling'
    assert c.get('/api/memory/items/'+human['id']).json()['state']=='active'
    assert auto['id'] not in {e['id'] for e in recall(env[0].state.db,uid(c),chat['id'],'回答',ACCESS)[0]}


def test_feedback_requires_real_exposure_is_idempotent_and_outdated_suspends_use(env):
    c=account(env);chat=conversation(c);saved=memory(c,content='我的名字是小林。',kind='fact')
    parent=message(env,c,chat,'你知道我的名字吗？');aid=ident()
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant','小林','complete',?,?)",(aid,chat['id'],parent,int(time.time())))
        remember_exposure(conn,uid(c),aid,[{'id':'memory-'+saved['id'],'memory_id':saved['id'],'evidence_kind':'memory'}])
    url='/api/memory/items/'+saved['id']+'/feedback'
    for _ in range(2):assert c.post(url,json={'version':1,'message_id':aid,'outcome':'helpful'}).status_code==200
    with env[0].state.db.connect() as conn:
        row=conn.execute('SELECT * FROM memory_semantics WHERE memory_id=?',(saved['id'],)).fetchone()
        assert row['positive']==1
        assert conn.execute('SELECT outcome FROM memory_usage WHERE message_id=?',(aid,)).fetchone()[0]=='exposed'
    assert c.post(url,json={'version':1,'message_id':aid,'outcome':'outdated'}).status_code==200
    assert c.get('/api/memory/items/'+saved['id']).json()['state']=='needs_review'
    assert not recall(env[0].state.db,uid(c),chat['id'],'名字',ACCESS)[0]
    other=account(env,'other');assert other.post(url,json={'version':1,'message_id':aid,'outcome':'helpful'}).status_code==404


def test_natural_forgetting_covers_old_versions_and_history_cannot_relearn(env):
    c=account(env);chat=conversation(c)
    mid=message(env,c,chat,'记住，我的名字是小林。')
    old=items(c)[0]
    message(env,c,chat,'请忘记我之前的称呼。')
    assert not items(c)
    with env[0].state.db.connect(write=True) as conn:
        filtered=filter_history(conn,uid(c),[{'id':mid,'content':'记住，我的名字是小林。'}])
        assert '小林' not in filtered[0]['content']
        conn.execute("UPDATE memory_jobs SET state='queued' WHERE source_id=?",(mid,))
        assert ingest_message(conn,uid(c),chat['id'],mid)==[]
    assert not items(c)


def test_forgetting_one_fact_does_not_block_another_fact_in_same_message(env):
    c=account(env);chat=conversation(c)
    text='记住，我的名字是小林。记住，我喜欢简短回答。'
    mid=message(env,c,chat,text)
    name=next(i for i in items(c) if '名字' in i['content'])
    assert c.request('DELETE','/api/memory/items/'+name['id'],json={'version':name['version']}).status_code==200
    assert any('简短' in i['content'] for i in items(c))
    with env[0].state.db.connect() as conn:
        filtered=filter_history(conn,uid(c),[{'id':mid,'content':text}])[0]['content']
        assert '小林' not in filtered and '简短' in filtered


def test_short_forgetting_removes_checkpoint_and_blocks_backfill(env):
    c=account(env);chat=conversation(c);mid=message(env,c,chat,'我计划今天去图书馆。')
    entry=next(e for e in short(c) if e['kind']=='intention')
    assert c.delete('/api/memory/session-items/'+entry['id']).status_code==200
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE memory_jobs SET state='queued' WHERE source_id=?",(mid,))
        ingest_message(conn,uid(c),chat['id'],mid)
    assert not any('图书馆' in e['content'] for e in short(c))


def test_unrelated_edit_does_not_invalidate_answer_but_selected_edit_does(env):
    c=account(env);chat=conversation(c)
    selected=memory(c,content='我的名字是小林。',kind='fact');other=memory(c,content='无关的植物资料',kind='fact')
    with env[0].state.db.connect() as conn:
        snapshot=bind_memories(conn,uid(c),chat['id'],capture(conn,uid(c),chat['id'],{**ACCESS,'memory':True}),[selected])
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE personal_memories SET content=?,version=version+1 WHERE id=?',('更新的植物资料',other['id']))
        assert_current(conn,uid(c),chat['id'],snapshot)
        conn.execute('UPDATE personal_memories SET content=?,version=version+1 WHERE id=?',('我的名字改为小陈。',selected['id']))
        with pytest.raises(AIError):assert_current(conn,uid(c),chat['id'],snapshot)


def test_expiry_source_delete_and_cross_user_short_term_access(env):
    c=account(env);other=account(env,'other');chat=conversation(c)
    mid=message(env,c,chat,'我需要准备实验材料。')
    entry=short(c)[0]
    assert other.delete('/api/memory/session-items/'+entry['id']).status_code==404
    assert other.get('/api/conversations/'+chat['id']+'/memory-state').status_code==404
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('DELETE FROM conversation_messages WHERE id=?',(mid,))
        assert not session_state(conn,uid(c),chat['id'])['goal']
        assert working_for(conn,chat['id'])['content']==''


def test_lifecycle_configuration_cas_and_expiry_reduction(env):
    c=account(env);chat=conversation(c);message(env,c,chat,'我希望今天采用精简格式。')
    before=short(c)[0]['expires_at']
    options=c.get('/api/memory/lifecycle').json()['settings']
    payload={**options,'session_days':1}
    assert c.put('/api/memory/lifecycle/settings',json=payload).status_code==200
    assert short(c)[0]['expires_at']==before-6*86400
    assert c.put('/api/memory/lifecycle/settings',json=payload).status_code==409


def test_new_topic_resets_session_without_erasing_long_term(env):
    c=account(env);chat=conversation(c)
    message(env,c,chat,'请帮我准备交流申请。')
    message(env,c,chat,'记住，我的名字是小林。')
    message(env,c,chat,'换个话题，请帮我计划课程复习。')
    state=c.get('/api/conversations/'+chat['id']+'/memory-state').json()['state']
    assert '课程复习' in state['goal'] and '交流申请' not in dumps(state)
    assert any('小林' in i['content'] for i in items(c))


def reflection_fixture(env):
    c=account(env);chat=conversation(c)
    a=memory(c,content='写作先核对来源。',kind='constraint')
    b=memory(c,content='回答应区分事实和建议。',kind='preference')
    message(env,c,chat,'请整理我的写作经验。')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('INSERT INTO conversation_ai_consents VALUES(?,?)',(chat['id'],int(time.time())))
        conn.execute('UPDATE conversations SET updated_at=? WHERE id=?',(int(time.time())-120,chat['id']))
    options=c.get('/api/memory/lifecycle').json()['settings']
    assert c.put('/api/memory/lifecycle/settings',json={**options,'semantic_reflection':True,'reflection_budget':1}).status_code==200
    env[1].ai_api_key='fixture'
    return c,chat,a,b


def test_semantic_reflection_is_opt_in_and_retains_source_bounded_proposals(env):
    from app.memory_reflection import enqueue,run_one
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:assert enqueue(conn,uid(c))==1
    called=[]
    def provider(settings,payload):
        called.append(payload)
        return {'proposals':[{'kind':'skill','content':'写作方法：核对来源并区分事实与建议。','source_memory_ids':[a['id'],b['id']]}]}, {'prompt_tokens':123}
    result=run_one(env[0].state.db,env[1],provider)
    assert result['proposals']==1 and len(called)==1
    proposed=next(e for e in items(c) if e['origin']=='reflection')
    assert proposed['review_status']=='pending' and not proposed['active']
    assert len(c.get('/api/memory/items/'+proposed['id']).json()['links'])==2
    with env[0].state.db.connect(write=True) as conn:assert enqueue(conn,uid(c))==0
    assert run_one(env[0].state.db,env[1],provider)['processed']==0 and len(called)==1


def test_semantic_reflection_cancels_changed_or_revoked_sources(env):
    from app.memory_reflection import enqueue,run_one
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    def provider(settings,payload):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE personal_memories SET content=?,version=version+1 WHERE id=?',('更正后的原文约束',a['id']))
        return {'proposals':[{'kind':'summary','content':'旧来源生成的过时结论。','source_memory_ids':[a['id'],b['id']]}]},{}
    result=run_one(env[0].state.db,env[1],provider)
    assert result['cancelled'] and not any(e['origin']=='reflection' for e in items(c))


def test_reflection_failure_is_not_automatically_rebilled_and_forgetting_purges_snapshots(env):
    from app.memory_reflection import enqueue,run_one
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    calls=[]
    def provider(settings,payload):calls.append(1);raise TimeoutError('fixture')
    assert run_one(env[0].state.db,env[1],provider)['failed']
    assert run_one(env[0].state.db,env[1],provider)['processed']==0 and calls==[1]
    assert c.request('DELETE','/api/memory/items/'+a['id'],json={'version':a['version']}).status_code==200
    with env[0].state.db.connect() as conn:
        assert not conn.execute('SELECT 1 FROM memory_reflection_jobs WHERE user_id=?',(uid(c),)).fetchone()


def test_disabling_semantic_reflection_before_processing_cancels_without_call(env):
    from app.memory_reflection import enqueue,run_one
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    options=c.get('/api/memory/lifecycle').json()['settings']
    assert c.put('/api/memory/lifecycle/settings',json={**options,'semantic_reflection':False}).status_code==200
    def provider(settings,payload):raise AssertionError('provider must not be called')
    assert run_one(env[0].state.db,env[1],provider)['processed']==0
    assert c.get('/api/memory/lifecycle').json()['reflection_jobs'][0]['state']=='cancelled'


def test_derived_summary_cannot_bypass_parent_cross_session_policy(env):
    c=account(env);a=conversation(c);b=conversation(c)
    message(env,c,a,'记住，我喜欢先核对原文。')
    parent=items(c)[0]
    with env[0].state.db.connect(write=True) as conn:
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary','content':'基于原文核对的学习摘要','source_conversation_id':a['id']},origin='agent',locked=False,parents=[parent])
    c.put('/api/memory/items/'+parent['id']+'/lifecycle',json={'version':parent['version'],'tier':'long_term','shared':False})
    selected,_=recall(env[0].state.db,uid(c),b['id'],'原文核对摘要',ACCESS)
    assert child not in {i['id'] for i in selected}


def test_expired_session_does_not_revive_when_retention_is_extended(env):
    c=account(env);chat=conversation(c);message(env,c,chat,'我计划今天核对资料。')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE memory_session_items SET expires_at=? WHERE user_id=?',(int(time.time())-1,uid(c)))
    options=c.get('/api/memory/lifecycle').json()['settings']
    assert c.put('/api/memory/lifecycle/settings',json={**options,'session_days':90}).status_code==200
    assert short(c)==[]


def test_reflection_daily_budget_and_same_scope_validation(env):
    from app.memory_reflection import enqueue,run_one
    c,chat,a,b=reflection_fixture(env)
    with env[0].state.db.connect(write=True) as conn:enqueue(conn,uid(c))
    calls=[]
    def provider(settings,payload):calls.append(1);return {'proposals':[]},{}
    assert run_one(env[0].state.db,env[1],provider)['processed']==1
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE personal_memories SET version=version+1 WHERE id=?',(a['id'],))
        assert enqueue(conn,uid(c))==1
    assert run_one(env[0].state.db,env[1],provider)['processed']==0 and len(calls)==1


def test_v2_schema_migrates_and_new_tables_are_required_for_v3(env):
    c=account(env);saved=memory(c,content='旧版本人工维护的中文偏好')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE meta SET value='2' WHERE key='memory_engine_schema_version'")
        conn.execute('DROP TABLE memory_reflection_jobs')
    reopened=Database(env[0].state.db.path)
    with reopened.connect() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='memory_engine_schema_version'").fetchone()[0]=='3'
        assert conn.execute('SELECT content FROM personal_memories WHERE id=?',(saved['id'],)).fetchone()[0]=='旧版本人工维护的中文偏好'
    with reopened.connect(write=True) as conn:conn.execute('DROP TABLE memory_reflection_jobs')
    with pytest.raises(RuntimeError):Database(reopened.path)


def test_backfill_uses_original_project_and_does_not_replay_old_forget_commands(env):
    c=account(env);chat=conversation(c);a=project(c,'原项目');b=project(c,'新项目')
    context(c,chat,project_id=a['id'])
    mid=message(env,c,chat,'记住，我希望使用中文回答。',learn=False)
    context(c,chat,project_id=b['id'])
    with env[0].state.db.connect(write=True) as conn:ingest_message(conn,uid(c),chat['id'],mid,explicit_backfill=True)
    assert items(c)[0]['project_id']==a['id']
    context(c,chat,project_id=a['id'])
    forget=message(env,c,chat,'请忘记我的写作语言。')
    assert not items(c)
    recreated=memory(c,scope='project',project_id=a['id'],content='现在人工重新启用中文偏好',semantic_key='写作语言')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE memory_jobs SET state='queued' WHERE source_id=?",(forget,))
        ingest_message(conn,uid(c),chat['id'],forget,explicit_backfill=True)
    assert recreated['id'] in {i['id'] for i in items(c)}


def test_unknown_historical_scope_is_not_automatically_global(env):
    c=account(env);chat=conversation(c)
    mid=message(env,c,chat,'记住，我喜欢先核对来源。',learn=False)
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE memory_message_context SET context_key='',learning_allowed=0 WHERE message_id=?",(mid,))
        ingest_message(conn,uid(c),chat['id'],mid,explicit_backfill=True)
    assert not items(c)
    entry=next(e for e in short(c) if e['kind']=='preference')
    assert not entry['context_key']
    assert c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'current'}).status_code==422
    assert c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'global'}).status_code==200


def test_turn_only_memory_restriction_does_not_disable_future_turns():
    from app.memory import memory_access
    assert not memory_access([{'role':'user','content':'仅本轮，不要使用记忆。'}])
    assert memory_access([{'role':'user','content':'仅本轮，不要使用记忆。'},{'role':'user','content':'现在继续准备材料。'}])


def test_clear_all_retires_unindexed_history_across_projects_but_future_learning_works(env):
    from app.memory_lifecycle import put_working
    c=account(env);a=conversation(c);b=conversation(c);p=project(c)
    old=message(env,c,a,'记住，我习惯先列来源再下结论。',learn=False)
    message(env,c,a,'我计划今天核对原文。')
    context(c,b,project_id=p['id'])
    message(env,c,b,'记住，我希望使用中文回答。')
    for i in range(8):memory(c,content=f'本人确认的历史条件 {i}')
    with env[0].state.db.connect(write=True) as conn:
        put_working(conn,a['id'],'本人手动锁定的旧工作内容',locked=True)
        assistant=ident()
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant',?,'complete',?,?)",
            (assistant,a['id'],'旧回答包含习惯条件',old,int(time.time())))
    message(env,c,b,'请清空我的所有记忆。')
    assert not items(c) and not short(c)
    with env[0].state.db.connect(write=True) as conn:
        assert not working_for(conn,a['id'])['content']
        assert not conn.execute('SELECT 1 FROM memory_checkpoints').fetchone()
        rows=[dict(r) for r in conn.execute('SELECT id,content FROM conversation_messages WHERE id IN (?,?)',(old,assistant))]
        assert all('撤销' in row['content'] for row in filter_history(conn,uid(c),rows))
        conn.execute("UPDATE memory_jobs SET state='queued' WHERE source_id=?",(old,))
        ingest_message(conn,uid(c),a['id'],old,explicit_backfill=True)
        assert session_item(conn,uid(c),a['id'],old,'记住，我习惯先列来源再下结论。') is None
    assert not items(c) and not short(c)
    message(env,c,a,'记住，我的专业是计算机科学。')
    assert any('计算机科学' in i['content'] for i in items(c))


def test_single_fact_forgetting_suppresses_related_assistant_history(env):
    c=account(env);chat=conversation(c);mid=message(env,c,chat,'记住，我希望使用中文回答。')
    with env[0].state.db.connect(write=True) as conn:
        aid=ident()
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant',?,'complete',?,?)",
            (aid,chat['id'],'已记住你的中文偏好。',mid,int(time.time())))
    message(env,c,chat,'请忘记我的写作语言。')
    with env[0].state.db.connect() as conn:
        assert '撤销' in filter_history(conn,uid(c),[{'id':aid,'content':'已记住你的中文偏好。'}])[0]['content']


def test_promoting_current_topic_keeps_topic_and_ambiguous_topics_need_choice(env):
    c=account(env);chat=conversation(c);context(c,chat,topics=['课程论文'])
    message(env,c,chat,'我计划今天核对原始论文。')
    entry=next(e for e in short(c) if e['kind']=='intention')
    result=c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'current','content':'我偏好先核对论文原始来源。'})
    assert result.status_code==200,result.text
    saved=c.get('/api/memory/items/'+result.json()['id']).json()
    assert saved['scope']=='topic' and saved['topic']=='课程论文' and saved['kind']=='preference'
    context(c,chat,topics=['课程论文','助学申请'])
    message(env,c,chat,'我计划今天核对申请材料。')
    entry=next(e for e in short(c) if '申请材料' in e['content'] and e['kind']=='intention')
    assert c.post('/api/memory/session-items/'+entry['id']+'/promote',json={'scope':'current'}).status_code==422


def test_repeated_evidence_never_revives_archived_human_memory(env):
    c=account(env);a=conversation(c);b=conversation(c)
    saved=memory(c,content='我希望使用中文回答。',semantic_key='写作语言')
    c.put('/api/memory/items/'+saved['id']+'/lifecycle',json={'version':saved['version'],'tier':'long_term','status':'archived'})
    sources=[(chat,message(env,c,chat,'我希望使用中文回答。',learn=False)) for chat in (a,b)]
    with env[0].state.db.connect(write=True) as conn:
        for chat,mid in sources:
            session_item(conn,uid(c),chat['id'],mid,'我希望使用中文回答。','preference')
        assert maintain(conn,uid(c))['promoted']==0
    assert c.get('/api/memory/items/'+saved['id']).json()['status']=='archived'


def test_task_summary_cannot_reintroduce_unrelated_progress_or_bypass_action_scope(env):
    from app.memory_policy import rows_for
    c=account(env);chat=conversation(c)
    with env[0].state.db.connect(write=True) as conn:
        parent_id=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'episode',
            'content':'办理记录：虚构奖学金申请。当前状态：待办理。','source_conversation_id':chat['id']},origin='task',locked=False)
        parent=next(i for i in rows_for(conn,uid(c)) if i['id']==parent_id)
        child=insert_memory(conn,uid(c),{'scope':'global','project_id':None,'topic':'','kind':'summary',
            'content':'申请资料及回执概览：虚构奖学金申请尚未完成。','source_conversation_id':chat['id']},origin='organizer',locked=False,parents=[parent])
    assert child not in {i['id'] for i in recall(env[0].state.db,uid(c),chat['id'],'如何核对申请资料？',ACCESS)[0]}
    assert child in {i['id'] for i in recall(env[0].state.db,uid(c),chat['id'],'我的待办申请资料还有哪些？',ACCESS)[0]}
    mid=message(env,c,chat,'不要使用我的日程。请总结申请资料经验。')
    result=actions(env,c,chat,mid,{'operation':'derive','kind':'summary','content':'新的申请经验总结',
        'source_quote':'请总结申请资料经验。','source_memory_ids':[child]})
    assert result[0]['status']=='rejected'


def test_business_sequences_are_not_treated_as_universal_presentation_preferences(env):
    c=account(env);chat=conversation(c)
    saved=[memory(c,kind='skill',content=f'课程申请方法 {i}：先核对原文，再准备材料，附加核对条件 {i}。') for i in range(4)]
    assert all(not c.get('/api/memory/items/'+item['id']).json()['facet'].startswith('style.') for item in saved)
    selected,_=recall(env[0].state.db,uid(c),chat['id'],'课程申请方法',ACCESS)
    assert len({item['id'] for item in saved}&{item['id'] for item in selected})==4


@pytest.mark.parametrize('finish,valid',[('stop',True),('length',False)])
def test_reflection_provider_adapter_checks_transport_completion(env,monkeypatch,finish,valid):
    import httpx
    from app import memory_reflection
    original=httpx.Client
    def handler(request):
        assert request.url.path.endswith('/chat/completions')
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"proposals":[]}'},'finish_reason':finish}],
            'usage':{'prompt_tokens':42,'completion_tokens':5}})
    monkeypatch.setattr(memory_reflection.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler)))
    if valid:
        result,usage=memory_reflection.provider_call(env[1],{'memories':[]})
        assert result=={'proposals':[]} and usage['prompt_tokens']==42
    else:
        with pytest.raises(ValueError):memory_reflection.provider_call(env[1],{'memories':[]})
