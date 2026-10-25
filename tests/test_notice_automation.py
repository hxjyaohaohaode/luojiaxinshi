"""Background automation contracts with a fake generator; never calls a model."""
import json

from fastapi import HTTPException

from app import notice_automation
from app.documents import text_source
from app.notice_ingest import ingest_notice
from tests.test_workflow import env, account, manual, confirm, task
from tests.test_source_subscriptions import website, enable


def incoming(env,c,body='本科生报名通知，请核对资格',key='1'):
    sid=website(c);enable(c,sid)
    uid=c.get('/api/session').json()['user']['id']
    with env[0].state.db.connect(write=True) as conn:
        result=ingest_notice(conn,uid,title='收到的通知 '+key,sources=[text_source(body)],source_label='学院官网',
                             source_url='https://school.example.edu.cn/info/'+key+'.htm',
                             external_key='website:'+sid+':https://school.example.edu.cn/info/'+key+'.htm')
    return result['notice_id'],sid,uid


def permit(c,**changes):
    before=c.get('/api/notice-automation').json()
    r=c.put('/api/notice-automation',json={'enabled':True,'allow_external_processing':True,'daily_limit':10,'version':before['version'],**changes})
    assert r.status_code==200,r.text
    return r.json()


def generator(env,monkeypatch,calls,fail=False):
    def generate(nid,payload,current):
        calls.append((nid,payload.version,current['id']))
        assert payload.allow_external_processing is True
        if fail:raise HTTPException(502,'模拟模型失败；不自动重试')
        with env[0].state.db.connect(write=True) as conn:
            conn.execute("UPDATE notices SET status='draft',version=version+1,draft_version=version+1,draft=? WHERE id=? AND version=?",(json.dumps({'applicability':'matches_known','tasks':[]}),nid,payload.version))
            row=dict(conn.execute('SELECT * FROM notices WHERE id=?',(nid,)).fetchone())
            return row
    monkeypatch.setattr(env[0].state,'generate_notice',generate)


def test_disabled_by_default_explicit_model_consent_and_no_repeat_after_success(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c);calls=[];generator(env,monkeypatch,calls)
    assert c.get('/api/notice-automation').json()['enabled'] is False
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None
    assert not calls
    assert c.put('/api/notice-automation',json={'enabled':True}).status_code==422
    permit(c)
    result=notice_automation.run_once(env[0],env[0].state.db,env[1])
    assert result['state']=='succeeded' and len(calls)==1
    assert c.get('/api/tasks').json()==[]
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None
    assert len(calls)==1
    state=c.get('/api/notice-automation').json();job=state['jobs'][0]
    assert job['result_version']==job['input_version']+1
    assert state['used_today']==1


def test_background_job_uses_real_generate_workflow_with_only_provider_stubbed(env,monkeypatch):
    from app import ai
    from tests.test_workflow import raw_ai
    c=account(env);nid,sid,uid=incoming(env,c);env[1].ai_api_key='synthetic-provider-stub'
    before=c.get('/api/notices/'+nid).json();calls=[]
    def provider(settings,record,sources,profile):
        calls.append(record['id'])
        return raw_ai(before),{'input_tokens':10,'output_tokens':20}
    monkeypatch.setattr(ai,'generate',provider);permit(c)
    result=notice_automation.run_once(env[0],env[0].state.db,env[1])
    assert result['state']=='succeeded',result
    after=c.get('/api/notices/'+nid).json()
    assert calls==[nid] and after['status']=='draft' and after['version']==before['version']+1
    assert after['blockers'] and not after['materials_complete']
    assert c.get('/api/tasks').json()==[]
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT status FROM ai_calls WHERE notice_id=?',(nid,)).fetchone()[0]=='succeeded'


def test_failure_never_retries_without_user_and_other_accounts_cannot_retry(env,monkeypatch):
    c,other=account(env),account(env,'other');incoming(env,c);calls=[];generator(env,monkeypatch,calls,True);permit(c)
    result=notice_automation.run_once(env[0],env[0].state.db,env[1])
    assert result['state']=='failed'
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None and len(calls)==1
    assert other.post('/api/notice-automation/'+result['job_id']+'/retry').status_code==404
    assert other.get('/api/notice-automation').json()['jobs']==[]
    assert c.post('/api/notice-automation/'+result['job_id']+'/retry').status_code==200
    generator(env,monkeypatch,calls)
    assert notice_automation.run_once(env[0],env[0].state.db,env[1])['state']=='succeeded'
    assert len(calls)==2 and c.get('/api/notice-automation').json()['used_today']==2


