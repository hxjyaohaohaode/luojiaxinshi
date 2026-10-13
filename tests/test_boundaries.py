from datetime import datetime, timedelta, timezone
import io
import json
import os
import sqlite3
import time

from fastapi.testclient import TestClient
import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app import ai
from app.backups import daily_backup
from app.config import Settings
from app.documents import file_source
from app.main import create_app
from app.models import TaskData
from test_workflow import env, account, notice, manual, confirm, task, raw_ai, ORIGIN


def test_public_illustration_cache_does_not_cache_private_data(env):
    c=account(env)
    asset=c.get('/static/assets/luojia-messenger-welcome.png')
    assert asset.status_code==200 and asset.content.startswith(b'\x89PNG')
    assert asset.headers['cache-control']=='public, max-age=86400'
    assert c.get('/api/tasks').headers['cache-control']=='no-store'
    assert c.get('/').headers['cache-control']=='no-store'


def test_real_pdf_text_and_page_locator():
    writer=PdfWriter()
    page=writer.add_blank_page(600,800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 50 700 Td (Submit the application by 2027-10-20.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO();writer.write(result)
    parsed=file_source('notice.pdf',result.getvalue())
    assert parsed['status']=='ok'
    assert parsed['sections'][0]['locator']=='第 1 页'
    assert '2027-10-20' in parsed['sections'][0]['text']


def test_provider_contract_and_usage_without_live_credentials(env,monkeypatch):
    c=account(env);n=notice(c);cfg=env[1];cfg.ai_api_key='FAKE-TEST-KEY'
    original=httpx.Client
    seen=[]
    def handler(request):
        payload=json.loads(request.content);seen.append(payload)
        assert request.url.path.endswith('/chat/completions')
        assert request.headers['authorization']=='Bearer FAKE-TEST-KEY'
        assert payload['model']=='mimo-v2.6-pro'
        assert payload['response_format']['type']=='json_object'
        assert payload['thinking']=={'type':'disabled'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw_ai(n),ensure_ascii=False)}}],'usage':{'prompt_tokens':120,'completion_tokens':80}})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    draft,usage=ai.generate(cfg,n,n['sources'],{'college':'测试学院'})
    assert draft['tasks'][0]['origin']=='ai' and usage['input_tokens']==120
    assert len(seen)==1
    assert 'FAKE-TEST-KEY' not in json.dumps(seen)


@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_provider_failure_does_not_leak_response_or_retry(env,monkeypatch,status):
    c=account(env);n=notice(c);env[1].ai_api_key='FAKE-KEY'
    original=httpx.Client;calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(status,json={'error':'raw provider secret should never appear'})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ai.AIError) as e:ai.generate(env[1],n,n['sources'],{})
    assert 'raw provider secret' not in str(e.value) and len(calls)==1


def test_provider_truncated_json_rejected(env,monkeypatch):
    c=account(env);n=notice(c);env[1].ai_api_key='FAKE-KEY'
    original=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]})),**kw))
    with pytest.raises(ai.AIError,match='未完整'):ai.generate(env[1],n,n['sources'],{})


def test_stale_ai_result_never_overwrites_new_sources(env,monkeypatch):
    c=account(env);n=notice(c);env[1].ai_api_key='FAKE-KEY'
    def changed(settings,record,sources,profile):
        r=c.post(f"/api/notices/{n['id']}/supplement",data={'version':1,'body':'补充：原文作废，请核实。'})
        assert r.status_code==200
        return ai.validate_extraction(raw_ai(n),sources,None),{'input_tokens':1,'output_tokens':2}
    monkeypatch.setattr(ai,'generate',changed)
    r=c.post(f"/api/notices/{n['id']}/generate",json={'version':1,'allow_external_processing':True})
    assert r.status_code==409
    current=c.get(f"/api/notices/{n['id']}").json()
    assert current['draft'] is None and len(current['sources'])==2
    assert current['tasks']==[]
    assert current['calls'][0]['status']=='discarded'


def test_completed_state_change_still_works_after_new_missing_material(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n)
    c.post(f"/api/notices/{n['id']}/materials",json={'version':n['version'],'complete':False})
    r=c.put('/api/tasks/'+tid,json={'version':1,'data':task(n),'status':'done','reason':'本人已提交'})
    assert r.status_code==200
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:2}}).status_code==422


def test_confirm_validation_rolls_back_whole_transaction(env):
    c=account(env);n=manual(c,notice(c))
    payload={'version':n['version'],'reviewed':True,'tasks':[task(n),task(n,title='不合法原文',evidence=[{'source_id':'fake','locator':'第 1 段','quote':'伪造'}])]}
    assert c.post(f"/api/notices/{n['id']}/confirm",json=payload).status_code==422
    assert c.get('/api/tasks').json()==[]


def test_inactive_material_evidence_retained(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n)
    sid=n['sources'][0]['id']
    r=c.post(f"/api/notices/{n['id']}/sources/{sid}/review",json={'version':n['version'],'action':'archive','reason':'已有正式更正材料'})
    assert r.status_code==200 and r.json()['sources'][0]['active']==0
    assert r.json()['sources'][0]['sections']
    assert len(c.get('/api/tasks').json())==1


def test_backup_rotation_and_private_snapshots(env):
    c=account(env);notice(c)
    folder=env[1].data_dir/'backups';folder.mkdir()
    old=folder/'auto-2000-01-01.sqlite3';old.write_bytes(b'old')
    os.utime(old,(time.time()-9*86400,time.time()-9*86400))
    keep=folder/'unmanaged.txt';keep.write_text('keep')
    daily_backup(env[0].state.db,env[1])
    assert not old.exists() and keep.exists()
    snapshots=list(folder.glob('auto-*.sqlite3'));assert len(snapshots)==1
    daily_backup(env[0].state.db,env[1]);assert len(list(folder.glob('auto-*.sqlite3')))==1
    with sqlite3.connect(snapshots[0]) as conn:
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0


def test_restart_persists_accounts_sources_and_tasks(env):
    c=account(env);n=manual(c,notice(c));confirm(c,n)
    restarted=TestClient(create_app(env[1]),base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    restarted.cookies.update(c.cookies)
    assert restarted.get('/api/tasks').json()[0]['data']['title']=='提交申请表'
    assert restarted.get('/api/notices/'+n['id']).json()['sources'][0]['sections']


def test_no_date_task_can_use_explicit_personal_plan(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n,task(n,due_date=None,due_time=None,deadline_confirmed=False,
        planned_at='2027-10-18T10:00:00+08:00',reminder_at='2027-10-18T09:00:00+08:00'))
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}}).status_code==200


def test_production_refuses_non_https_origin(monkeypatch,tmp_path):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('APP_ORIGIN','http://campus.example')
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    with pytest.raises(ValueError,match='HTTPS'):Settings.from_env()
