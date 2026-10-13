"""Real database/API tests. Model responses below are explicit engineering fixtures."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import threading
import uuid

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app import chat_ai
from app.ai import AIError
from test_workflow import env,account,ORIGIN,PASSWORD


def conversation(c):
    r=c.post('/api/conversations',json={});assert r.status_code==200,r.text
    return r.json()


def material(c,chat,text='【工程夹具】请本人核对并准备报名表。'):
    r=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version'],'body':text,'label':'工程材料'})
    assert r.status_code==200,r.text
    return r.json()


def send(c,chat,content='要准备什么？',**overrides):
    data={'version':chat['version'],'content':content,'request_id':uuid.uuid4().hex,'allow_external_processing':True,**overrides}
    r=c.post('/api/conversations/'+chat['id']+'/messages',json=data)
    assert r.status_code==200,r.text
    return r.json(),data


def fixture_answer(settings,sources,messages,profile):
    s=sources[0]
    return {'answer':'【测试回复】先核对材料中的要求。','citations':[{'source_id':s['id'],'locator':s['sections'][0]['locator'],'quote':s['sections'][0]['text']}],'image_sources':[]},{'input_tokens':20,'output_tokens':10}


def test_public_registration_is_not_administrator_and_recovery_is_single_use(env):
    app,_=env;c=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    body={'username':'20269990001','display_name':'测试师生','password':PASSWORD,'accepted_terms':True,'account_kind':'student_id','campus_role':'student'}
    result=c.post('/api/auth/register',json=body);assert result.status_code==200,result.text
    code=result.json()['recovery_code'];session=c.get('/api/session').json()
    assert session['user']['role']=='user'
    assert session['user']['profile']['student_id']==body['username']
    c.headers['X-CSRF-Token']=session['csrf']
    assert c.post('/api/admin/invites').status_code==403
    assert c.post('/api/auth/register',json=body).status_code==409
    c.post('/api/auth/logout')
    reset={'username':body['username'],'password':'Another-Test-Password-2026','recovery_code':code}
    recovered=c.post('/api/auth/recover',json=reset);assert recovered.status_code==200
    assert recovered.json()['recovery_code']!=code
    assert c.post('/api/auth/recover',json=reset).status_code==400
    assert c.post('/api/auth/login',json={'username':body['username'],'password':PASSWORD}).status_code==401
    assert c.post('/api/auth/login',json={'username':body['username'],'password':reset['password']}).status_code==200
    with app.state.db.connect() as db:
        assert db.execute('SELECT code_hash FROM account_recovery').fetchone()[0]!=code


def test_registration_terms_phone_and_forged_admin(env):
    app,_=env;c=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    body={'username':'somebody','display_name':'X','password':PASSWORD}
    assert c.post('/api/auth/register',json=body).status_code==422
    body.update(accepted_terms=True,account_kind='phone')
    assert c.post('/api/auth/register',json=body).status_code==422
    body['username']='13800000000';body['role']='admin'
    assert c.post('/api/auth/register',json=body).status_code==422
    del body['role'];assert c.post('/api/auth/register',json=body).status_code==200


def test_unconfigured_reply_persists_question_and_idempotent_replay(env):
    c=account(env);chat=material(c,conversation(c));result,payload=send(c,chat)
    assert [m['role'] for m in result['messages']]==['user','assistant']
    assert result['messages'][-1]['status']=='failed'
    assert '未配置' in result['messages'][-1]['error']
    again=c.post('/api/conversations/'+chat['id']+'/messages',json=payload).json()
    assert len(again['messages'])==2
    assert c.get('/api/tasks').json()==[]


def test_multiturn_passes_only_this_conversation_and_promotes_originals(env,monkeypatch):
    c=account(env);env[1].ai_api_key='engineering-fixture';calls=[]
    def reply(*args):
        calls.append(args);return fixture_answer(*args)
    monkeypatch.setattr(chat_ai,'reply',reply)
    chat=material(c,conversation(c));first,_=send(c,chat);second,_=send(c,first,'地点还不明确，怎么办？')
    assert [m['role'] for m in calls[1][2]]==['user','assistant','user']
    assert second['messages'][-1]['citations'][0]['source_id']==chat['sources'][0]['id']
    promote={'version':second['version'],'title':'需要核对的工程通知','source_ids':[chat['sources'][0]['id']]}
    r=c.post('/api/conversations/'+chat['id']+'/promote',json=promote);assert r.status_code==200,r.text
    n=c.get('/api/notices/'+r.json()['notice_id']).json()
    assert n['sources'][0]['sections']==chat['sources'][0]['sections']
    assert '测试回复' not in json.dumps(n,ensure_ascii=False)
    assert n['draft'] is None and not n['materials_complete']
    repeat=c.post('/api/conversations/'+chat['id']+'/promote',json=promote).json()
    assert repeat['already_created'] and repeat['notice_id']==n['id']
    assert not c.get('/api/tasks').json()


def test_conversation_owner_isolation_for_all_paths(env):
    a=account(env);b=account(env,'bob');chat=material(a,conversation(a));cid=chat['id'];sid=chat['sources'][0]['id']
    requests=[('get','',None),('put','',{'version':chat['version'],'title':'steal'}),('delete','',{'version':chat['version']}),
              ('get',f'/sources/{sid}/download',None),('delete',f'/sources/{sid}',{'version':chat['version']}),
              ('post','/cancel',{'version':chat['version']}),('post','/promote',{'version':chat['version'],'title':'X','source_ids':[sid]}),
              ('post','/messages',{'version':chat['version'],'content':'X','request_id':'long-request-identifier'})]
    for method,suffix,payload in requests:
        r=b.request(method,'/api/conversations/'+cid+suffix,**({'json':payload} if payload else {}));assert r.status_code==404,r.text
    assert b.get('/api/edit-cache/chat:'+cid).status_code==404
    assert b.get('/api/conversations').json()==[]


def test_material_dedup_version_and_actual_image_validation(env):
    c=account(env);chat=material(c,conversation(c));same=material(c,chat)
    assert same['added_count']==0 and len(same['sources'])==1
    invalid=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']-1,'body':'新版正文'})
    assert invalid.status_code==409
    pic=io.BytesIO();Image.new('RGB',(16,16),(10,90,40)).save(pic,format='PNG')
    upload=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':('test.png',pic.getvalue(),'image/png')})
    assert upload.status_code==200,upload.text
    img=upload.json()['sources'][-1];assert img['status']=='review' and img['sections']==[]
    raw=c.get(f"/api/conversations/{chat['id']}/sources/{img['id']}/download?preview=true")
    assert raw.content==pic.getvalue() and raw.headers['content-type']=='image/png'
    bad=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':upload.json()['version']},files={'files':('bad.png',b'<script>bad</script>','image/png')})
    assert bad.status_code==200
    assert bad.json()['sources'][-1]['status']=='failed'
    bad_id=bad.json()['sources'][-1]['id']
    assert c.get(f"/api/conversations/{chat['id']}/sources/{bad_id}/download?preview=true").headers['content-disposition'].startswith('attachment')


def test_model_cancel_rejects_late_reply(env,monkeypatch):
    c=account(env);env[1].ai_api_key='engineering-fixture';chat=material(c,conversation(c));started=threading.Event();finish=threading.Event()
    def delayed(*args):
        started.set();assert finish.wait(10);return fixture_answer(*args)
    monkeypatch.setattr(chat_ai,'reply',delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(send,c,chat)
        try:
            assert started.wait(5)
            busy=c.get('/api/conversations/'+chat['id']).json();assert busy['processing']
            assert c.post('/api/conversations/'+chat['id']+'/sources',data={'version':busy['version'],'body':'不应写入'}).status_code==409
            stopped=c.post('/api/conversations/'+chat['id']+'/cancel',json={'version':busy['version']});assert stopped.status_code==200
        finally:
            finish.set()
        result,_=future.result()
    assert result['messages'][-1]['status']=='cancelled' and not result['messages'][-1]['content']


def test_retry_does_not_repeat_user_message_and_consent_is_required(env,monkeypatch):
    c=account(env);chat=material(c,conversation(c));failed,_=send(c,chat)
    env[1].ai_api_key='engineering-fixture';monkeypatch.setattr(chat_ai,'reply',fixture_answer)
    retry={'version':failed['version'],'content':'','request_id':uuid.uuid4().hex,'retry_message_id':failed['messages'][-1]['id']}
    assert c.post('/api/conversations/'+chat['id']+'/messages',json=retry).status_code==422
    retry['allow_external_processing']=True
    result=c.post('/api/conversations/'+chat['id']+'/messages',json=retry).json()
    assert len([m for m in result['messages'] if m['role']=='user'])==1
    assert result['messages'][-1]['status']=='complete'
    retry.update(version=result['version'],request_id=uuid.uuid4().hex)
    assert c.post('/api/conversations/'+chat['id']+'/messages',json=retry).status_code==409


def test_sources_catalog_is_private_and_does_not_claim_sync(env):
    a=account(env);b=account(env,'bob');body={'name':'工程测试公众号','platform':'wechat_public','followed':True,'semester':'测试学期'}
    sid=a.post('/api/source-catalog',json=body).json()['id']
    assert b.get('/api/source-catalog').json()==[]
    assert a.get('/api/source-catalog').json()[0]['data']=={**body,'institution':'','purpose':'','url':''}
    assert b.put('/api/source-catalog/'+sid,json={**body,'version':1}).status_code==404
    assert a.put('/api/source-catalog/'+sid,json={**body,'version':1,'url':'javascript:alert(1)'}).status_code==422
    assert a.put('/api/source-catalog/'+sid,json={**body,'version':1,'purpose':'跟进通知'}).status_code==200
    assert a.request('DELETE','/api/source-catalog/'+sid,json={'version':1}).status_code==409


def test_export_and_delete_contain_only_owned_conversation_data(env):
    c=account(env);chat=material(c,conversation(c));send(c,chat);c.put('/api/edit-cache/chat:'+chat['id'],json={'revision':0,'payload':{'content':'草稿'}})
    result=c.get('/api/export').json();assert len(result['conversations'])==1
    latest=c.get('/api/conversations/'+chat['id']).json()
    assert c.request('DELETE','/api/conversations/'+chat['id'],json={'version':latest['version']}).status_code==200
    assert c.get('/api/conversations').json()==[]
    with env[0].state.db.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM conversation_sources').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM conversation_messages').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM edit_caches WHERE cache_key LIKE 'chat:%'").fetchone()[0]==0


def test_chat_adapter_citations_and_contact_minimization(env,monkeypatch):
    import httpx
    c=account(env);chat=material(c,conversation(c));sources=chat['sources'];cfg=env[1];cfg.ai_api_key='engineering-fixture';seen=[]
    source=sources[0]
    answer={'answer':'请核对报名表。','citations':[{'source_id':source['id'],'locator':source['sections'][0]['locator'],'quote':source['sections'][0]['text']}],'image_sources':[]}
    def transport(request):
        seen.append(json.loads(request.content));return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]})
    client=httpx.Client
    monkeypatch.setattr(chat_ai.httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(transport),**kwargs))
    profile={'phone':'private-phone','wechat':'private-wechat','qq':'private-qq','student_id':'private-id','campus_role':'student'}
    result,_=chat_ai.reply(cfg,sources,[{'role':'user','content':'准备什么'}],profile)
    assert result['answer']
    assert 'private-' not in json.dumps(seen)
    answer['citations'][0]['quote']='杜撰的原文'
    with pytest.raises(AIError,match='引用未通过'):
        chat_ai.reply(cfg,sources,[{'role':'user','content':'准备什么'}],profile)
