"""Automatic age, reversible filtering and original-evidence network contracts."""
import asyncio
import json
import time
import threading
from datetime import datetime
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import grounding
from app.db import ident,dumps
from app.documents import text_source
from app.notice_lifecycle import lifecycle,CST
from app.notice_network import candidates,read_network,retain_unavailable
from app.notice_automation import mark_profile
from app.agent_runtime.chat import ChatRun
from app.agent_runtime.types import AgentError
from tests.test_workflow import env,account,notice
from tests.test_workspace import conversation


def stamp(value):return int(datetime.fromisoformat(value).replace(tzinfo=CST).timestamp())
NOW=stamp('2026-11-02T12:00')


def dated(day='2026-09-02',clock='17:00',quote=None):
    return {'scope':'personal','title':'提交申请','due_date':day,'due_time':clock,
        'deadline_evidence':[{'source_id':'s','locator':'正文','quote':quote or day+' '+(clock or '')+'前提交申请'}]}


def draft(*tasks):return {'applicability':'matches_known','quality':{'status':'passed'},'tasks':list(tasks)}


def test_old_opportunity_expires_without_opt_in_or_changing_personal_tasks():
    d=draft(dated());n={'published_at':None}
    result=lifecycle(n,d,current=True,now=NOW)
    assert result['automatic'] and result['state']=='elapsed' and result['expired_actions'][0]['evidence']
    assert '未把个人待办改成已完成' in result['reason']
    assert d['tasks'][0]['due_date']=='2026-09-02'
    assert lifecycle(n,d,current=False,now=NOW)['state']=='unknown'
    d['quality']['status']='needs_review'
    assert lifecycle(n,d,current=True,now=NOW)['state']=='unknown'


def test_only_explicit_year_and_all_actions_can_establish_whole_notice_expiry():
    n={'published_at':None}
    assert lifecycle(n,draft(dated(quote='9月2日17:00前提交')),current=True,now=NOW)['state']=='unknown'
    assert lifecycle(n,draft(dated(),{'scope':'personal','title':'等待后续结果'}),current=True,now=NOW)['state']=='unknown'
    changed=lifecycle(n,draft(dated(),dated('2026-11-20')),current=True,now=NOW)
    assert changed['state']=='mixed' and len(changed['open_actions'])==1
    assert lifecycle(n,draft(dated(quote='2026-09-02 提交申请')),current=True,now=NOW)['state']=='unknown'


def test_date_only_and_event_boundaries_do_not_invent_an_end_time():
    n={};d=draft(dated('2026-11-02',None))
    assert lifecycle(n,d,current=True,now=stamp('2026-11-02T23:59:59'))['state']=='active'
    assert lifecycle(n,d,current=True,now=stamp('2026-11-03T00:00'))['state']=='elapsed'
    event={'scope':'personal','title':'参加会议','scheduled':{'start_date':'2026-11-02','start_time':'09:00',
        'evidence':[{'quote':'2026年11月2日9:00举行会议'}]}}
    assert lifecycle(n,draft(event),current=True,now=stamp('2026-11-03T00:00'))['state']=='unknown'
    event['scheduled'].update(end_date='2026-11-02',end_time='17:00',evidence=[{'quote':'2026年11月2日9:00至17:00举行会议'}])
    assert lifecycle(n,draft(event),current=True,now=stamp('2026-11-02T12:00'))['state']=='active'
    assert lifecycle(n,draft(event),current=True,now=stamp('2026-11-03T00:00'))['state']=='elapsed'


def test_urgent_optional_opportunity_does_not_wait_past_its_verified_deadline():
    from app.proactive_policy import assess,delivery_slot
    from app.models import NotificationPreferences
    at=stamp('2026-11-02T16:59:30');n={'title':'合成机会','draft':{**draft(dated('2026-11-02')),'plans':{'0':{'action_kind':'optional'}}}}
    pref=NotificationPreferences(mode='digest')
    decision=assess(n,current_draft=True,pref=pref,now=at)
    assert decision['priority']=='P2' and decision['urgency']['state']=='due_soon' and decision['delivery']=='near_term'
    assert delivery_slot(at,decision,pref)[1]==at
    assert assess(n,current_draft=True,pref=pref,now=stamp('2026-11-02T17:00'))['delivery']=='silent'


