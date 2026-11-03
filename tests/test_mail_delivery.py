import json
import time
from app import mail_delivery as mail
from app.db import ident,dumps
from test_workflow import env,account
from verification_helpers import CapturedMessages


def enable(env,c):
    app,cfg=env;cfg.aliyun_access_key_id='synthetic';cfg.aliyun_access_key_secret='synthetic';cfg.mail_sender='sender@example.invalid'
    assert c.put('/api/notifications/email',json={'enabled':True,'accepted_delivery':True}).status_code==200
    return app,cfg


def test_email_consent_verified_destination_and_real_candidate_lifecycle(env,monkeypatch):
    c=account(env);app,cfg=enable(env,c);uid=c.get('/api/session').json()['user']['id'];now=int(time.time())+1
    candidate={'due_at':now,'payload':{'user_id':uid,'title':'待办提醒','body':'请核对','url':'/#dashboard'}}
    monkeypatch.setattr(mail,'candidates',lambda *args:{'task:1':candidate})
    provider=CapturedMessages();mail.tick(app.state.db,cfg,provider,now)
    assert len(provider.mail)==1 and provider.mail[0][0]=='alice@example.invalid'
    mail.tick(app.state.db,cfg,provider,now+1);assert len(provider.mail)==1
    assert c.get('/api/notifications/email').json()['recent'][0]['state']=='accepted'
    assert c.put('/api/notifications/email',json={'enabled':False}).status_code==200
    monkeypatch.setattr(mail,'candidates',lambda *args:{'task:2':candidate})
    mail.tick(app.state.db,cfg,provider,now+2);assert len(provider.mail)==1


def test_cancel_done_changed_contacts_and_do_not_replay_ambiguous_send(env,monkeypatch):
    c=account(env);app,cfg=enable(env,c);uid=c.get('/api/session').json()['user']['id'];now=int(time.time())+1
    monkeypatch.setattr(mail,'candidates',lambda *args:{})
    with app.state.db.connect(write=True) as conn:
        conn.execute('INSERT INTO mail_outbox(id,user_id,event_key,payload,destination,due_at,created_at) VALUES(?,?,?,?,?,?,?)',
                     (ident(),uid,'done-task',dumps({'user_id':uid}),'alice@example.invalid',now,now))
    provider=CapturedMessages();mail.tick(app.state.db,cfg,provider,now);assert not provider.mail
    assert c.post('/api/notifications/email/test').status_code==200
    def ambiguous(*args):raise TimeoutError('synthetic timeout')
    provider.send_mail=ambiguous;mail.tick(app.state.db,cfg,provider,now)
    assert any(row['state']=='uncertain' for row in c.get('/api/notifications/email').json()['recent'])
    provider=CapturedMessages();mail.tick(app.state.db,cfg,provider,now+120);assert not provider.mail
    assert c.post('/api/notifications/email/test').status_code==200
    with app.state.db.connect(write=True) as conn:conn.execute("UPDATE verified_contacts SET value='changed@example.invalid' WHERE user_id=? AND channel='email'",(uid,))
    mail.tick(app.state.db,cfg,provider,now+180);assert not provider.mail
    assert not c.get('/api/notifications/email').json()['enabled']


def test_email_requires_delivery_consent_and_config(env):
    c=account(env)
    assert c.put('/api/notifications/email',json={'enabled':True,'accepted_delivery':True}).status_code==503
    app,cfg=env;cfg.aliyun_access_key_id='synthetic';cfg.aliyun_access_key_secret='synthetic';cfg.mail_sender='sender@example.invalid'
    assert c.put('/api/notifications/email',json={'enabled':True}).status_code==422


