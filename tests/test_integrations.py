"""Contract/security tests; synthetic platform events and HTTP fixtures, no real credentials."""
import json
import time
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app.integrations import PublisherClient,qq_key
from app.backups import restore_database
from app.db import Database
from test_workflow import env,account,ORIGIN


def configured(env):
    app,cfg=env;cfg.qq_bot_app_id='engineering-app';cfg.qq_bot_secret='engineering-secret'
    return TestClient(app,base_url=ORIGIN)


def event(client,cfg,content='测试通知',openid='synthetic-open-id',mid=None,extra=None,stamp=None,t='C2C_MESSAGE_CREATE'):
    payload={'op':0,'t':t,'d':{'author':{'user_openid':openid},'id':mid or uuid.uuid4().hex,'content':content,**(extra or {})}}
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode();stamp=stamp or str(int(time.time()))
    return client.post('/api/integrations/qq/webhook',content=raw,headers={'X-Bot-Appid':cfg.qq_bot_app_id,'X-Signature-Timestamp':stamp,'X-Signature-Ed25519':qq_key(cfg.qq_bot_secret).sign(stamp.encode()+raw).hex()})


def bind(c,external,cfg,openid='synthetic-open-id'):
    result=c.post('/api/integrations/qq/link-code',json={'receive_my_submissions':True});assert result.status_code==200,result.text
    command=result.json()['command'];assert event(external,cfg,command,openid).status_code==200
    return command


def test_signature_matches_official_document_vector():
    signature=qq_key('DG5g3B4j9X2KOErG').sign(b'1725442341Arq0D5A61EgUu4OxUvOp').hex()
    assert signature=='87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d01bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706'


def test_callback_signature_challenge_is_not_event_signing_oracle(env):
    external=configured(env);cfg=env[1];stamp=str(int(time.time()));plain='SyntheticToken123456789'
    response=external.post('/api/integrations/qq/webhook',json={'op':13,'d':{'plain_token':plain,'event_ts':stamp}},headers={'X-Bot-Appid':cfg.qq_bot_app_id})
    assert response.status_code==200,response.text
    qq_key(cfg.qq_bot_secret).public_key().verify(bytes.fromhex(response.json()['signature']),(stamp+plain).encode())
    bad=external.post('/api/integrations/qq/webhook',json={'op':13,'d':{'plain_token':'{"op":0,"d":{}}','event_ts':stamp}},headers={'X-Bot-Appid':cfg.qq_bot_app_id})
    assert bad.status_code==400
    assert event(external,cfg,stamp=str(int(time.time())-400)).status_code==403
    assert external.post('/api/integrations/qq/webhook',json={'op':0,'d':{}},headers={'X-Bot-Appid':cfg.qq_bot_app_id}).status_code==403
    assert external.post('/api/conversations',json={}).status_code==403
    assert external.post('/api/integrations/qq/webhook',content=b'X'*262145).status_code==413


def test_qq_binding_is_opt_in_single_use_scoped_and_receipt_idempotent(env):
    external=configured(env);cfg=env[1];a=account(env);b=account(env,'bob')
    assert a.post('/api/integrations/qq/link-code',json={'receive_my_submissions':False}).status_code==422
    assert event(external,cfg).status_code==200 and a.get('/api/conversations').json()==[]
    command=bind(a,external,cfg)
    assert a.get('/api/integrations').json()['qq']['bound']
    assert event(external,cfg,command,'someone-else').status_code==200
    assert event(external,cfg,'不能串号','someone-else').status_code==200
    assert event(external,cfg,'工程验收消息',mid='same-message').status_code==200
    assert event(external,cfg,'工程验收消息',mid='same-message').status_code==200
    chats=a.get('/api/conversations').json();assert len(chats)==1 and b.get('/api/conversations').json()==[]
    assert event(external,cfg,'群事件不能误收',t='GROUP_AT_MESSAGE_CREATE').status_code==200
    assert len(a.get('/api/conversations').json())==1
    cid=chats[0]['id'];chat=a.get('/api/conversations/'+cid).json()
    assert chat['sources'][0]['sections'][0]['text']=='工程验收消息'
    assert a.request('DELETE','/api/conversations/'+cid,json={'version':chat['version']}).status_code==200
    event(external,cfg,'工程验收消息',mid='same-message');assert a.get('/api/conversations').json()==[]


def test_binding_conflict_cannot_reassign_another_account_and_unlink_stops_receipt(env):
    external=configured(env);cfg=env[1];a=account(env);b=account(env,'bob');bind(a,external,cfg)
    bind(b,external,cfg)
    assert a.get('/api/integrations').json()['qq']['bound'] and not b.get('/api/integrations').json()['qq']['bound']
    a.post('/api/integrations/qq/unlink');event(external,cfg)
    assert not a.get('/api/integrations').json()['qq']['bound'] and a.get('/api/conversations').json()==[]