def test_verified_old_event_preview_without_personal_tasks_is_not_presented_as_a_future_opportunity():
    from app.proactive_policy import assess
    n={'title':'通识教育大讲堂讲座预告','draft':{**draft(),'facts':{'dates':{
        'value':'2026年10月23日19:00','evidence':[{'source_id':'s','locator':'第1段','quote':'时 间：2026年10月23日（周五）19:00'}]}}}}
    result=assess(n,current_draft=True,now=NOW)
    assert result['tracking']['state']=='event_date_passed' and not result['recommended'] and result['delivery']=='silent'
    assert '不据此宣称活动已结束' in result['tracking']['reason']
    n['draft']['facts']['dates']['evidence'][0]['quote']='发布时间：2026年10月23日19:00'
    assert assess(n,current_draft=True,now=NOW)['tracking']['state']=='unknown'
    for quote in ['时间：2026年10月23日开始长期开放','时间：2026年10月23日、2027年3月12日','时间：10月23日19:00']:
        n['draft']['facts']['dates']['evidence'][0]['quote']=quote
        assert assess(n,current_draft=True,now=NOW)['tracking']['state']=='unknown'


def classified(c,db):
    n=notice(c,'2020-09-02 17:00前提交合成申请，材料可继续保留。')
    uid=c.get('/api/session').json()['user']['id']
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET status='draft',draft_version=version,draft=? WHERE id=?",(dumps(draft(dated('2020-09-02'))),n['id']))
        profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
        mark_profile(conn,n['id'],uid,n['version'],profile)
    return n


def test_expired_record_is_findable_and_reversible_with_owner_and_version_fences(env):
    c=account(env);other=account(env,'other');db=env[0].state.db;n=classified(c,db)
    rows=c.get('/api/notices').json();assert rows[0]['intent']=='closed' and rows[0]['recommended'] is False
    found=c.get('/api/notices/search',params={'q':'合成申请'}).json();assert found[0]['id']==n['id']
    url='/api/proactive/notices/'+n['id']+'/feedback'
    value={'notice_version':n['version'],'version':0,'mode':'include','note':'仍需补办，保留给我'}
    assert other.put(url,json=value).status_code==404
    assert c.put(url,json=value).status_code==200
    shown=c.get('/api/notices').json()[0]
    assert shown['recommended'] and shown['intent']=='decide' and shown['tracking']['state']=='elapsed'
    assert c.get('/api/notices/'+n['id']).json()['feedback']['mode']=='include'
    assert c.put(url,json=value).status_code==409
    for version,mode,visible in [(1,'exclude',False),(2,'auto',False),(3,'include',True)]:
        assert c.put(url,json={**value,'version':version,'mode':mode}).status_code==200
        assert c.get('/api/notices').json()[0]['recommended'] is visible
    assert c.get('/api/tasks').json()==[]
    detail=c.get('/api/proactive/notices/'+n['id']).json()
    assert detail['assessment']['tracking']['state']=='elapsed' and detail['evidence_chain']['documents']
    assert other.get('/api/proactive/notices/'+n['id']).status_code==404
    exported=c.get('/api/export').json()
    preview=other.post('/api/import',json={'data':exported});assert preview.status_code==200,preview.text
    imported=other.post('/api/import',json={'data':exported,'digest':preview.json()['digest'],'confirm':True})
    assert imported.status_code==200,imported.text
    assert other.get('/api/notices').json()[0]['feedback']['mode']=='include'


def test_notification_preferences_never_enter_model_profile_even_when_profile_is_allowed(env):
    from app.memory_context import basic_profile
    c=account(env);db=env[0].state.db;chat=conversation(c);uid=c.get('/api/session').json()['user']['id'];mid=ident()
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'assistant','','processing',?)",(mid,chat['id'],int(time.time())))
    for question in ['按我的条件回答','不要使用我的个人资料和记忆，只看本条消息']:
        result=basic_profile(db,uid,chat['id'],mid,[{'role':'user','content':question}],{'college':'合成学院','notification_preferences':{'muted_terms':['私有投递词']}})
        assert 'notification_preferences' not in result and '私有投递词' not in dumps(result)


