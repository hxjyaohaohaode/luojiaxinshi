from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from test_workflow import env, account, PASSWORD, ORIGIN
from verification_helpers import proof,install_capture,advance_cooldown


def anonymous(app):return TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})


def test_mandatory_verification_and_unconfigured_channels_fail_closed(env):
    app,_=env;c=anonymous(app)
    body={'username':'alice','password':PASSWORD,'display_name':'A','accepted_terms':True}
    assert c.post('/api/auth/register',json=body).status_code==400
    assert c.post('/api/auth/challenges',json={'purpose':'register','channel':'sms','destination':'13800000000'}).status_code==503
    assert c.get('/api/auth/policy').json()['channels']=={'sms':False,'email':False}


def test_sms_signup_password_and_code_login(env):
    app,_=env;c=anonymous(app)
    token=proof(c,channel='sms',destination='+86 13800000000')
    body={'username':'student001','password':PASSWORD,'display_name':'合成学生','accepted_terms':True,'verification_token':token}
    assert c.post('/api/auth/register',json=body).status_code==200
    assert c.get('/api/session').json()['user']['verified_contacts'][0]['value']=='13800000000'
    assert c.post('/api/auth/register',json={**body,'username':'another'}).status_code==400
    assert anonymous(app).post('/api/auth/login',json={'username':'13800000000','password':PASSWORD}).status_code==200
    advance_cooldown(app);other=anonymous(app)
    login=proof(other,'login','13800000000','sms')
    assert other.post('/api/auth/verified-login',json={'verification_token':login}).status_code==200
    assert other.post('/api/auth/verified-login',json={'verification_token':login}).status_code==400


def test_wrong_attempts_are_committed_and_limit_survives_parallel_requests(env):
    app,_=env;provider=install_capture(app);c=anonymous(app)
    r=c.post('/api/auth/challenges',json={'purpose':'register','channel':'email','destination':'one@example.invalid'});cid=r.json()['challenge_id']
    correct=provider.codes[cid];wrong='000001' if correct=='000000' else '000000'
    def attempt(_):return anonymous(app).post('/api/auth/verify',json={'challenge_id':cid,'code':wrong}).status_code
    with ThreadPoolExecutor(max_workers=6) as pool:assert list(pool.map(attempt,range(6)))==[400]*6
    assert c.post('/api/auth/verify',json={'challenge_id':cid,'code':correct}).status_code==400
    with app.state.db.connect() as conn:assert conn.execute('SELECT attempts FROM auth_challenges WHERE id=?',(cid,)).fetchone()[0]==5


def test_expiration_resend_and_budget(env):
    app,cfg=env;install_capture(app);c=anonymous(app)
    data={'purpose':'register','channel':'sms','destination':'13800000000'}
    first=c.post('/api/auth/challenges',json=data).json();assert c.post('/api/auth/challenges',json=data).status_code==429
    with app.state.db.connect(write=True) as conn:conn.execute('UPDATE auth_challenges SET expires_at=0')
    assert c.post('/api/auth/verify',json={'challenge_id':first['challenge_id'],'code':app.state.verification.provider.codes[first['challenge_id']]}).status_code==400
    cfg.otp_sms_daily_limit=1
    assert c.post('/api/auth/challenges',json={**data,'destination':'13800000001'}).status_code==429
    assert len(app.state.verification.provider.codes)==1


def test_password_reset_requires_otp_and_invalidates_sessions(env):
    c=account(env);app,_=env;other=anonymous(app)
    assert other.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).status_code==200
    assert c.post('/api/auth/password',json={'old_password':PASSWORD,'new_password':'New-Password-2026'}).status_code==400
    assert other.post('/api/auth/recover',json={'username':'alice','password':'New-Password-2026','recovery_code':'legacy-backdoor-is-not-valid'}).status_code==400
    advance_cooldown(app);token=proof(other,'recover','alice@example.invalid',username='alice')
    assert other.post('/api/auth/recover',json={'username':'alice','password':'New-Password-2026','verification_token':token}).status_code==200
    assert c.get('/api/session').status_code==401


