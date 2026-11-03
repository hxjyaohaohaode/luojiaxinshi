"""Adversarial regressions found during the complete pilot audit; no providers."""
import json
import time
import asyncio
import pytest
from app import ai,notice_automation
from app.db import dumps,ident
from app.documents import text_source
from app.notice_ingest import ingest_notice
from app.handling_assistant import fingerprint
from tests.test_workflow import env,account,notice,raw_ai
from tests.test_notice_automation import incoming,permit,generator


def test_obsolete_and_revoked_jobs_retire_even_when_daily_quota_is_exhausted(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c);permit(c,daily_limit=1)
    db=env[0].state.db;calls=[];generator(env,monkeypatch,calls)
    with db.connect(write=True) as conn:
        old=conn.execute('SELECT id FROM notice_automation_jobs WHERE notice_id=?',(nid,)).fetchone()[0]
        conn.execute('INSERT INTO notice_automation_attempts VALUES(?,?,?,?)',(ident(),old,uid,int(time.time())))
        conn.execute('UPDATE notices SET version=version+1 WHERE id=?',(nid,))
    assert notice_automation.run_once(env[0],db,env[1]) is None
    with db.connect() as conn:
        assert conn.execute('SELECT state FROM notice_automation_jobs WHERE id=?',(old,)).fetchone()[0]=='stale'
        assert conn.execute("SELECT count(*) FROM notice_automation_jobs WHERE user_id=? AND state='queued'",(uid,)).fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM notice_automation_attempts WHERE user_id=?',(uid,)).fetchone()[0]==1
    with db.connect(write=True) as conn:conn.execute('UPDATE source_subscriptions SET enabled=0 WHERE source_id=?',(sid,))
    assert notice_automation.run_once(env[0],db,env[1]) is None
    state=c.get('/api/notice-automation').json()
    assert state['counts'].get('queued',0)==0 and state['counts']['cancelled']==1
    assert state['used_today']==1 and not calls


@pytest.mark.parametrize('change,expected',[
    ({'notification_preferences':{'mode':'digest'}},200),
    ({'avatar_tone':'forest'},200),
    ({'college':'新的适用学院'},409),
])
def test_only_actual_model_profile_changes_interrupt_an_inflight_notice(env,monkeypatch,change,expected):
    c=account(env);n=notice(c);app,cfg=env;cfg.ai_api_key='synthetic-not-a-provider'
    uid=c.get('/api/session').json()['user']['id']
    def provider(settings,record,sources,profile):
        with app.state.db.connect(write=True) as conn:
            value=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]);value.update(change)
            conn.execute('UPDATE users SET profile=? WHERE id=?',(dumps(value),uid))
        from app.notice_progress import CURRENT
        CURRENT.get().phase('reviewing')
        return raw_ai(n),{'input_tokens':20,'output_tokens':30}
    monkeypatch.setattr(ai,'generate',provider)
    result=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert result.status_code==expected,result.text
    after=c.get('/api/notices/'+n['id']).json()
    if expected==200:
        assert after['status']=='draft'
        with app.state.db.connect() as conn:
            saved=json.loads(conn.execute("SELECT after_json FROM audit WHERE notice_id=? AND action='ai_processing_consent'",(n['id'],)).fetchone()[0])
            assert 'notification_preferences' not in saved['profile']
    else:assert after['status']=='failed'


def test_preparation_result_survives_local_notification_preferences_change():
    args=({'version':1},{'version':1},{'version':1})
    original=fingerprint(*args,{'college':'资环学院'},[])
    assert fingerprint(*args,{'college':'资环学院','notification_preferences':{'mode':'digest'}},[])==original
    assert fingerprint(*args,{'college':'另一个学院'},[])!=original