def test_long_paragraph_tail_fact_is_retrieved_as_an_exact_original_span():
    text='不相关的正文。'*2400+'地理信息实验项目的最终提交入口为校内甲系统，截止2027年3月12日。'+'附注。'*400
    sources=[grounding.source('s','长篇通知',[{'locator':'正文第1段','text':text}],'notice')]
    got,coverage=grounding.select_sections(sources,['地理信息实验项目 最终提交入口'],7000)
    section=got[0]['sections'][0]
    assert '截止2027年3月12日' in section['text'] and section['_retrieval_offset']>0
    assert section['text']==text[section['_retrieval_offset']:section['_retrieval_offset']+len(section['text'])]
    assert section['_original_locator']=='正文第1段' and section['locator'].startswith('正文第1段（字符') and coverage['characters']<=7000


def test_two_queries_into_the_same_long_paragraph_preserve_both_exact_citations():
    from app.ai import check_evidence
    text='甲入口必须现场提交。'+'背景说明。'*2800+'乙入口允许线上补充。'
    records=[grounding.source('s','办事规则',[{'locator':'同一段','text':text}],'notice')]
    head,_=grounding.select_sections(records,['甲入口'],7000)
    tail,_=grounding.select_sections(records,['乙入口'],7000)
    run=ChatRun.__new__(ChatRun);run.records={};run.evidence_entries=[]
    run.merge(head);run.merge(tail)
    assert len(run.records['s']['sections'])==2
    citations=[{'source_id':'s','locator':head[0]['sections'][0]['locator'],'quote':'甲入口必须现场提交。'},
        {'source_id':'s','locator':tail[0]['sections'][0]['locator'],'quote':'乙入口允许线上补充。'}]
    check_evidence(citations,list(run.records.values()))
    with pytest.raises(ValueError):check_evidence([{**citations[0],'quote':'   '}],list(run.records.values()))
    assert tail[0]['retrieval_windows'][0]['original_locator']=='同一段'


def minimal_run():
    run=ChatRun.__new__(ChatRun)
    run.db=None;run.uid='owner';run.cid='conversation';run.original=[];run.user_messages=[];run.profile={}
    run.access={'library':True};run.used_scopes=set();run.read_cache={};run.read_locks={};run.read_epoch=0;run.retrieval_metrics=[]
    run.guard=lambda:None;run.merge=lambda records:None;run.indexed_sources=lambda records:{'sources':records}
    return run


def test_concurrent_same_scope_retrieval_is_coalesced_and_event_loop_remains_responsive(monkeypatch):
    calls=[];finished=threading.Event()
    def slow(db,uid,*args):
        calls.append(uid);time.sleep(.08);finished.set();return [],{'scanned':{'sections':1}}
    monkeypatch.setattr(grounding,'retrieve',slow)
    async def scenario():
        run=minimal_run();ticks=[]
        async def heartbeat():
            for _ in range(4):await asyncio.sleep(.008);ticks.append(finished.is_set())
        result=await asyncio.gather(run.local('申请',['library']),run.local('申请',['library']),heartbeat())
        assert result[0]==result[1] and len(ticks)==4 and not any(ticks) and calls==['owner']
        assert sum(item['cached'] for item in run.retrieval_metrics)==1
        run.invalidate_reads();await run.local('申请',['library']);assert len(calls)==2
    asyncio.run(scenario())


def test_inflight_old_retrieval_cannot_repopulate_cache_after_an_authorized_edit(monkeypatch):
    started=threading.Event();release=threading.Event()
    def retrieve(*args):started.set();release.wait(2);return [],{}
    monkeypatch.setattr(grounding,'retrieve',retrieve)
    async def scenario():
        run=minimal_run();task=asyncio.create_task(run.local('申请',['library']))
        while not started.is_set():await asyncio.sleep(.002)
        run.invalidate_reads();release.set()
        with pytest.raises(AgentError,match='未采用旧结果'):await task
        assert not run.read_cache
    asyncio.run(scenario())


CONFIG={'url':'https://school.example.edu.cn/list','article_path_prefix':'/info/','mode':'html'}


