from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

from fastapi.testclient import TestClient
from icalendar import Calendar
import pytest
from pypdf import PdfWriter

from app import ai
from app.config import ROOT, Settings
from app.db import Database
from app.documents import file_source
from app.main import create_app
from app.models import TaskData
from app.security import new_invite

ORIGIN='http://127.0.0.1:8765'
TEXT='测试通知：本科生须于2027年10月20日17:00前提交申请表至学院办公室。\n请本人核对资格并准备申请表。'
PASSWORD='Test-Only-Password-2026'


@pytest.fixture
def env(tmp_path):
    cfg=Settings(tmp_path/'data',origin=ORIGIN)
    app=create_app(cfg)
    return app,cfg


def account(env,name='alice',role='user'):
    app,cfg=env
    c=TestClient(app,base_url=ORIGIN)
    c.headers.update({'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    token=new_invite(app.state.db,role)
    r=c.post('/api/auth/register',json={'invite':token,'username':name,'password':PASSWORD,'display_name':name})
    assert r.status_code==200,r.text
    c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf']
    return c


def notice(c,text=TEXT,complete=True,files=None):
    r=c.post('/api/notices',data={'title':'自动化测试通知','body':text,'source_label':'测试夹具','materials_complete':str(complete).lower()},files=files)
    assert r.status_code==200,r.text
    return r.json()


def manual(c,n):
    r=c.post(f"/api/notices/{n['id']}/manual",json={'version':n['version']})
    assert r.status_code==200,r.text
    return r.json()


def task(n,**overrides):
    base=TaskData(title='提交申请表',due_date='2027-10-20',due_time='17:00',deadline_confirmed=True,
                  deadline_text='2027年10月20日17:00前',materials=['申请表'],notes='保留我的备注').model_dump()
    base.update(overrides)
    return base


def confirm(c,n,data=None,**kwargs):
    r=c.post(f"/api/notices/{n['id']}/confirm",json={'version':n['version'],'reviewed':True,'tasks':[data or task(n)],**kwargs})
    assert r.status_code==200,r.text
    return r.json()['task_ids'][0]


def raw_ai(n):
    s=n['sources'][0]
    e={'source_id':s['id'],'locator':s['sections'][0]['locator'],'quote':s['sections'][0]['text']}
    d=task(n,origin='ai',evidence=[e],deadline_evidence=[e],deadline_confirmed=False)
    return {'title':'测试提取','summary':'提取测试','applicability':'needs_review','applicability_reason':'身份待核实',
            'facts':{k:{'value':'','evidence':[]} for k in ai.FACT_KEYS},'tasks':[d],'warnings':[]}


def test_health_and_authentication(env):
    app,_=env
    c=TestClient(app,base_url=ORIGIN)
    assert c.get('/api/health').json()['status']=='ok'
    assert c.get('/api/tasks').status_code==401
    a=account(env)
    headers=a.get('/').headers
    assert "frame-ancestors 'none'" in headers['content-security-policy']
    assert headers['x-content-type-options']=='nosniff'
    assert a.get('/api/session').json()['ai']=={'configured':False,'model':'mimo-v2.6-pro'}


def test_invite_single_use_and_password_policy(env):
    app,_=env
    c=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    token=new_invite(app.state.db)
    body={'invite':token,'username':'alice','password':'short','display_name':'A'}
    assert c.post('/api/auth/register',json=body).status_code==422
    body['password']=PASSWORD
    r=c.post('/api/auth/register',json=body)
    assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    body['username']='bob'
    assert c.post('/api/auth/register',json=body).status_code==400


def test_csrf_origin_and_host_checks(env):
    c=account(env)
    assert c.put('/api/profile',json={},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.put('/api/profile',json={},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get('/api/tasks',headers={'Host':'evil.example'}).status_code==400
    assert c.post('/api/auth/login',json={'username':'alice','password':PASSWORD},headers={'Origin':'https://evil.example'}).status_code==403


def test_account_and_attachment_isolation_even_admin(env):
    a,b=account(env),account(env,'admin','admin')
    n=notice(a,files=[('files',('private.txt',b'private attachment','text/plain'))])
    d=manual(a,n)
    tid=confirm(a,d)
    sid=next(s['id'] for s in n['sources'] if s['kind']=='txt')
    for path in [f"/notices/{n['id']}",f"/notices/{n['id']}/history",f"/notices/{n['id']}/sources/{sid}/download"]:
        assert b.get('/api'+path).status_code==404
    assert b.put('/api/tasks/'+tid,json={'version':1,'data':task(n),'status':'done','reason':'x'}).status_code==404
    assert b.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}}).status_code==404
    assert b.get('/api/tasks').json()==[]


def test_duplicate_notice_explicit_override(env):
    c=account(env)
    n=notice(c)
    payload={'title':'另一个学期','body':TEXT,'materials_complete':'true'}
    r=c.post('/api/notices',data=payload)
    assert r.status_code==409 and r.json()['detail']['duplicate_id']==n['id']
    payload['allow_duplicate']='true'
    assert c.post('/api/notices',data=payload).status_code==200


def test_manual_workflow_idempotency_and_stale_writes(env):
    c=account(env)
    n=manual(c,notice(c))
    tid=confirm(c,n)
    assert confirm(c,n)==tid
    assert len(c.get('/api/tasks').json())==1
    changed=task(n,notes='新备注')
    update={'version':1,'data':changed,'status':'done','reason':'已自行提交'}
    assert c.put('/api/tasks/'+tid,json=update).status_code==200
    assert c.put('/api/tasks/'+tid,json=update).status_code==409
    current=c.get('/api/tasks').json()[0]
    assert current['status']=='done' and current['data']['notes']=='新备注'
    assert confirm(c,n)==tid
    assert c.get('/api/tasks').json()[0]['status']=='done'


def test_parallel_confirmation_creates_only_one_task(env):
    c=account(env)
    n=manual(c,notice(c))
    payload={'version':n['version'],'reviewed':True,'tasks':[task(n)]}
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:c.post(f"/api/notices/{n['id']}/confirm",json=payload),range(5)))
    assert all(r.status_code==200 for r in results)
    assert len(c.get('/api/tasks').json())==1