def test_changed_source_updates_title_and_publication_metadata_and_keeps_old_evidence(env):
    c=account(env);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    key='website:synthetic:revision'
    with db.connect(write=True) as conn:
        old=ingest_notice(conn,uid,sources=[text_source('原通知：原表于2026年9月2日前提交')],title='原申请通知',
            source_label='学院旧栏目名',source_url='https://school.example.edu.cn/info/one.htm',
            external_key=key,published_at='2026-09-01',observed_at=100)
        changed=ingest_notice(conn,uid,sources=[text_source('更正：新表于2027年3月12日前提交')],title='申请更正及补充通知',
            source_label='学院通知',source_url='https://school.example.edu.cn/info/one.htm',
            external_key=key,published_at='2026-11-02',observed_at=200)
    assert changed['notice_id']==old['notice_id'] and changed['updated']
    result=c.get('/api/notices/'+old['notice_id']).json()
    assert result['title']=='申请更正及补充通知' and result['published_at']=='2026-11-02'
    assert result['source_label']=='学院通知' and len(result['sources'])==2
    assert sum(bool(s['active']) for s in result['sources'])==1
    assert result['pending_intake_updates']==1


def test_runtime_audit_is_admin_only_and_never_exposes_configuration_values(env):
    from types import SimpleNamespace
    user=account(env);admin=account(env,'system-auditor',role='admin')
    assert user.get('/api/admin/runtime').status_code==403
    env[1].ai_api_key='synthetic-secret-never-public'
    env[1].aliyun_access_key_secret='another-synthetic-secret'
    env[0].state.worker_tasks={'sources':SimpleNamespace(done=lambda:False),
        'notice_analysis':SimpleNamespace(done=lambda:True,cancelled=lambda:False,exception=lambda:ValueError('private failure contents'))}
    result=admin.get('/api/admin/runtime');assert result.status_code==200,result.text
    value=result.json();assert value['workers']=={'sources':'running','notice_analysis':'failed'}
    assert value['database']=='readable' and value['configuration']['model'] is True
    assert value['external_delivery_verified'] is False
    assert 'synthetic-secret' not in result.text and 'private failure contents' not in result.text


def test_automatic_attachments_include_existing_spreadsheet_and_text_parsers():
    from app.notice_intake import read_notice_materials
    base='https://school.example.edu.cn'
    root=text_source('通知要求填写附件申请表');urls=[base+'/申请表.xlsx',base+'/材料清单.csv',base+'/说明.txt']
    root['origin']={'url':base+'/info/notice.htm','attachments':urls}
    async def reader(url):
        source=text_source('合成附件内容：'+url)
        source.update(kind='xlsx' if url.endswith('.xlsx') else 'csv' if url.endswith('.csv') else 'text')
        source['origin']={'url':url,'attachments':[]}
        return source,'合成附件'
    result=asyncio.run(read_notice_materials(root,read=reader))
    assert len(result)==4 and result[0]['origin']['received_attachments']==urls
    assert all(s['origin']['relationship']=='attachment' for s in result[1:])


def test_related_materials_fit_the_actual_review_source_budget(monkeypatch):
    from app import notice_network
    base='https://school.example.edu.cn';root=text_source('主通知正文','地理信息实验项目申请通知')
    root['origin']={'url':base+'/info/root.htm','attachments':[]}
    entries=[{'url':base+'/info/'+str(i)+'.htm','title':'地理信息实验项目申请补充通知','published_at':None} for i in (1,2)]
    async def reader(url):
        source=text_source('关联通知正文 '+url,'地理信息实验项目申请补充通知');source['origin']={'url':url,'attachments':[]}
        return source,source['name']
    async def attachments(source,read):
        if source['origin']['url']!=root['origin']['url']:return [source]
        extras=[]
        for i in range(4):
            item=text_source('合成主文附件'+str(i));item['kind']='docx';extras.append(item)
        return [source,*extras]
    monkeypatch.setattr(notice_network,'read_notice_materials',attachments)
    results=asyncio.run(notice_network.read_network(root,{'url':base+'/notices/','article_path_prefix':'/info/'},entries,read=reader))
    assert len(results)==6 and notice_network.within_budget(results)
    assert results[0]['origin']['related_search']['errors']
    assert not notice_network.within_budget([*results,text_source('第七份不能交给只有六份范围的复核器')])