def primary():
    result=text_source('原始项目正文。','2026年地理信息创新实践项目报名通知')
    result['origin']={'url':'https://school.example.edu.cn/info/1.htm','attachments':['https://school.example.edu.cn/apply.pdf'],'warnings':[],'published_at':None}
    return result


def test_auto_research_reads_attachments_and_same_matter_supplement_without_user_item_opt_in():
    calls=[]
    entries=[{'url':'https://school.example.edu.cn/info/2.htm','title':'2026年地理信息创新实践项目延期通知','published_at':None},
        {'url':'https://school.example.edu.cn/info/3.htm','title':'2025年地理信息创新实践项目结果公示','published_at':None},
        {'url':'https://other.example.edu.cn/info/4.htm','title':'2026年地理信息创新实践项目补充通知','published_at':None}]
    async def read(url):
        calls.append(url);s=text_source('实际附件内容' if url.endswith('pdf') else '延期的正式原文','补充材料')
        s['origin']={'url':url,'attachments':[],'warnings':[],'retrieved_at':123}
        if url.endswith('pdf'):s.update(kind='pdf',content=b'%PDF-synthetic')
        return s,'材料'
    got=asyncio.run(read_network(primary(),CONFIG,entries,read=read))
    assert len(got)==3 and len(calls)==2 and not any('3.htm' in url or 'other.' in url for url in calls)
    assert got[1]['origin']['relationship']=='attachment' and got[1]['origin']['relationship_verified']
    assert got[2]['origin']['relationship']=='index_candidate' and not got[2]['origin']['relationship_verified']
    assert got[0]['origin']['related_search']['complete']
    assert all('parent_url' in s['origin'] for s in got[1:])


def test_different_lecture_occurrences_do_not_cross_link_but_supplement_numbers_can():
    from app.notice_network import relation
    left={'title':'通识教育大讲堂第七十五讲预告','published_at':'2026-10-16'}
    assert not relation(left,{'title':'通识教育大讲堂第七十六讲预告','published_at':'2026-10-20'})
    assert relation({'title':'2026年地理信息创新实践会议通知（第二号）','published_at':'2026-09-01'},
        {'title':'2026年地理信息创新实践会议通知（第三号）','published_at':'2026-09-03'})


def test_failed_related_source_and_unsupported_attachment_keep_primary_and_visible_gaps():
    p=primary();p['origin']['attachments']=['https://school.example.edu.cn/old.zip']
    entries=[{'url':'https://school.example.edu.cn/info/2.htm','title':'2026年地理信息创新实践项目补充通知','published_at':None}]
    async def read(url):raise HTTPException(502,'来源维护中')
    got=asyncio.run(read_network(p,CONFIG,entries,read=read))
    assert len(got)==1 and got[0]['sections']==p['sections']
    assert '来源维护中' in dumps(got[0]['origin']['related_search']['errors'])
    assert any('附件格式' in warning for warning in got[0]['origin']['warnings'])


def test_related_primary_notices_are_not_merged_just_because_their_evidence_sets_match():
    from app.notice_ingest import fingerprint
    a,b=primary(),text_source('明确延期至2027年3月12日','正式延期通知')
    a['origin']['related_search']={'candidates':[]}
    b['origin']={'relationship':'index_candidate','url':'https://school.example.edu.cn/info/2.htm'}
    left=fingerprint([a,b])
    first={**a,'origin':{**a['origin'],'relationship':'index_candidate'}};first['origin'].pop('related_search')
    second={**b,'origin':{'related_search':{'candidates':[]},'url':b['origin']['url']}}
    assert left!=fingerprint([second,first])
    assert fingerprint([text_source('正文')])==fingerprint([{**text_source('正文'),'origin':{'related_search':{'candidates':[]}}}])


