"""Purpose-bound OTP challenges and atomic, single-use verification proofs."""
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import Field

from .db import dumps, ident
from .models import Strict
from .security import rate_limit, token_hash, verify_password

TABLES = {'verified_contacts', 'auth_challenges'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS verified_contacts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 channel TEXT NOT NULL CHECK(channel IN ('sms','email')), value TEXT NOT NULL,
 verified_at INTEGER NOT NULL, PRIMARY KEY(user_id,channel), UNIQUE(channel,value));
CREATE TABLE IF NOT EXISTS auth_challenges(
 id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL, channel TEXT NOT NULL, destination TEXT NOT NULL,
 password_stamp TEXT NOT NULL DEFAULT '', digest TEXT NOT NULL,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 proof_hash TEXT UNIQUE, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 provider_id TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS auth_challenges_expiry ON auth_challenges(expires_at);
CREATE INDEX IF NOT EXISTS auth_challenges_recipient ON auth_challenges(channel,destination,purpose,user_id,state);
INSERT OR IGNORE INTO meta VALUES('verification_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='verification_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('身份验证数据缺失或版本不兼容')
    conn.executescript(SCHEMA)


def normalize(channel, value):
    value = value.strip()
    if channel == 'sms':
        value = re.sub(r'[\s-]', '', value)
        if value.startswith('+86'):value = value[3:]
        if not re.fullmatch(r'1[3-9][0-9]{9}', value):
            raise HTTPException(422, '请输入中国大陆 11 位手机号')
    else:
        value = value.casefold()
        if len(value)>254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", value):
            raise HTTPException(422, '请输入有效的邮箱地址')
    return value


def masked(channel, value):
    return value[:3]+'****'+value[-4:] if channel=='sms' else value[:1]+'***@'+value.split('@')[-1]


def contacts(conn, uid):
    return [dict(r) for r in conn.execute('SELECT channel,value,verified_at FROM verified_contacts WHERE user_id=? ORDER BY channel',(uid,))]


def find_account(conn, identifier):
    name=identifier.strip().casefold()
    row=conn.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
    if row:return row
    channel='email' if '@' in name else 'sms'
    try:value=normalize(channel,name)
    except HTTPException:return None
    return conn.execute('SELECT u.* FROM users u JOIN verified_contacts c ON c.user_id=u.id WHERE c.channel=? AND c.value=?',(channel,value)).fetchone()


def available_contact(conn, channel, value, uid=None):
    owner=conn.execute('SELECT user_id FROM verified_contacts WHERE channel=? AND value=?',(channel,value)).fetchone()
    if channel=='sms':
        alias=conn.execute("SELECT id FROM users WHERE replace(username,'-','') IN (?,?)",(value,'+86'+value)).fetchone()
    else:
        alias=conn.execute('SELECT id FROM users WHERE username=?',(value,)).fetchone()
    if (owner and owner['user_id']!=uid) or (alias and alias['id']!=uid):
        raise HTTPException(409, '此联系方式暂不能绑定，请使用已有账号登录或找回密码')


def available_alias(conn, name):
    channel='email' if '@' in name else 'sms'
    try:value=normalize(channel,name)
    except HTTPException:return
    if conn.execute('SELECT 1 FROM verified_contacts WHERE channel=? AND value=?',(channel,value)).fetchone():
        raise HTTPException(409,'该账号名已经与其他账号的联系方式关联')


def require_verified_alias(name, proof):
    channel='email' if '@' in name else 'sms'
    try:
        value=normalize(channel,name)
    except HTTPException:
        return
    if channel!=proof['channel'] or value!=proof['destination']:
        raise HTTPException(422,{'code':'alias_proof_required','message':'使用手机号或邮箱作为账号名时，请先验证同一个联系方式'})


def consume(conn, proof, purpose, uid=None):
    row=conn.execute("SELECT * FROM auth_challenges WHERE proof_hash=? AND state='verified' AND expires_at>?",(token_hash(proof),int(time.time()))).fetchone()
    if not row or row['purpose']!=purpose or (uid is not None and row['user_id']!=uid):
        raise HTTPException(400, '身份验证已失效或用途不匹配，请重新获取验证码')
    if row['user_id']:
        account=conn.execute('SELECT password FROM users WHERE id=?',(row['user_id'],)).fetchone()
        if not account or token_hash(account['password'])!=row['password_stamp']:
            raise HTTPException(400, '账号安全信息已变更，请重新验证')
        if purpose!='contact_bind' and not conn.execute('SELECT 1 FROM verified_contacts WHERE user_id=? AND channel=? AND value=?',
                (row['user_id'],row['channel'],row['destination'])).fetchone():
            raise HTTPException(400, '联系方式已变更，请重新验证')
    conn.execute("UPDATE auth_challenges SET state='consumed',digest='' WHERE id=?",(row['id'],))
    return dict(row)


class Challenge(Strict):
    purpose: Literal['register','login','recover','password','contact_authorize','contact_bind']
    channel: Literal['sms','email']
    destination: str = Field(max_length=254)
    username: str = Field(default='',max_length=254)
    invite: str = Field(default='',max_length=100)


class Verify(Strict):
    challenge_id: str = Field(min_length=20,max_length=100)
    code: str = Field(pattern=r'^[0-9]{6}$')


class VerifiedLogin(Strict):
    verification_token: str = Field(min_length=20,max_length=100)


class BindContact(VerifiedLogin):
    authorization_token: str = Field(default='',max_length=100)
    old_password: str = Field(default='',max_length=256)


class VerificationService:
    def __init__(self, db, settings, provider):
        self.db,self.settings,self.provider=db,settings,provider
        path=settings.data_dir/'.verification.key'
        # Separate from the database, so a DB-only leak cannot brute-force 6 digits.
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:pass
        else:
            with os.fdopen(fd,'wb') as stream:stream.write(secrets.token_bytes(32))
        self.key=path.read_bytes()
        if len(self.key)!=32:raise RuntimeError('身份验证密钥损坏，未启用验证码')

    def digest(self, cid, code):
        return hmac.new(self.key,(cid+':'+code).encode(),hashlib.sha256).hexdigest()

    def issue(self, payload, ip, current=None):
        value=normalize(payload.channel,payload.destination)
        channel,purpose=payload.channel,payload.purpose
        if not self.provider.available(channel):
            raise HTTPException(503, '短信通道尚未配置，请联系管理员' if channel=='sms' else '邮箱通道尚未配置，请联系管理员')
        with self.db.connect() as conn:
            uid=None;stamp='';deliver=True
            if purpose in {'password','contact_authorize','contact_bind'}:
                if not current:raise HTTPException(401,'请先登录')
                uid=current['id'];stamp=token_hash(current['password'])
                if purpose=='contact_bind':available_contact(conn,channel,value,uid)
                elif not conn.execute('SELECT 1 FROM verified_contacts WHERE user_id=? AND channel=? AND value=?',(uid,channel,value)).fetchone():
                    raise HTTPException(400,'请使用已经验证的手机号或邮箱')
            elif purpose=='register':
                if self.settings.registration_mode=='invite' and not payload.invite:raise HTTPException(403,'请先使用试点邀请链接')
                if payload.invite and not conn.execute('SELECT 1 FROM invites WHERE token_hash=? AND used_at IS NULL AND expires_at>?',(token_hash(payload.invite),int(time.time()))).fetchone():
                    raise HTTPException(400,'邀请链接无效或已使用')
                available_contact(conn,channel,value)
            else:
                record=find_account(conn,payload.username or value)
                if record and conn.execute('SELECT 1 FROM verified_contacts WHERE user_id=? AND channel=? AND value=?',(record['id'],channel,value)).fetchone():
                    uid=record['id'];stamp=token_hash(record['password'])
                else:deliver=False  # Same-shaped response, no disclosure or SMS to unrelated contacts.
        rate_limit(self.db,'otp-ip:'+token_hash(ip),20,3600)
        now=int(time.time());cid=secrets.token_urlsafe(32)
        response={'challenge_id':cid,'expires_in':300,'retry_after':60,'destination':masked(channel,value),
                  'message':'若填写的信息与账号匹配，验证码将发送；请检查短信或邮箱。'}
        if not deliver:
            # An unmatched request must not consume the recipient's delivery
            # allowance or invalidate a legitimate login/recovery in progress.
            rate_limit(self.db,'otp-unmatched:'+token_hash(channel+':'+value+':'+payload.username.casefold()),1,60)
            return response
        key=token_hash(channel+':'+value)
        rate_limit(self.db,'otp-cooldown:'+key,1,60)
        rate_limit(self.db,'otp-destination:'+key,10,86400)
        rate_limit(self.db,'otp-budget:'+channel,getattr(self.settings,'otp_'+('sms' if channel=='sms' else 'mail')+'_daily_limit'),86400)
        code=f'{secrets.randbelow(1000000):06d}'
        with self.db.connect(write=True) as conn:
            conn.execute('DELETE FROM auth_challenges WHERE expires_at<?',(now-86400,))
            conn.execute('INSERT INTO auth_challenges(id,user_id,purpose,channel,destination,password_stamp,digest,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (cid,uid,purpose,channel,value,stamp,self.digest(cid,code),'pending',now,now+300))
        try:
            receipt=self.provider.send_code(channel,value,code,purpose,cid)
        except Exception:
            with self.db.connect(write=True) as conn:
                conn.execute("UPDATE auth_challenges SET state='failed',digest='' WHERE id=? AND state='pending'",(cid,))
            raise
        with self.db.connect(write=True) as conn:
            updated=conn.execute("UPDATE auth_challenges SET state='sent',provider_id=? WHERE id=? AND state='pending'",(str(receipt)[:100],cid))
            if updated.rowcount:
                conn.execute("""UPDATE auth_challenges SET state='superseded',digest=''
                    WHERE channel=? AND destination=? AND purpose=? AND user_id IS ?
                    AND state IN ('pending','sent','verified')
                    AND rowid<(SELECT rowid FROM auth_challenges WHERE id=?)""",(channel,value,purpose,uid,cid))
        if not updated.rowcount:
            raise HTTPException(409,'已发起更新的验证，请使用最近一次发送的验证码')
        elapsed=max(0,int(time.time())-now)
        response.update(expires_in=max(0,300-elapsed),retry_after=max(1,60-elapsed))
        return response

    def verify(self, payload, ip, current=None):
        rate_limit(self.db,'otp-check:'+token_hash(ip),60,900)
        proof=secrets.token_urlsafe(32);valid=False
        # Commit wrong-attempt counters before raising. Failed validation MUST NOT
        # roll back the counter or allow parallel requests to exceed five guesses.
        with self.db.connect(write=True) as conn:
            row=conn.execute('SELECT * FROM auth_challenges WHERE id=?',(payload.challenge_id,)).fetchone()
            if row and row['state']=='sent' and row['expires_at']>int(time.time()) and row['attempts']<5:
                protected=row['purpose'] in {'password','contact_authorize','contact_bind'}
                if protected and (not current or current['id']!=row['user_id']):raise HTTPException(403,'请在发起验证的账号中操作')
                valid=hmac.compare_digest(row['digest'],self.digest(row['id'],payload.code))
                conn.execute('UPDATE auth_challenges SET attempts=attempts+1,state=?,proof_hash=?,digest=? WHERE id=?',
                    ('verified' if valid else 'sent',token_hash(proof) if valid else None,'' if valid else row['digest'],row['id']))
        if not valid:raise HTTPException(400,'验证码错误、已使用或已过期，请检查后重试')
        return {'verification_token':proof,'expires_in':max(0,row['expires_at']-int(time.time()))}


def install(app, db, settings, user, session_response):
    from .cloud_messages import CloudMessages
    service=VerificationService(db,settings,CloudMessages(settings))
    app.state.verification=service

    @app.post('/api/auth/challenges')
    def issue(payload:Challenge,request:Request):
        current=user(request) if payload.purpose in {'password','contact_authorize','contact_bind'} else None
        return service.issue(payload,request.client.host if request.client else 'unknown',current)

    @app.post('/api/auth/verify')
    def verify(payload:Verify,request:Request):
        with db.connect() as conn:row=conn.execute('SELECT purpose FROM auth_challenges WHERE id=?',(payload.challenge_id,)).fetchone()
        current=user(request) if row and row['purpose'] in {'password','contact_authorize','contact_bind'} else None
        return service.verify(payload,request.client.host if request.client else 'unknown',current)

    @app.post('/api/auth/verified-login')
    def verified_login(payload:VerifiedLogin):
        with db.connect(write=True) as conn:
            record=consume(conn,payload.verification_token,'login')
            if not record['user_id']:raise HTTPException(400,'身份验证无效')
            return session_response(conn,record['user_id'])

    @app.get('/api/account/contacts')
    def list_contacts(current=Depends(user)):
        with db.connect() as conn:return {'contacts':contacts(conn,current['id'])}

    @app.post('/api/account/contacts')
    def bind(payload:BindContact,current=Depends(user)):
        rate_limit(db,'bind-contact:'+current['id'],10,3600)
        password_matches=bool(payload.old_password) and verify_password(payload.old_password,current['password'])
        with db.connect(write=True) as conn:
            existing=contacts(conn,current['id'])
            if existing:consume(conn,payload.authorization_token,'contact_authorize',current['id'])
            elif not password_matches or not conn.execute('SELECT 1 FROM users WHERE id=? AND password=?',
                    (current['id'],current['password'])).fetchone():
                raise HTTPException(400,'首次绑定请确认当前密码，并验证新联系方式')
            proof=consume(conn,payload.verification_token,'contact_bind',current['id'])
            available_contact(conn,proof['channel'],proof['destination'],current['id'])
            conn.execute('INSERT INTO verified_contacts VALUES(?,?,?,?) ON CONFLICT(user_id,channel) DO UPDATE SET value=excluded.value,verified_at=excluded.verified_at',
                         (current['id'],proof['channel'],proof['destination'],int(time.time())))
            if proof['channel']=='sms':
                import json
                profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()[0]);profile['phone']=proof['destination']
                conn.execute('UPDATE users SET profile=? WHERE id=?',(dumps(profile),current['id']))
            # Changing contacts invalidates all outstanding proofs and other sessions.
            conn.execute('DELETE FROM auth_challenges WHERE user_id=?',(current['id'],))
            conn.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?',(current['id'],current['session_hash']))
        return {'ok':True}