def test_official_sdk_adapters_send_only_expected_fields(env,monkeypatch):
    from types import SimpleNamespace
    from app.cloud_messages import CloudMessages
    from alibabacloud_dypnsapi20170525.client import Client as SMS
    from alibabacloud_dm20151123.client import Client as Mail
    app,cfg=env;cfg.aliyun_access_key_id='synthetic';cfg.aliyun_access_key_secret='synthetic';cfg.sms_sign_name='synthetic';cfg.mail_sender='sender@example.invalid'
    calls=[]
    def sms(self,request,runtime):
        calls.append(request)
        assert request.return_verify_code is False and runtime.autoretry is False
        assert request.template_code=='100003' and json.loads(request.template_param)['code']=='234567'
        return SimpleNamespace(body=SimpleNamespace(code='OK',success=True,request_id='sms-fixture'))
    def email(self,request,runtime):
        calls.append(request);assert request.address_type==1 and request.reply_to_address is False
        assert runtime.autoretry is False
        return SimpleNamespace(body=SimpleNamespace(request_id='mail-fixture'))
    monkeypatch.setattr(SMS,'send_sms_verify_code_with_options',sms);monkeypatch.setattr(Mail,'single_send_mail_with_options',email)
    sender=CloudMessages(cfg)
    assert sender.send_code('sms','13800000000','234567','recover','fixture')=='sms-fixture'
    assert sender.send_code('email','a@example.invalid','234567','register','fixture')=='mail-fixture'
    assert len(calls)==2


def test_qq_mail_uses_verified_tls_fixed_endpoint_and_authorization_code(env,monkeypatch):
    import smtplib
    import ssl
    from app.cloud_messages import CloudMessages
    _,cfg=env
    cfg.mail_provider='qq_smtp';cfg.smtp_username='synthetic-pilot@qq.com';cfg.smtp_authorization_code='synthetic-client-code'
    calls=[]
    class SMTP:
        def __init__(self,host,port,*,timeout,context):
            assert (host,port,timeout)==('smtp.qq.com',465,10)
            assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def login(self,username,password):
            assert (username,password)==(cfg.smtp_username,cfg.smtp_authorization_code)
        def send_message(self,message,*,from_addr,to_addrs):
            assert from_addr==cfg.smtp_username and to_addrs==['recipient@example.invalid']
            assert message['From'].addresses[0].addr_spec==cfg.smtp_username
            calls.append(message)
            return {}
    monkeypatch.setattr(smtplib,'SMTP_SSL',SMTP)
    sender=CloudMessages(cfg)
    assert sender.available('email') and not sender.available('sms')
    receipt=sender.send_code('email','recipient@example.invalid','234567','register','synthetic-request')
    assert receipt==str(calls[0]['Message-ID'])
    assert '234567' in calls[0].get_content() and '注册账号' in calls[0].get_content()


def test_qq_mail_failure_is_sanitized_and_never_retried_or_falls_back(env,monkeypatch):
    import smtplib
    import pytest
    from fastapi import HTTPException
    from app.cloud_messages import CloudMessages
    _,cfg=env
    cfg.mail_provider='qq_smtp';cfg.smtp_username='synthetic-pilot@qq.com';cfg.smtp_authorization_code='synthetic-private-client-code'
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1);raise TimeoutError(cfg.smtp_authorization_code)
    monkeypatch.setattr(smtplib,'SMTP_SSL',fail)
    with pytest.raises(HTTPException) as exc:CloudMessages(cfg).send_mail('recipient@example.invalid','测试','合成内容')
    assert exc.value.status_code==502 and cfg.smtp_authorization_code not in exc.value.detail
    assert len(calls)==1


def test_mail_provider_configuration_rejects_unknown_provider_and_unsafe_sender(env,monkeypatch):
    import pytest
    from app.config import Settings
    _,cfg=env
    monkeypatch.setenv('DATA_DIR',str(cfg.data_dir))
    monkeypatch.setenv('MAIL_PROVIDER','plain_smtp')
    with pytest.raises(ValueError,match='MAIL_PROVIDER'):Settings.from_env()
    monkeypatch.setenv('MAIL_PROVIDER','qq_smtp');monkeypatch.setenv('SMTP_USERNAME','header\ninjection@qq.com')
    with pytest.raises(ValueError,match='SMTP_USERNAME'):Settings.from_env()