def test_supplement_stale_draft_and_revision_preserves_status_notes(env):
    c=account(env)
    n=manual(c,notice(c));tid=confirm(c,n)
    c.put('/api/tasks/'+tid,json={'version':1,'data':task(n),'status':'done','reason':'已经完成'})
    r=c.post(f"/api/notices/{n['id']}/supplement",data={'version':n['version'],'body':'补充通知：请保留提交回执。'})
    assert r.status_code==200,r.text
    newer=r.json()
    assert newer['draft'] is None and newer['tasks'][0]['status']=='done'
    assert c.post(f"/api/notices/{n['id']}/manual",json={'version':n['version']}).status_code==409
    d=manual(c,newer)
    tid2=confirm(c,d,task(d,title='补充核对回执',notes='不得覆盖旧备注'),replacements={0:tid},target_versions={tid:2})
    assert tid2==tid
    current=c.get('/api/tasks').json()[0]
    assert current['status']=='done' and current['data']['notes']=='保留我的备注'


def test_unconfigured_ai_honest_failure(env):
    c=account(env);n=notice(c)
    r=c.post(f"/api/notices/{n['id']}/generate",json={'version':n['version'],'allow_external_processing':True})
    assert r.status_code==503
    assert c.get('/api/tasks').json()==[]
    assert c.get(f"/api/notices/{n['id']}").json()['sources']


def test_ai_only_generates_draft_and_preserves_usage(env,monkeypatch):
    env[1].ai_api_key='test-not-a-real-key'
    c=account(env);n=notice(c)
    def mock(settings,record,sources,profile):
        return ai.validate_extraction(raw_ai(n),sources,None),{'input_tokens':100,'output_tokens':50}
    monkeypatch.setattr(ai,'generate',mock)
    r=c.post(f"/api/notices/{n['id']}/generate",json={'version':1,'allow_external_processing':True})
    assert r.status_code==200,r.text
    assert c.get('/api/tasks').json()==[]
    draft=r.json()
    assert draft['draft']['tasks'][0]['deadline_confirmed'] is False
    assert draft['calls'][0]['input_tokens']==100
    confirm(c,draft)