def test_review_schema_and_per_source_reference_contract_forbid_quote_strings():
    from app.notice_semantics import Review,prepare
    sources=[text_source('申请表于2027年3月12日前提交。','主文'),text_source('补充说明：原申请表仍然有效。','补充')]
    _,refs,system,content=prepare({},sources,{}, {'tasks':[],'facts':{}})
    value=json.loads(content)
    assert value['coverage_contract']['source_indices']==[0,1]
    assert value['sources'][0]['allowed_evidence_refs']==['R000001']
    assert value['sources'][1]['allowed_evidence_refs']==['R000002']
    assert Review.model_json_schema()['$defs']['SourceCheck']['properties']['evidence_refs']['items']['pattern']=='^R[0-9]{6}$'
    raw={'checked_task_indices':[],'issues':[],'source_checks':[{'source_index':0,'coverage':'background',
        'requirements_summary':'该份材料只是背景信息，无个人步骤。','evidence_refs':['R000001','第 1 段：申请表于2027年3月12日前提交。']}]}
    with pytest.raises(ValueError):Review.model_validate(raw)


def test_unselected_source_revision_is_system_tracking_while_its_analysis_is_queued(env):
    c=account(env);nid,sid,uid=incoming(env,c);db=env[0].state.db
    with db.connect(write=True) as conn:
        receipt=conn.execute('SELECT id FROM notice_ingest_receipts WHERE notice_id=?',(nid,)).fetchone()[0]
        conn.execute('INSERT INTO notice_ingest_updates(id,notice_id,receipt_id,previous_source_ids,new_source_ids,created_at) VALUES(?,?,?,?,?,?)',
            (ident(),nid,receipt,'[]','[]',int(time.time())))
    permit(c)
    record=next(n for n in c.get('/api/notices').json() if n['id']==nid)
    assert record['pending_intake_updates']==1 and record['automation_state']=='queued'
    assert record['intent']=='tracking' and c.get('/api/tasks').json()==[]


def test_metadata_only_corrections_are_versioned_without_duplicate_channel_oscillation(env):
    c=account(env);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    def receive(key,title,date,at,url):
        with db.connect(write=True) as conn:
            return ingest_notice(conn,uid,title=title,sources=[text_source('学校发布的同一则公开通知原文。')],
                source_url=url,external_key=key,published_at=date,observed_at=at)
    url='https://school.example.edu.cn/info/a.htm'
    first=receive('website:a','原题名','2026-09-01',100,url)
    corrected=receive('website:a','更正后的完整题名','2026-11-02',200,url)
    assert corrected['updated'] and corrected['metadata_changed'] and corrected['notice_id']==first['notice_id']
    replay=receive('website:a','原题名','2026-09-01',150,url)
    assert replay['stale']
    again=receive('website:a','更正后的完整题名','2026-11-02',250,url)
    assert again['duplicate'] and not again['updated']
    second=receive('website:b','转发渠道题名','2026-11-02',300,'https://school.example.edu.cn/info/b.htm')
    assert second['notice_id']==first['notice_id']
    receive('website:b','转发渠道题名','2026-11-02',400,'https://school.example.edu.cn/info/b.htm')
    result=c.get('/api/notices/'+first['notice_id']).json()
    assert result['title']=='更正后的完整题名' and result['version']==2 and len(result['sources'])==1
    assert result['pending_intake_updates']==1


def test_automation_drains_finished_work_without_sleeping_between_ready_jobs(env,monkeypatch):
    calls=[];sleeps=[];results=[{'state':'succeeded'},{'state':'failed'},None]
    async def threadpool(*args):
        calls.append(True);return results.pop(0)
    async def idle(seconds):
        sleeps.append(seconds)
        assert len(calls)==3  # No fixed wait after either completed result.
        raise asyncio.CancelledError
    monkeypatch.setattr(notice_automation,'run_in_threadpool',threadpool)
    monkeypatch.setattr(notice_automation.asyncio,'sleep',idle)
    with pytest.raises(asyncio.CancelledError):asyncio.run(notice_automation.run_worker(env[0],env[0].state.db,env[1]))
    assert sleeps==[notice_automation.POLL_SECONDS]