def test_failed_related_recheck_preserves_last_snapshot_and_original_retrieval_time(env):
    from app.notice_ingest import ingest_notice
    c=account(env);other=account(env,'another');db=env[0].state.db;uid=c.get('/api/session').json()['user']['id'];key='network-fixture:1'
    other_uid=other.get('/api/session').json()['user']['id']
    root=primary();root['origin']['attachments']=[];root['origin']['related_search']={'candidates':[]}
    extension=text_source('延期：2027年3月12日17:00前提交','延期原文')
    extension['origin']={'url':'https://school.example.edu.cn/info/2.htm','retrieved_at':123,'parent_url':root['origin']['url'],'relationship':'index_candidate'}
    with db.connect(write=True) as conn:
        result=ingest_notice(conn,uid,title=root['name'],sources=[root,extension],external_key=key)
        current=primary();current['origin']['attachments']=[]
        current['origin']['related_search']={'errors':[{'url':extension['origin']['url'],'error':'503'}]}
        materials=retain_unavailable(conn,uid,key,[current])
        assert len(materials)==2 and materials[1]['origin']['retrieved_at']==123
        assert materials[0]['origin']['retained_snapshots'][0]['sha256']==extension['sha256']
        assert len(retain_unavailable(conn,other_uid,key,[current]))==1


def test_revision_is_private_detects_corrections_and_contains_no_profile_payload(env,monkeypatch):
    import app.proactive as proactive
    monkeypatch.setattr(proactive.time,'time',lambda:NOW)
    c=account(env);other=account(env,'other');n=classified(c,env[0].state.db)
    before=c.get('/api/proactive/revision');assert before.status_code==200,before.text
    assert set(before.json())=={'revision','poll_after_seconds','temporal_precision_seconds'}
    assert c.get('/api/proactive/revision').json()['revision']==before.json()['revision']
    assert other.get('/api/proactive/revision').json()['revision']!=before.json()['revision']
    result=c.put('/api/proactive/notices/'+n['id']+'/feedback',json={'notice_version':n['version'],'version':0,'mode':'include'})
    assert result.status_code==200,result.text
    assert c.get('/api/proactive/revision').json()['revision']!=before.json()['revision']


def test_source_updates_do_not_bypass_relevance_or_notify_unanalysed_history(env):
    from app.push_delivery import candidates as deliveries
    from tests.test_workflow import manual,confirm,task
    c=account(env);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id'];n=notice(c,'合成来源更新，补充了一份附件。');at=int(time.time())
    def updated(conn):return any(key.startswith('intake-change:') for key in deliveries(conn,uid,at))
    with db.connect(write=True) as conn:
        receipt=conn.execute('SELECT id FROM notice_ingest_receipts WHERE notice_id=?',(n['id'],)).fetchone()[0]
        conn.execute('INSERT INTO notice_ingest_updates(id,notice_id,receipt_id,previous_source_ids,new_source_ids,created_at) VALUES(?,?,?,?,?,?)',(ident(),n['id'],receipt,'[]','[]',at-180))
        conn.execute('INSERT INTO notice_delivery_suppressions VALUES(?,?)',(n['id'],'initial_snapshot'))
        assert not updated(conn)
        conn.execute('INSERT INTO notice_recommendation_feedback VALUES(?,?,?,?,?,1,?)',(n['id'],uid,'include','本人明确希望关注',n['version'],at))
        assert updated(conn)  # Explicit owner choice also covers unanalysed updates.
        conn.execute('DELETE FROM notice_recommendation_feedback WHERE notice_id=?',(n['id'],))
        d=draft();d['applicability']='not_matching'
        conn.execute("UPDATE notices SET status='draft',draft_version=version,draft=? WHERE id=?",(dumps(d),n['id']))
        mark_profile(conn,n['id'],uid,n['version'],conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0])
        assert not updated(conn)
        d['applicability']='matches_known';conn.execute('UPDATE notices SET draft=? WHERE id=?',(dumps(d),n['id']))
        assert updated(conn)
    current=c.get('/api/notices/'+n['id']).json();url='/api/proactive/notices/'+n['id']+'/feedback'
    assert c.put(url,json={'notice_version':current['version'],'version':0,'mode':'exclude'}).status_code==200
    with db.connect() as conn:assert not updated(conn)
    # Once personally chosen, requirement changes still need a receipt even
    # when the user has muted new information or the new analysis is pending.
    current=manual(c,c.get('/api/notices/'+n['id']).json());confirm(c,current,task(current))
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET status='received',version=version+1 WHERE id=?",(n['id'],))
        assert updated(conn)