def test_ai_failure_is_retryable_and_no_false_success(env,monkeypatch):
    env[1].ai_api_key='test-not-a-real-key'
    c=account(env);n=notice(c)
    def fail(*args):raise ai.AIError('测试模型超时')
    monkeypatch.setattr(ai,'generate',fail)
    r=c.post(f"/api/notices/{n['id']}/generate",json={'version':1,'allow_external_processing':True})
    assert r.status_code==502
    result=c.get(f"/api/notices/{n['id']}").json()
    assert result['status']=='failed' and result['calls'][0]['status']=='failed'
    assert result['sources'] and result['tasks']==[]


def test_ai_evidence_rejects_fabricated_quote_and_source(env):
    c=account(env);n=notice(c);raw=raw_ai(n)
    raw['tasks'][0]['evidence'][0]['quote']='根本不存在的原句'
    with pytest.raises(ValueError):ai.validate_extraction(raw,n['sources'],None)


def test_missing_year_and_invented_time_are_not_inferred(env):
    c=account(env);n=notice(c,'请于10月20日提交。')
    raw=raw_ai(n)
    result=ai.validate_extraction(raw,n['sources'],None)
    assert result['tasks'][0]['due_date'] is None
    n2=notice(c,'请于2027年10月20日提交。')
    result=ai.validate_extraction(raw_ai(n2),n2['sources'],None)
    assert result['tasks'][0]['due_date']=='2027-10-20'
    assert result['tasks'][0]['due_time'] is None


def test_relative_date_requires_original_publication(env):
    c=account(env);n=notice(c,'请在明天提交申请表。')
    raw=raw_ai(n)
    assert ai.validate_extraction(raw,n['sources'],None)['tasks'][0]['due_date'] is None
    assert ai.validate_extraction(raw,n['sources'],'2027-10-19T10:00:00+08:00')['tasks'][0]['due_date']=='2027-10-20'


def test_incomplete_materials_block_deadline_until_resolution(env):
    c=account(env);n=manual(c,notice(c,complete=False))
    payload={'version':n['version'],'reviewed':True,'tasks':[task(n)]}
    assert c.post(f"/api/notices/{n['id']}/confirm",json=payload).status_code==422
    tid=confirm(c,n,task(n,deadline_confirmed=False))
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}}).status_code==422


def test_ics_round_trip_timezone_all_day_and_injection(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n,task(n,title='提交,申请;材料\nBEGIN:VEVENT',reminder_at='2027-10-19T09:00:00+08:00'))
    response=c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}})
    assert response.status_code==200,response.text
    cal=Calendar.from_ical(response.content)
    events=cal.walk('VEVENT');assert len(events)==1
    assert events[0].decoded('DTSTART').hour==9 # 17:00 CST => 09:00 UTC
    assert len(events[0].walk('VALARM'))==1
    changed=task(n,due_time=None)
    c.put('/api/tasks/'+tid,json={'version':1,'data':changed,'status':'pending','reason':'原通知只有日期'})
    current=c.get('/api/tasks').json()[0];assert current['needs_calendar_sync']
    response=c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:2}})
    event=Calendar.from_ical(response.content).walk('VEVENT')[0]
    assert event['DTSTART'].params['VALUE']=='DATE'
    assert event.decoded('DTEND')-event.decoded('DTSTART')==timedelta(days=1)


def test_cancel_marks_calendar_dirty_and_exports_cancelled(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n)
    c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}})
    r=c.put('/api/tasks/'+tid,json={'version':1,'data':task(n),'status':'cancelled','reason':'本人取消'})
    assert r.json()['needs_calendar_sync']
    result=c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:2}})
    assert str(Calendar.from_ical(result.content).walk('VEVENT')[0]['STATUS'])=='CANCELLED'


