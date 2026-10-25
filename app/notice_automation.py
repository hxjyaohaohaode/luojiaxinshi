"""Explicitly authorized, versioned source-to-draft work. Never confirms actions."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from starlette.concurrency import run_in_threadpool

from .usage_limits import limits_for
from .db import dumps, ident
from .models import Generate, Strict

PROFILE_KEYS={'campus_role','school','level','grade','college','major','semester','goals','campus_area','interests','available_time'}
TABLES={'notice_automation_settings','notice_automation_jobs','notice_profile_checks','notice_automation_attempts'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS notice_automation_settings(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL DEFAULT 0,consented_at INTEGER,version INTEGER NOT NULL DEFAULT 1,
 daily_limit INTEGER NOT NULL DEFAULT 200,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notice_automation_jobs(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 input_version INTEGER NOT NULL,profile_hash TEXT NOT NULL,state TEXT NOT NULL,
 created_at INTEGER NOT NULL,started_at INTEGER,finished_at INTEGER,lease_until INTEGER,
 result_version INTEGER,error TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL DEFAULT 0,
 UNIQUE(notice_id,input_version,profile_hash));
CREATE INDEX IF NOT EXISTS notice_automation_queue ON notice_automation_jobs(state,created_at);
CREATE TABLE IF NOT EXISTS notice_automation_attempts(
 id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES notice_automation_jobs(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,started_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notice_profile_checks(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
 notice_version INTEGER NOT NULL,profile_hash TEXT NOT NULL,checked_at INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('notice_automation_schema_version','1');
"""


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='notice_automation_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('通知自动整理记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


def profile_hash(profile):
    profile=json.loads(profile) if isinstance(profile,str) else profile
    return hashlib.sha256(dumps({key:profile.get(key,'') for key in sorted(PROFILE_KEYS)}).encode()).hexdigest()


def mark_profile(conn,nid,uid,version,profile):
    if not conn.execute('SELECT 1 FROM notices WHERE id=? AND user_id=? AND version=?',(nid,uid,version)).fetchone():return
    conn.execute('INSERT INTO notice_profile_checks VALUES(?,?,?,?) ON CONFLICT(notice_id) DO UPDATE SET notice_version=excluded.notice_version,profile_hash=excluded.profile_hash,checked_at=excluded.checked_at',
                 (nid,version,profile_hash(profile),int(time.time())))


def needs_profile_review(conn,nid,uid):
    row=conn.execute('SELECT p.profile_hash,u.profile FROM notice_profile_checks p JOIN notices n ON n.id=p.notice_id JOIN users u ON u.id=n.user_id WHERE n.id=? AND n.user_id=?',(nid,uid)).fetchone()
    return bool(row and row['profile_hash']!=profile_hash(row['profile']))


def require_current_profile(conn,nid,uid):
    if needs_profile_review(conn,nid,uid):
        raise HTTPException(409,'个人适用条件已改变，请重新整理或手工核对当前草稿后再确认')