def test_external_attachments_are_marked_incomplete_not_downloaded(env,monkeypatch):
    external=configured(env);cfg=env[1];a=account(env);bind(a,external,cfg)
    response=event(external,cfg,'',extra={'attachments':[{'url':'http://127.0.0.1:1/private','filename':'secret.pdf'}]})
    assert response.status_code==200
    cid=a.get('/api/conversations').json()[0]['id'];data=a.get('/api/conversations/'+cid).json()
    assert data['sources'][0]['status']=='failed' and not data['sources'][0]['sections']
    assert '未取得' in data['sources'][0]['warning']
    assert a.get('/api/tasks').json()==[]


def test_qq_expired_binding_code_does_not_bind(env):
    external=configured(env);cfg=env[1];a=account(env)
    command=a.post('/api/integrations/qq/link-code',json={'receive_my_submissions':True}).json()['command']
    with env[0].state.db.connect(write=True) as db:db.execute('UPDATE binding_codes SET expires_at=0')
    event(external,cfg,command)
    assert not a.get('/api/integrations').json()['qq']['bound']


def test_publisher_admin_authorization_private_import_and_no_duplicate(env,monkeypatch):
    a=account(env,'admin','admin');b=account(env,'bob');publisher=env[0].state.publisher_client
    assert b.get('/api/integrations/wechat/articles').status_code==403
    assert b.post('/api/integrations/wechat/import',json={'article_id':'fixture','index':0}).status_code==403
    def fixture_request(path,payload,token=None):
        if path.endswith('stable_token'):return {'access_token':'fixture-token','expires_in':7200}
        if path.endswith('batchget'):return {'total_count':1,'item':[{'article_id':'fixture','content':{'news_item':[{'title':'工程文章'}]}}]}
        return {'news_item':[{'title':'工程文章','content':'<p>请核对报名条件</p><script>secret-script</script><img src="http://localhost/private"><p>附件待补</p>'}]}
    env[1].wechat_publisher_app_id='fixture';env[1].wechat_publisher_secret='fixture'
    monkeypatch.setattr(publisher,'request',fixture_request)
    listing=a.get('/api/integrations/wechat/articles');assert listing.json()['items'][0]['title']=='工程文章'
    payload={'article_id':'fixture','index':0};r=a.post('/api/integrations/wechat/import',json=payload)
    assert r.status_code==200,r.text
    cid=r.json()['conversation_id'];data=a.get('/api/conversations/'+cid).json();s=data['sources'][0]
    assert s['status']=='review' and s['kind']=='html' and 'secret-script' not in json.dumps(s['sections'])
    assert a.post('/api/integrations/wechat/import',json=payload).json()['already_imported']
    assert b.get('/api/conversations/'+cid).status_code==404
    original=a.get('/api/conversations/'+cid+'/sources/'+s['id']+'/download?preview=true')
    assert 'attachment' in original.headers['content-disposition'] and 'text/html' not in original.headers['content-type']
    assert a.get('/api/tasks').json()==[]


@pytest.mark.parametrize('body',[{'errcode':48001,'errmsg':'private-secret'},{'not':'expected'},[],{'item':[],'total_count':'broken'}])
def test_publisher_business_errors_and_malformed_responses_are_not_success(env,monkeypatch,body):
    cfg=env[1];cfg.wechat_publisher_app_id='app';cfg.wechat_publisher_secret='secret'
    client=PublisherClient(cfg);client.token='fixture';client.expires=time.time()+100
    real=httpx.Client
    def fixture_http(**kwargs):
        def respond(request):
            assert request.url.host=='api.weixin.qq.com' and request.url.scheme=='https'
            return httpx.Response(200,json=body)
        return real(transport=httpx.MockTransport(respond),**kwargs)
    monkeypatch.setattr(httpx,'Client',fixture_http)
    with pytest.raises(HTTPException) as exc:client.articles(0)
    assert exc.value.status_code==502 and 'private-secret' not in str(exc.value.detail)


def test_backup_restore_removes_external_binding_and_pending_codes(env,tmp_path):
    external=configured(env);a=account(env);bind(a,external,env[1]);a.post('/api/integrations/qq/link-code',json={'receive_my_submissions':True})
    path=tmp_path/'backup.sqlite3';env[0].state.db.backup(path)
    restored=tmp_path/'restored.sqlite3';restore_database(path,restored)
    with Database(restored).connect() as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==1
        for table in ['external_bindings','binding_codes','sessions','invites']:assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