def test_own_data_export_excludes_password_sessions_api_key(env):
    c=account(env);notice(c)
    result=c.get('/api/export')
    assert result.status_code==200 and len(result.json()['notices'])==1
    for secret in ['password','token_hash','csrf','AI_API_KEY','processing_token']:
        assert secret not in result.text


def test_delete_cascades_private_data(env):
    c=account(env);n=manual(c,notice(c,files=[('files',('a.txt',b'secret text','text/plain'))]));confirm(c,n)
    assert c.request('DELETE','/api/notices/'+n['id'],json={'version':n['version']}).status_code==200
    for table in ['notices','sources','tasks','audit','confirmations','ai_calls']:
        with env[0].state.db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


def test_password_rotation_revokes_other_sessions(env):
    c=account(env)
    other=TestClient(env[0],base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    assert other.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
    assert c.post('/api/auth/password',json={'old_password':PASSWORD,'new_password':'New-Strong-Password-2026'}).status_code==200
    assert other.get('/api/session').status_code==401
    assert c.get('/api/session').status_code==200


def test_login_rate_limit(env):
    c=account(env)
    for _ in range(10):
        assert c.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
    assert c.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==429


def test_upload_limits_and_no_silent_truncation(env):
    c=account(env)
    assert c.post('/api/notices',data={'title':'t','body':'文'*10001}).status_code==422
    assert c.post('/api/notices',data={'title':'t'},files=[('files',('a.txt',b'x'*(5*1024*1024+1),'text/plain'))]).status_code==422
    assert c.post('/api/notices',data={'title':'t'},files=[('files',(f'{i}.txt',b'text','text/plain')) for i in range(6)]).status_code==400
    assert c.post('/api/notices',data={'title':'t','source_url':'https://example.com'}).status_code==422


def test_failed_attachment_is_kept_and_visible(env):
    c=account(env);n=notice(c,files=[('files',('broken.pdf',b'not pdf','application/pdf'))])
    source=next(s for s in n['sources'] if s['kind']=='pdf')
    assert source['status']=='failed' and n['blockers']
    assert c.get(f"/api/notices/{n['id']}/sources/{source['id']}/download").content==b'not pdf'


def test_docx_parser_and_zip_bomb_guard():
    content=io.BytesIO()
    with zipfile.ZipFile(content,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>通知原文：提交申请表。</w:t></w:r></w:p></w:body></w:document>')
    parsed=file_source('safe.docx',content.getvalue())
    assert parsed['status']=='ok' and parsed['sections'][0]['locator']=='第 1 段'
    oversized=io.BytesIO()
    with zipfile.ZipFile(oversized,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml',b'x'*(26*1024*1024))
    assert file_source('large.docx',oversized.getvalue())['status']=='failed'


def test_pdf_encrypted_and_scanned_rejected():
    writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    data=io.BytesIO();writer.write(data)
    assert file_source('scan.pdf',data.getvalue())['status']=='failed'
    writer.encrypt('password');data=io.BytesIO();writer.write(data)
    assert '加密' in file_source('locked.pdf',data.getvalue())['warning']


def test_backup_integrity_and_restore(env,tmp_path):
    c=account(env);n=manual(c,notice(c));confirm(c,n)
    dest=tmp_path/'backup.sqlite3';env[0].state.db.backup(dest)
    with sqlite3.connect(dest) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
    target=tmp_path/'restored'
    result=subprocess.run([sys.executable,'manage.py','restore','--file',str(dest)],cwd=ROOT,capture_output=True,
                          env={**os.environ,'DATA_DIR':str(target),'APP_ORIGIN':ORIGIN,'APP_ENV':'local'})
    assert result.returncode==0,result.stderr
    restored=create_app(Settings(target,origin=ORIGIN))
    client=TestClient(restored,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    assert client.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
    assert client.get('/api/tasks').json()[0]['data']['title']=='提交申请表'