def test_restricted_old_article_does_not_back_off_successful_index_discovery(env,monkeypatch):
    from fastapi import HTTPException
    from app import source_sync
    from tests.test_source_subscriptions import website,enable
    c=account(env);sid=website(c);enable(c,sid)
    base='https://school.example.edu.cn'
    async def index(config):return [{'url':base+'/info/public.htm','title':'公开通知','published_at':None},
        {'url':base+'/info/login.htm','title':'历史内部通知','published_at':None}]
    async def read(url):
        if url.endswith('login.htm'):raise HTTPException(422,'需要学校登录，不能冒充读到正文')
        source=text_source('这是一则能够公开读取的完整通知。');source['origin']={'url':url,'attachments':[]}
        return source,'公开通知'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    for _ in range(3):
        result=asyncio.run(source_sync.sync_source(env[0].state.db,sid,force=True))
        assert result['error'] and '登录' in result['error']
        assert result['next_poll']-result['checked_at']<=result['config']['interval_minutes']*60+3
    assert len(c.get('/api/notices').json())==1


def entry_draft(day='2020-09-02'):
    quote=day+' 17:00报名截止。'
    return {'applicability':'matches_known','quality':{'status':'passed'},
        'tasks':[{'scope':'personal','title':'完成比赛注册报名','due_date':day,'due_time':'17:00',
            'evidence':[{'quote':quote}],'deadline_evidence':[{'quote':quote}]},
            {'scope':'personal','title':'查询结果或向组委会咨询'}],
        'plans':{'0':{'action_kind':'optional','execution_mode':'submission'},
            '1':{'action_kind':'optional','execution_mode':'custom'}}}


def test_past_entry_window_does_not_stay_a_new_opportunity_because_consultation_has_no_deadline():
    from app.proactive_policy import assess
    d=entry_draft();n={'title':'第三届合成比赛','draft':d}
    result=assess(n,current_draft=True)
    assert result['tracking']['state']=='entry_closed' and not result['recommended'] and result['delivery']=='silent'
    assert result['tracking']['entry_deadlines'][0]['evidence']
    assert result['tracking']['unknown_actions'] and '不据此宣称整件事已结束' in result['tracking']['reason']
    assert n['draft']==d


@pytest.mark.parametrize('counterexample',['future','unknown_alternative','mandatory','unsupported_quote','unchecked'])
def test_entry_retirement_requires_every_relevant_boundary_and_optional_personal_work(counterexample):
    from app.proactive_policy import assess
    d=entry_draft()
    if counterexample=='future':d=entry_draft('2099-09-02')
    elif counterexample=='unknown_alternative':
        d['tasks'].append({'scope':'personal','title':'完成补充报名','evidence':[{'quote':'另设补充报名，时间待公布。'}]})
        d['plans']['2']={'action_kind':'optional','execution_mode':'submission'}
    elif counterexample=='mandatory':d['plans']['1']['action_kind']='required'
    elif counterexample=='unsupported_quote':d['tasks'][0]['deadline_evidence']=[{'quote':'9月2日报名截止，年份未说明。'}]
    else:d['quality']['status']='needs_review'
    assert assess({'title':'合成机会','draft':d},current_draft=True)['tracking']['state']!='entry_closed'


def test_closed_entry_can_be_restored_and_never_hides_chosen_personal_work(env):
    from app.notice_automation import mark_profile
    from app.models import TaskData
    c=account(env);n=notice(c);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET status='draft',draft_version=version,draft=? WHERE id=?",(dumps(entry_draft()),n['id']))
        mark_profile(conn,n['id'],uid,n['version'],conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0])
    record=c.get('/api/notices').json()[0]
    assert record['intent']=='closed' and not record['recommended'] and record['tracking']['state']=='entry_closed'
    response=c.put('/api/proactive/notices/'+n['id']+'/feedback',json={'notice_version':n['version'],'version':0,'mode':'include','note':'本人已报名，仍需查询结果'})
    assert response.status_code==200,response.text
    restored=c.get('/api/notices').json()[0];assert restored['recommended'] and restored['tracking']['state']=='entry_closed'
    assert c.put('/api/proactive/notices/'+n['id']+'/feedback',json={'notice_version':n['version'],'version':1,'mode':'auto'}).status_code==200
    now=int(time.time())
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO tasks(id,user_id,notice_id,data,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (ident(),uid,n['id'],dumps(TaskData(title='跟进本人已经提交的作品').model_dump()),'pending',now,now))
    chosen=c.get('/api/notices').json()[0]
    assert chosen['recommended'] and chosen['intent']=='act'
    assert c.get('/api/tasks').json()[0]['status']=='pending'
