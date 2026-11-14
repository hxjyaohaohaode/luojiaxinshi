"""Opt-in email delivery using the same reminder candidates as Web Push."""
import asyncio
import json
import logging
import time
from fastapi import Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from .cloud_messages import CloudMessages
from .db import dumps, ident
from .models import Strict
from .push_delivery import candidates
from .security import rate_limit

TABLES={'mail_preferences','mail_outbox'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS mail_preferences(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL, destination TEXT NOT NULL, contact_verified_at INTEGER NOT NULL,
 consented_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mail_outbox(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_key TEXT NOT NULL,payload TEXT NOT NULL,destination TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending',due_at INTEGER NOT NULL,created_at INTEGER NOT NULL,
 lease_until INTEGER NOT NULL DEFAULT 0,finished_at INTEGER,error TEXT NOT NULL DEFAULT '',
 provider_id TEXT NOT NULL DEFAULT '',UNIQUE(user_id,event_key));
CREATE INDEX IF NOT EXISTS mail_outbox_due ON mail_outbox(state,due_at);
INSERT OR IGNORE INTO meta VALUES('mail_delivery_schema_version','1');
"""


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='mail_delivery_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):raise ValueError('邮件投递数据缺失或版本不兼容')
    conn.executescript(SCHEMA)


def preference(conn, uid):
    return conn.execute("""SELECT p.* FROM mail_preferences p JOIN verified_contacts c
        ON c.user_id=p.user_id AND c.channel='email' AND c.value=p.destination
        AND c.verified_at=p.contact_verified_at WHERE p.user_id=? AND p.enabled=1""",(uid,)).fetchone()


def reconcile(conn, uid, now):
    pref=preference(conn,uid)
    wanted=candidates(conn,uid,now) if pref else {}
    if pref:
        from .proactive_policy import delivered_refs,receipt_payload
        seen=delivered_refs(conn,'mail_outbox',uid)
        from .notification_events import channel_events
        wanted=channel_events(wanted,seen,pref['consented_at'])
        for key,event in list(wanted.items()):
            if key.startswith('received:'):
                notices=[n for n in event['received_items'] if n['created_at']>=pref['consented_at'] and n.get('ref') not in seen]
                if not notices:wanted.pop(key)
                else:event['payload']=receipt_payload(event['payload'],notices)

    for row in conn.execute("SELECT * FROM mail_outbox WHERE user_id=? AND state='pending'",(uid,)).fetchall():
        event=wanted.get(row['event_key'])
        valid=pref and row['destination']==pref['destination'] and (event or row['event_key'].startswith('test:'))
        if not valid:conn.execute("UPDATE mail_outbox SET state='cancelled',finished_at=? WHERE id=?",(now,row['id']))
        elif event:conn.execute('UPDATE mail_outbox SET payload=?,due_at=? WHERE id=?',(dumps(event['payload']),event['due_at'],row['id']))
    if not pref:return
    for key,event in wanted.items():
        if event.get('created_at') and event['created_at']<pref['consented_at']:continue
        if event['due_at']<pref['consented_at']:continue
        conn.execute('INSERT OR IGNORE INTO mail_outbox(id,user_id,event_key,payload,destination,due_at,created_at) VALUES(?,?,?,?,?,?,?)',
                     (ident(),uid,key,dumps(event['payload']),pref['destination'],event['due_at'],now))
        # A future reminder cancelled while opted out may be scheduled again
        # after explicit re-enablement. Accepted/uncertain messages never replay.
        conn.execute("UPDATE mail_outbox SET state='pending',payload=?,destination=?,due_at=?,created_at=?,finished_at=NULL,error='' WHERE user_id=? AND event_key=? AND state='cancelled'",
                     (dumps(event['payload']),pref['destination'],event['due_at'],now,uid,key))


def tick(db, settings, provider=None, now=None):
    sender=provider or CloudMessages(settings)
    if not sender.available('email'):return
    def clock():
        return int(time.time() if now is None else now)
    with db.connect(write=True) as conn:
        moment=clock()
        # Provider timeouts and process crashes have ambiguous delivery status.
        # Never blindly replay an already submitted notification on restart.
        conn.execute("UPDATE mail_outbox SET state='uncertain',finished_at=?,error='发送中断，送达状态待核对' WHERE state='sending' AND lease_until<?",(moment,moment))
        conn.execute("DELETE FROM mail_outbox WHERE state NOT IN ('pending','sending') AND finished_at<?",(moment-30*86400,))
        users=[row['user_id'] for row in conn.execute('SELECT user_id FROM mail_preferences WHERE enabled=1')]
    from .notification_coordination import coordinate
    for uid in users:coordinate(db,uid,'email',clock(),reconcile)
    for _ in range(12):
        # Locate a possible job without claiming submission. Budget accounting
        # can wait on the database; current truth must be checked after it.
        with db.connect() as conn:
            row=conn.execute("SELECT id FROM mail_outbox WHERE state='pending' AND due_at<=? ORDER BY due_at,rowid LIMIT 1",(clock(),)).fetchone()
            if not row:return
            jid=row['id']
        try:rate_limit(db,'mail-reminder-budget',settings.notification_mail_daily_limit,86400)
        except HTTPException:
            with db.connect(write=True) as conn:
                conn.execute("UPDATE mail_outbox SET error='今日邮件额度已用完，等待额度恢复' WHERE id=? AND state='pending'",(jid,))
            return
        with db.connect(write=True) as conn:
            # Read the live clock only after FIFO/SQLite admission. Explicit
            # now remains fixed for deterministic simulations and tests.
            moment=clock()
            row=conn.execute("SELECT * FROM mail_outbox WHERE id=? AND state='pending' AND due_at<=?",(jid,moment)).fetchone()
            if not row:continue
            job=dict(row);reconcile(conn,job['user_id'],moment)
            if conn.execute('SELECT state FROM mail_outbox WHERE id=?',(job['id'],)).fetchone()[0]!='pending':continue
            pref=preference(conn,job['user_id'])
            if not pref or pref['destination']!=job['destination']:continue
            job=dict(conn.execute('SELECT * FROM mail_outbox WHERE id=?',(job['id'],)).fetchone())
            if job['due_at']>moment:continue
            conn.execute("UPDATE mail_outbox SET state='sending',lease_until=? WHERE id=?",(moment+60,job['id']))
        try:
            payload=json.loads(job['payload'])
            if payload.get('user_id')!=job['user_id']:raise ValueError('invalid_owner')
            url=payload.get('url','/#dashboard')
            if not url.startswith('/#'):url='/#dashboard'
            body=f"{payload.get('title','校园提醒')}\n{payload.get('body','')}\n\n查看并核对：{settings.origin}{url}\n\n此邮件来自你在珞珈信使中开启的提醒。可在提醒设置中随时关闭。"
            receipt=sender.send_mail(job['destination'],'珞珈信使 · 校园提醒',body)
            state,error='accepted',''
        except Exception:
            receipt='';state,error='uncertain','邮件提交未确认，请检查收件箱和垃圾邮件；系统不会重复提交这条邮件'
        with db.connect(write=True) as conn:
            moment=clock()
            conn.execute('UPDATE mail_outbox SET state=?,finished_at=?,error=?,provider_id=? WHERE id=? AND state=?',
                         (state,moment,error,str(receipt)[:100],job['id'],'sending'))


async def run_worker(db,settings):
    while True:
        try:await run_in_threadpool(tick,db,settings)
        except asyncio.CancelledError:raise
        except Exception as exc:logging.getLogger('campus').error('mail_worker_failed error=%s',type(exc).__name__)
        await asyncio.sleep(15)


class Preference(Strict):
    enabled: bool
    accepted_delivery: bool = False


def install(app,db,settings,user):
    @app.get('/api/notifications/email')
    def status(current=Depends(user)):
        with db.connect() as conn:
            pref=preference(conn,current['id'])
            email=conn.execute("SELECT value FROM verified_contacts WHERE user_id=? AND channel='email'",(current['id'],)).fetchone()
            recent=[dict(r) for r in conn.execute('SELECT id,state,created_at,finished_at,error FROM mail_outbox WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 10',(current['id'],))]
        return {'configured':CloudMessages(settings).available('email'),'enabled':bool(pref),'email':email['value'] if email else '',
                'recent':recent,'delivery_note':'服务商接受请求不代表收件箱已收到或学生已阅读'}

    @app.put('/api/notifications/email')
    def configure(payload:Preference,current=Depends(user)):
        with db.connect(write=True) as conn:
            email=conn.execute("SELECT * FROM verified_contacts WHERE user_id=? AND channel='email'",(current['id'],)).fetchone()
            if payload.enabled:
                if not email:raise HTTPException(422,'请先在账号安全中验证邮箱')
                if not CloudMessages(settings).available('email'):raise HTTPException(503,'邮件发送服务尚未配置')
                if not payload.accepted_delivery:raise HTTPException(422,'请确认将提醒内容发送到绑定邮箱')
                if not preference(conn,current['id']):
                    conn.execute('INSERT OR REPLACE INTO mail_preferences VALUES(?,1,?,?,?)',(current['id'],email['value'],email['verified_at'],int(time.time())))
            else:
                conn.execute('UPDATE mail_preferences SET enabled=0 WHERE user_id=?',(current['id'],))
                conn.execute("UPDATE mail_outbox SET state='cancelled',finished_at=? WHERE user_id=? AND state='pending'",(int(time.time()),current['id']))
        return {'ok':True}

    @app.post('/api/notifications/email/test')
    def test(current=Depends(user)):
        rate_limit(db,'mail-test:'+current['id'],3,3600)
        with db.connect(write=True) as conn:
            pref=preference(conn,current['id'])
            if not pref:raise HTTPException(422,'请先开启邮件提醒')
            now=int(time.time());key='test:'+ident()
            payload={'user_id':current['id'],'title':'测试提醒','body':'如果你读到了这封邮件，邮件通道已到达此收件箱。','url':'/#dashboard'}
            conn.execute('INSERT INTO mail_outbox(id,user_id,event_key,payload,destination,due_at,created_at) VALUES(?,?,?,?,?,?,?)',
                         (ident(),current['id'],key,dumps(payload),pref['destination'],now,now))
        return {'state':'pending'}