def test_contact_change_needs_old_identity_and_new_contact_proof(env):
    c=account(env);app,_=env
    new=proof(c,'contact_bind','13800000000','sms')
    assert c.post('/api/account/contacts',json={'verification_token':new}).status_code==400
    advance_cooldown(app);old=proof(c,'contact_authorize','alice@example.invalid')
    assert c.post('/api/account/contacts',json={'verification_token':new,'authorization_token':old}).status_code==200
    assert {x['channel'] for x in c.get('/api/account/contacts').json()['contacts']}=={'sms','email'}
    assert c.patch('/api/profile',json={'changes':{'phone':'13800000001'},'expected':{'phone':'13800000000'}}).status_code==422


def test_proof_purpose_and_account_isolation(env):
    a=account(env);b=account(env,'bob');app,_=env
    advance_cooldown(app);token=proof(a,'password','alice@example.invalid')
    assert b.post('/api/auth/password',json={'old_password':PASSWORD,'new_password':'New-Password-2026','verification_token':token}).status_code==400
    assert a.post('/api/account/contacts',json={'verification_token':token,'authorization_token':token}).status_code==400


def test_delivery_failure_never_produces_a_valid_challenge(env):
    app,_=env;provider=install_capture(app);c=anonymous(app)
    from fastapi import HTTPException
    def fail(*args):raise HTTPException(502,'Synthetic provider failure')
    provider.send_code=fail
    assert c.post('/api/auth/challenges',json={'purpose':'register','channel':'email','destination':'a@example.invalid'}).status_code==502
    with app.state.db.connect() as conn:
        row=conn.execute('SELECT * FROM auth_challenges').fetchone();assert row['state']=='failed' and row['digest']==''


def test_password_length_is_consistent_for_signup_login_change_and_delete(env):
    from app.models import Login,Register,Recover,PasswordChange
    from app.account import DeleteAccount
    from app.verification import BindContact
    from pydantic import ValidationError
    import pytest
    password='Synthetic-Passphrase-'+('x'*235)
    assert len(password)==256
    Login(username='fixture',password=password)
    Register(username='fixture',display_name='fixture',password=password)
    Recover(username='fixture',password=password)
    PasswordChange(old_password=password,new_password=password)
    DeleteAccount(password=password,confirm='注销账号')
    BindContact(old_password=password,verification_token='fixture-token-with-32-characters')
    with pytest.raises(ValidationError):Login(username='fixture',password=password+'x')


def test_contact_aliases_cannot_shadow_another_verified_phone(env):
    app,_=env;c=anonymous(app)
    token=proof(c,channel='sms',destination='13800000000')
    assert c.post('/api/auth/register',json={'username':'first','password':PASSWORD,'display_name':'A','accepted_terms':True,'verification_token':token}).status_code==200
    other=anonymous(app);token=proof(other,destination='other@example.invalid')
    for alias in ('+8613800000000','138-0000-0000'):
        assert other.post('/api/auth/register',json={'username':alias,'password':PASSWORD,'display_name':'B','accepted_terms':True,'verification_token':token}).status_code==409


def test_email_hyphens_remain_meaningful_when_checking_account_aliases(env):
    app,_=env;c=anonymous(app)
    token=proof(c,channel='sms',destination='13800000000')
    assert c.post('/api/auth/register',json={'username':'student-name@example.invalid','password':PASSWORD,'display_name':'A','accepted_terms':True,'verification_token':token}).status_code==200
    other=anonymous(app)
    proof(other,destination='studentname@example.invalid')
    assert other.post('/api/auth/challenges',json={'purpose':'register','channel':'email','destination':'student-name@example.invalid'}).status_code==409


def test_future_verification_schema_is_rejected_before_any_migration(env):
    from app.db import Database
    import pytest
    app,cfg=env
    with app.state.db.connect(write=True) as conn:conn.execute("UPDATE meta SET value='future' WHERE key='verification_schema_version'")
    with app.state.db.connect() as conn:before=list(conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name'))
    with pytest.raises(RuntimeError,match='未修改数据库'):Database(cfg.data_dir/'campus.sqlite3')
    with app.state.db.connect() as conn:assert [tuple(r) for r in conn.execute('SELECT name,sql FROM sqlite_master ORDER BY name')]==[tuple(r) for r in before]
