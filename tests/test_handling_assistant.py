"""Actual API/SQLite handling loop; model transport is isolated and deterministic."""
from datetime import datetime, timedelta, timezone
import io
import json
import uuid
import zipfile

import httpx
import pytest

from app import handling_assistant
from test_workflow import env, account, notice, manual, confirm


def setup(env, monkeypatch, *, provider_error=False, invented_ref=False, change_profile=False):
    c=account(env); n=manual(c,notice(c)); tid=confirm(c,n)
    current=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    cfg=env[1];cfg.ai_api_key='synthetic-only'
    original=httpx.Client;seen=[]

    def provider(request):
        payload=json.loads(request.content);seen.append(payload)
        if provider_error:return httpx.Response(429,json={'error':'PRIVATE_PROVIDER_DETAIL'})
        data=json.loads(payload['messages'][1]['content'])
        assert 'notes' not in data['task'] and 'PRIVATE_PHONE' not in json.dumps(data)
        if change_profile:
            with env[0].state.db.connect(write=True) as conn:
                conn.execute('UPDATE users SET profile=?',(json.dumps({'school':'changed'}),))
        ref=data['sources'][0]['sections'][0]['ref']
        result={'title':'申请表填写准备','body':'姓名：【待填写：姓名】\n请按学院原申请表填写，并在规定时间交至学院办公室。',
                'missing_fields':['姓名'],'evidence_refs':['R999999' if invented_ref else ref]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}],
                                        'usage':{'prompt_tokens':110,'completion_tokens':60}})

    monkeypatch.setattr(handling_assistant.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    payload={'task_version':current['version'],'workflow_version':current['workflow']['version'],
             'request_id':uuid.uuid4().hex,'purpose':'material','requirement':'申请表',
             'personal_context':'正在准备申请材料','allow_external_processing':True}
    return c,n,current,payload,seen


def test_preparation_to_file_submission_feedback_and_followup_is_one_persisted_loop(env,monkeypatch):
    c,n,t,payload,seen=setup(env,monkeypatch);tid=t['id'];path='/api/tasks/'+tid
    response=c.post(path+'/assistance',json=payload)
    assert response.status_code==200,response.text
    draft=response.json()
    assert draft['authority']=='preparation_draft' and draft['missing_fields']==['姓名']
    assert draft['evidence'][0]['source_id']==n['sources'][0]['id']
    assert c.get(path+'/assistance').json()==draft
    assert c.post(path+'/assistance',json=payload).json()==draft and len(seen)==1
    assert c.get(path+'/materials').json()['materials']==[]  # AI output never silently becomes a submitted file.
    request={'task_version':draft['task_version'],'notice_version':draft['notice_version'],'workflow_version':draft['workflow_version'],
             'requirement':'申请表','request_id':uuid.uuid4().hex}
    upload=c.post(path+'/materials',data=request,files={'file':('本人准备草稿.txt',draft['body'].encode(),'text/plain')})
    assert upload.status_code==200,upload.text
    material=upload.json()['materials'][0]
    package=c.get(path+'/materials/package')
    assert package.status_code==200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert any(name.endswith('.txt') for name in archive.namelist())
    now=datetime.now(timezone.utc).replace(microsecond=0)
    followup=(now+timedelta(days=2)).isoformat()
    workflow={**t['workflow']['data'],'next_step':'查询学院实际受理反馈','followup_at':followup}
    submission={'request_id':uuid.uuid4().hex,'channel':'学院办公室（自动化联调记录）','submitted_at':(now-timedelta(minutes=1)).isoformat(),
                'receipt':'合成提交凭证 SYNTHETIC-01','confirmed':True,
                'files':[{'material_id':material['id'],'version':1}]}
    body={'version':t['workflow']['version'],'task_version':t['version'],'data':workflow,'submission':submission}
    sent=c.put(path+'/workflow',json=body)
    assert sent.status_code==200,sent.text
    current=sent.json()
    assert current['status']=='pending' and current['workflow']['data']['stage']=='submitted'
    assert current['workflow']['data']['followup_at']==followup
    record=c.get(path+'/materials').json()['submissions'][0]
    assert record['data']['authority']=='self_reported' and record['data']['files'][0]['version']==1
    assert c.put(path+'/workflow',json=body).status_code==200
    assert len(c.get(path+'/materials').json()['submissions'])==1
    accepted=c.put(path+'/workflow',json={'version':current['workflow']['version'],'task_version':current['version'],
        'data':{**current['workflow']['data'],'stage':'accepted','outcome':'合成联调反馈：已收到受理回执 SYNTHETIC-02'},'complete':True})
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['status']=='done'
    assert c.get(path+'/materials').json()['materials'][0]['versions'][0]['sha256']==material['versions'][0]['sha256']


@pytest.mark.parametrize('options', [{'provider_error':True},{'invented_ref':True}])
def test_failed_preparation_never_resends_or_creates_file(env,monkeypatch,options):
    c,n,t,payload,seen=setup(env,monkeypatch,**options);path='/api/tasks/'+t['id']
    r=c.post(path+'/assistance',json=payload)
    assert r.status_code==502 and 'PRIVATE_PROVIDER_DETAIL' not in r.text
    assert c.post(path+'/assistance',json=payload).status_code==409 and len(seen)==1
    assert c.get(path+'/assistance').json()['status']=='empty'
    assert c.get(path+'/materials').json()['materials']==[]
    assert c.get(path+'/workflow').json()['task']['workflow']['data']['stage']=='preparing'


def test_changed_profile_discards_preparation_and_accounts_for_used_request(env,monkeypatch):
    c,n,t,payload,seen=setup(env,monkeypatch,change_profile=True);path='/api/tasks/'+t['id']
    r=c.post(path+'/assistance',json=payload)
    assert r.status_code==409 and len(seen)==1
    assert c.get(path+'/assistance').json()['status']=='empty'
    run=c.get('/api/executions').json()['items'][0]
    assert run['status']=='discarded' and run['stop_reason']=='context_changed'
    with env[0].state.db.connect() as conn:
        row=conn.execute('SELECT status FROM handling_assistance').fetchone()
        assert row['status']=='discarded'


def test_consent_ownership_and_stale_revision_reject_before_model_request(env,monkeypatch):
    c,n,t,payload,seen=setup(env,monkeypatch);path='/api/tasks/'+t['id']
    assert c.post(path+'/assistance',json={**payload,'allow_external_processing':False}).status_code==422
    assert c.post(path+'/assistance',json={**payload,'task_version':99}).status_code==409
    assert c.post(path+'/assistance',json={**payload,'workflow_version':99}).status_code==409
    assert c.post(path+'/assistance',json={**payload,'requirement':'虚构材料'}).status_code==422
    other=account(env,'bob')
    assert other.get(path+'/assistance').status_code==404
    assert other.post(path+'/assistance',json=payload).status_code==404
    assert seen==[]


def test_draft_upload_checks_notice_and_workflow_revisions(env,monkeypatch):
    c,n,t,payload,seen=setup(env,monkeypatch);path='/api/tasks/'+t['id']
    fields={'task_version':t['version'],'notice_version':n['version']+99,'workflow_version':0,
            'requirement':'申请表','request_id':uuid.uuid4().hex}
    r=c.post(path+'/materials',data=fields,files={'file':('草稿.txt',b'draft','text/plain')})
    assert r.status_code==409
    fields.update(notice_version=n['version'],workflow_version=99,request_id=uuid.uuid4().hex)
    assert c.post(path+'/materials',data=fields,files={'file':('草稿.txt',b'draft','text/plain')}).status_code==409
    assert c.get(path+'/materials').json()['materials']==[] and seen==[]