def test_revoked_source_or_global_switch_stops_queued_jobs(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c);calls=[];generator(env,monkeypatch,calls);permit(c)
    with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE source_subscriptions SET enabled=0 WHERE source_id=?',(sid,))
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None and not calls
    assert c.get('/api/notice-automation').json()['jobs'][0]['state']=='cancelled'
    nid2,sid2,_=incoming(env,c,'另一份必须完成的通知','2')
    permit(c,enabled=False,allow_external_processing=False)
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None and not calls


def test_profile_change_requeues_unconfirmed_draft_and_blocks_old_confirmation(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c);calls=[];generator(env,monkeypatch,calls);permit(c)
    notice_automation.run_once(env[0],env[0].state.db,env[1])
    with env[0].state.db.connect(write=True) as conn:
        profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]);profile['college']='新学院'
        conn.execute('UPDATE users SET profile=? WHERE id=?',(json.dumps(profile),uid))
        assert notice_automation.detail(conn,nid,uid)['needs_profile_review']
        try:notice_automation.require_current_profile(conn,nid,uid)
        except HTTPException as exc:assert exc.status_code==409
        else:raise AssertionError('stale profile was accepted')
    assert notice_automation.run_once(env[0],env[0].state.db,env[1])['state']=='succeeded'
    with env[0].state.db.connect() as conn:assert not notice_automation.detail(conn,nid,uid)['needs_profile_review']
    assert len(calls)==2 and c.get('/api/tasks').json()==[]


def test_daily_cap_and_expired_running_job_do_not_make_extra_model_calls(env,monkeypatch):
    c=account(env);incoming(env,c,key='1');incoming(env,c,'第二则内容不同的通知',key='2');calls=[];generator(env,monkeypatch,calls);permit(c,daily_limit=1)
    assert notice_automation.run_once(env[0],env[0].state.db,env[1])['state']=='succeeded'
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None and len(calls)==1
    state=c.get('/api/notice-automation').json();assert state['counts']['queued']==1
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE notice_automation_jobs SET state='running',lease_until=1,attempts=1 WHERE state='queued'")
    notice_automation.run_once(env[0],env[0].state.db,env[1])
    assert c.get('/api/notice-automation').json()['counts']['failed']==1 and len(calls)==1


def test_new_source_version_drafts_without_changing_confirmed_personal_work(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c)
    notice=manual(c,c.get('/api/notices/'+nid).json())
    tid=confirm(c,notice,data=task(notice,title='核对报名资格',deadline_confirmed=False,due_date=None,due_time=None,deadline_text='',materials=[]))
    before=c.get('/api/tasks').json();calls=[];generator(env,monkeypatch,calls);permit(c)
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None
    with env[0].state.db.connect(write=True) as conn:
        updated=ingest_notice(conn,uid,title='来源更正',sources=[text_source('更正：报名时间调整，请核对新的截止日期')],
            external_key='website:'+sid+':https://school.example.edu.cn/info/1.htm',source_label='学院官网')
        assert updated['notice_id']==nid and updated['updated']
    assert notice_automation.run_once(env[0],env[0].state.db,env[1])['state']=='succeeded'
    after=c.get('/api/tasks').json()
    assert len(after)==1 and after[0]['id']==tid
    assert after[0]['data']==before[0]['data'] and after[0]['status']==before[0]['status']


def test_failed_real_status_is_not_retried_but_changed_profile_gets_new_job(env,monkeypatch):
    c=account(env);nid,sid,uid=incoming(env,c);calls=[];generator(env,monkeypatch,calls,True);permit(c)
    result=notice_automation.run_once(env[0],env[0].state.db,env[1])
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET status='failed' WHERE id=?",(nid,))
    assert notice_automation.run_once(env[0],env[0].state.db,env[1]) is None and len(calls)==1
    with env[0].state.db.connect(write=True) as conn:
        profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]);profile['college']='新的学院'
        conn.execute('UPDATE users SET profile=? WHERE id=?',(json.dumps(profile),uid))
    assert c.post('/api/notice-automation/'+result['job_id']+'/retry').status_code==409
    # The new job survives the 409 response instead of being rolled back.
    assert c.get('/api/notice-automation').json()['counts']['queued']==1
    generator(env,monkeypatch,calls)
    assert notice_automation.run_once(env[0],env[0].state.db,env[1])['state']=='succeeded'
    assert len(calls)==2