def detail(conn,nid,uid):
    row=conn.execute('SELECT * FROM notice_automation_jobs WHERE notice_id=? AND user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(nid,uid)).fetchone()
    return {'job':dict(row) if row else None,'needs_profile_review':needs_profile_review(conn,nid,uid)}


def authorized_source(conn,uid,nid,settings):
    keys=[r[0] for r in conn.execute('SELECT r.external_key FROM notice_ingest_receipts r JOIN notices n ON n.id=r.notice_id WHERE r.notice_id=? AND r.user_id=? AND r.fingerprint=n.fingerprint',(nid,uid))]
    for key in keys:
        if key.startswith('website:'):
            sid=key.split(':',2)[1]
            subscription=conn.execute('SELECT config FROM source_subscriptions WHERE source_id=? AND user_id=? AND enabled=1',(sid,uid)).fetchone()
            if subscription:
                config=json.loads(subscription['config']);url=key.split(':',2)[2]
                if urlsplit(url).hostname==urlsplit(config['url']).hostname and (config['mode']=='feed' or urlsplit(url).path.startswith(config['article_path_prefix'])):return True
        elif key.startswith('wechat:'):
            if key.split(':',2)[1]==settings.wechat_publisher_app_id and conn.execute("SELECT 1 FROM publisher_subscriptions p JOIN users u ON u.id=p.user_id WHERE p.user_id=? AND p.enabled=1 AND p.app_id=? AND u.role='admin'",(uid,settings.wechat_publisher_app_id)).fetchone():return True
        elif key.startswith('qq-group:'):
            parts=key.split(':',3)
            if len(parts)==4 and parts[1]==settings.qq_bot_app_id and conn.execute('SELECT 1 FROM qq_group_subscriptions WHERE user_id=? AND app_id=? AND group_id=?',(uid,parts[1],parts[2])).fetchone():return True
        elif key.startswith('qq-c2c:'):
            parts=key.split(':',3)
            if len(parts)==4 and parts[1]==settings.qq_bot_app_id and conn.execute('SELECT 1 FROM external_bindings WHERE user_id=? AND app_id=? AND open_id=?',(uid,parts[1],parts[2])).fetchone():return True
    return False


def eligible(conn,notice,settings):
    if notice['status'] in {'confirmed','processing'}:return False
    disposition=conn.execute('SELECT disposition FROM notice_dispositions WHERE notice_id=?',(notice['id'],)).fetchone()
    if disposition and disposition[0]!='inbox':return False
    has_tasks=conn.execute('SELECT 1 FROM tasks WHERE notice_id=?',(notice['id'],)).fetchone()
    changed=conn.execute("SELECT 1 FROM notice_ingest_updates WHERE notice_id=? AND state='pending'",(notice['id'],)).fetchone()
    if has_tasks and not changed:return False
    return authorized_source(conn,notice['user_id'],notice['id'],settings)


def queue_ready(conn,settings,only_uid=None):
    params=(only_uid,) if only_uid else ()
    users=conn.execute('SELECT u.* FROM users u JOIN notice_automation_settings a ON a.user_id=u.id WHERE a.enabled=1 AND a.consented_at IS NOT NULL'+(' AND u.id=?' if only_uid else ''),params).fetchall()
    for user in users:
        digest=profile_hash(user['profile'])
        for notice in conn.execute("SELECT * FROM notices WHERE user_id=? AND status IN ('received','draft','failed')",(user['id'],)).fetchall():
            if not eligible(conn,notice,settings):continue
            profile=conn.execute('SELECT * FROM notice_profile_checks WHERE notice_id=?',(notice['id'],)).fetchone()
            if notice['status']=='draft' and notice['draft_version']==notice['version']:
                # Existing human-edited / old untracked drafts are not replaced.
                if not profile or profile['profile_hash']==digest:continue
            now=int(time.time())
            conn.execute("INSERT OR IGNORE INTO notice_automation_jobs(id,user_id,notice_id,input_version,profile_hash,state,created_at) VALUES(?,?,?,?,?,'queued',?)",
                         (ident(),user['id'],notice['id'],notice['version'],digest,now))
            conn.execute("UPDATE notice_automation_jobs SET state='queued',error='',finished_at=NULL WHERE notice_id=? AND input_version=? AND profile_hash=? AND state='cancelled' AND attempts=0",
                         (notice['id'],notice['version'],digest))


def today_start():
    now=datetime.now(timezone(timedelta(hours=8)))
    return int(now.replace(hour=0,minute=0,second=0,microsecond=0).timestamp())


def run_once(app,db,settings):
    now=int(time.time())
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notice_automation_jobs SET state='failed',error='上次整理中断，计费状态不确定；请核对后手动重试',finished_at=? WHERE state='running' AND lease_until<?",(now,now))
        queue_ready(conn,settings)
        rows=conn.execute("""SELECT j.* FROM notice_automation_jobs j WHERE j.state='queued'
            AND NOT EXISTS(SELECT 1 FROM notice_automation_settings a WHERE a.user_id=j.user_id
                AND (SELECT count(*) FROM notice_automation_attempts t WHERE t.user_id=j.user_id AND t.started_at>=?)>=MIN(a.daily_limit,?))
            ORDER BY j.created_at,j.rowid LIMIT 50""",(today_start(),limits_for(conn).automation_daily_max)).fetchall()
        selected=None
        for row in rows:
            pref=conn.execute('SELECT * FROM notice_automation_settings WHERE user_id=?',(row['user_id'],)).fetchone()
            notice=conn.execute('SELECT * FROM notices WHERE id=?',(row['notice_id'],)).fetchone()
            user=conn.execute('SELECT * FROM users WHERE id=?',(row['user_id'],)).fetchone()
            if not pref or not pref['enabled'] or not pref['consented_at'] or not notice or not user or not eligible(conn,notice,settings):
                conn.execute("UPDATE notice_automation_jobs SET state='cancelled',error='自动整理已停用、来源授权已撤回或事项已处理',finished_at=? WHERE id=?",(now,row['id']))
                continue
            if notice['version']!=row['input_version'] or profile_hash(user['profile'])!=row['profile_hash']:
                conn.execute("UPDATE notice_automation_jobs SET state='stale',error='通知或个人条件已有新版本，本次未调用模型',finished_at=? WHERE id=?",(now,row['id']))
                continue
            used=conn.execute('SELECT count(*) FROM notice_automation_attempts WHERE user_id=? AND started_at>=?',(row['user_id'],today_start())).fetchone()[0]
            if used>=min(pref['daily_limit'],limits_for(conn).automation_daily_max):continue
            selected=dict(row);current_user=dict(user)
            conn.execute("UPDATE notice_automation_jobs SET state='running',started_at=?,lease_until=?,attempts=attempts+1,error='' WHERE id=?",(now,now+max(600,getattr(settings,'ai_workflow_timeout',1800)+120),row['id']))
            conn.execute('INSERT INTO notice_automation_attempts VALUES(?,?,?,?)',(ident(),row['id'],row['user_id'],now))
            break
    if not selected:return None
    try:
        result=app.state.generate_notice(selected['notice_id'],Generate(version=selected['input_version'],allow_external_processing=True),current_user)
        if not isinstance(result,dict) or result.get('status')!='draft':
            raise HTTPException(502,'整理未返回可核对草稿，请查看通知的实际处理状态')
        with db.connect(write=True) as conn:
            live=conn.execute('SELECT version,status FROM notices WHERE id=?',(selected['notice_id'],)).fetchone()
            if not live or live['version']!=result.get('version') or live['status']!='draft':
                conn.execute("UPDATE notice_automation_jobs SET state='stale',error='完成时通知已有更新，请核对当前版本',finished_at=?,lease_until=NULL WHERE id=?",(int(time.time()),selected['id']))
                return None
            mark_profile(conn,selected['notice_id'],selected['user_id'],live['version'],current_user['profile'])
            conn.execute("UPDATE notice_automation_jobs SET state='succeeded',result_version=?,finished_at=?,lease_until=NULL WHERE id=?",(live['version'],int(time.time()),selected['id']))
            return {'job_id':selected['id'],'notice_id':selected['notice_id'],'state':'succeeded'}
    except Exception as exc:
        error=str(exc.detail) if isinstance(exc,HTTPException) else '自动整理未完成，请查看通知后决定是否重试'
        with db.connect(write=True) as conn:
            conn.execute("UPDATE notice_automation_jobs SET state='failed',error=?,finished_at=?,lease_until=NULL WHERE id=?",(error[:1000],int(time.time()),selected['id']))
        return {'job_id':selected['id'],'notice_id':selected['notice_id'],'state':'failed','error':error}


async def run_worker(app,db,settings):
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notice_automation_jobs SET state='failed',error='服务重启中断了上次整理，请核对后决定是否重试',finished_at=?,lease_until=NULL WHERE state='running'",(int(time.time()),))
    while True:
        try:await run_in_threadpool(run_once,app,db,settings)
        except asyncio.CancelledError:raise
        except Exception:logging.getLogger('campus').error('notice_automation_worker_failed')
        await asyncio.sleep(15)


class AutomationSettings(Strict):
    enabled: bool
    allow_external_processing: bool=False
    daily_limit: int | None=Field(default=None,ge=1,le=1000000)
    version: int=Field(default=0,ge=0)

    @model_validator(mode='after')
    def consent(self):
        if self.enabled and not self.allow_external_processing:
            raise ValueError('开启自动整理前须明确同意将通知和相关个人条件交给外部模型处理')
        return self


def status(conn,uid):
    row=conn.execute('SELECT * FROM notice_automation_settings WHERE user_id=?',(uid,)).fetchone()
    result=dict(row) if row else {'enabled':False,'version':0,'daily_limit':limits_for(conn).automation_daily_default,'consented_at':None}
    result['daily_limit_max']=limits_for(conn).automation_daily_max
    result['daily_limit']=min(result['daily_limit'],result['daily_limit_max'])
    result['enabled']=bool(result['enabled'])
    result['jobs']=[dict(r) for r in conn.execute('SELECT j.*,n.title FROM notice_automation_jobs j JOIN notices n ON n.id=j.notice_id WHERE j.user_id=? ORDER BY j.created_at DESC,j.rowid DESC LIMIT 30',(uid,))]
    result['used_today']=conn.execute('SELECT count(*) FROM notice_automation_attempts WHERE user_id=? AND started_at>=?',(uid,today_start())).fetchone()[0]
    result['counts']={r['state']:r['total'] for r in conn.execute('SELECT state,count(*) AS total FROM notice_automation_jobs WHERE user_id=? GROUP BY state',(uid,))}
    return result


def install(app,db,settings,user):
    @app.get('/api/notice-automation')
    def read(current=Depends(user)):
        with db.connect() as conn:return status(conn,current['id'])

    @app.put('/api/notice-automation')
    def configure(payload:AutomationSettings,current=Depends(user)):
        with db.connect(write=True) as conn:
            daily_limit=payload.daily_limit or limits_for(conn).automation_daily_default
            if daily_limit>limits_for(conn).automation_daily_max:raise HTTPException(422,f'每日自动整理最多可设置 {limits_for(conn).automation_daily_max} 则')
            old=status(conn,current['id'])
            if old['version']!=payload.version:raise HTTPException(409,'自动整理设置已更新，请刷新后再保存')
            now=int(time.time())
            conn.execute('INSERT INTO notice_automation_settings VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,consented_at=excluded.consented_at,version=version+1,daily_limit=excluded.daily_limit,updated_at=excluded.updated_at',
                         (current['id'],payload.enabled,now if payload.enabled else None,1,daily_limit,now))
            if payload.enabled:queue_ready(conn,settings,current['id'])
            else:conn.execute("UPDATE notice_automation_jobs SET state='cancelled',finished_at=?,error='本人已停用自动整理' WHERE user_id=? AND state='queued'",(now,current['id']))
            return status(conn,current['id'])

    @app.post('/api/notice-automation/{job_id}/retry')
    def retry(job_id:str,current=Depends(user)):
        with db.connect(write=True) as conn:
            job=conn.execute('SELECT * FROM notice_automation_jobs WHERE id=? AND user_id=?',(job_id,current['id'])).fetchone()
            if not job:raise HTTPException(404,'整理记录不存在')
            pref=conn.execute('SELECT * FROM notice_automation_settings WHERE user_id=?',(current['id'],)).fetchone()
            if not pref or not pref['enabled'] or not pref['consented_at']:raise HTTPException(409,'请先开启自动整理并确认模型处理授权')
            notice=conn.execute('SELECT * FROM notices WHERE id=?',(job['notice_id'],)).fetchone()
            if job['state']!='failed' or not eligible(conn,notice,settings):raise HTTPException(409,'当前记录不可重试，请查看通知或来源授权')
            if notice['version']!=job['input_version'] or profile_hash(current['profile'])!=job['profile_hash']:
                queue_ready(conn,settings,current['id'])
                return JSONResponse({'detail':'通知或个人条件已变化，已按新版本排队，请查看最新整理记录'},status_code=409)
            conn.execute("UPDATE notice_automation_jobs SET state='queued',error='',finished_at=NULL,lease_until=NULL WHERE id=?",(job_id,))
            return {'ok':True}
