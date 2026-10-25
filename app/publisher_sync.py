"""Private, explicitly enabled polling of the configured publishing account."""
import json
import logging
import time

from fastapi import Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from .models import Strict
from .notice_ingest import ingest_notice
from .security import rate_limit

TABLES={'publisher_subscriptions','publisher_subscription_items'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS publisher_subscriptions(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,app_id TEXT NOT NULL,
 enabled INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1,interval_minutes INTEGER NOT NULL,
 initial_pages INTEGER NOT NULL,remaining_pages INTEGER NOT NULL,initialized INTEGER NOT NULL DEFAULT 0,
 cursor_offset INTEGER,next_poll INTEGER NOT NULL DEFAULT 0,running_until INTEGER NOT NULL DEFAULT 0,
 checked_at INTEGER,succeeded_at INTEGER,error TEXT NOT NULL DEFAULT '',
 received_count INTEGER NOT NULL DEFAULT 0,updated_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS publisher_subscription_items(
 user_id TEXT NOT NULL REFERENCES publisher_subscriptions(user_id) ON DELETE CASCADE,
 article_id TEXT NOT NULL,article_index INTEGER NOT NULL,title TEXT NOT NULL,
 provider_updated REAL,checked_at INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,article_id,article_index));
INSERT OR IGNORE INTO meta VALUES('publisher_sync_schema_version','1');
"""


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='publisher_sync_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('公众号同步记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


class PublisherSubscription(Strict):
    enabled: bool
    initial_pages: int=Field(default=1,ge=1,le=10)
    interval_minutes: int=Field(default=30,ge=5,le=1440)
    version: int=Field(default=0,ge=0)


def status(conn,uid):
    row=conn.execute('SELECT * FROM publisher_subscriptions WHERE user_id=?',(uid,)).fetchone()
    if not row:return {'enabled':False,'state':'manual','version':0,'initial_pages':1,'interval_minutes':30}
    result=dict(row);result['enabled']=bool(row['enabled'])
    result['state']='paused' if not row['enabled'] else 'syncing' if row['running_until']>time.time() else 'error' if row['error'] else 'active' if row['succeeded_at'] else 'waiting'
    result['pending_count']=conn.execute('SELECT count(*) FROM publisher_subscription_items WHERE user_id=? AND checked_at=0',(uid,)).fetchone()[0]
    return result


def sync_one(db,publisher,uid,force=False):
    now=int(time.time())
    with db.connect(write=True) as conn:
        row=conn.execute('SELECT p.*,u.role FROM publisher_subscriptions p JOIN users u ON u.id=p.user_id WHERE p.user_id=?',(uid,)).fetchone()
        if not row:raise HTTPException(404,'尚未开启公众号同步')
        if not row['enabled']:raise HTTPException(409,'公众号同步已暂停')
        if row['role']!='admin' or row['app_id']!=publisher.settings.wechat_publisher_app_id:
            conn.execute("UPDATE publisher_subscriptions SET enabled=0,running_until=0,error='账号权限或发布账号已改变，请重新确认授权' WHERE user_id=?",(uid,))
            return status(conn,uid)
        if row['running_until']>now or (not force and row['next_poll']>now):return status(conn,uid)
        snapshot=dict(row)
        conn.execute('UPDATE publisher_subscriptions SET running_until=?,checked_at=? WHERE user_id=?',(now+600,now,uid))
    errors=[];created=updated=0
    def current(conn):
        return conn.execute("SELECT 1 FROM publisher_subscriptions p JOIN users u ON u.id=p.user_id WHERE p.user_id=? AND p.enabled=1 AND p.version=? AND u.role='admin'",(uid,snapshot['version'])).fetchone()
    def enqueue(conn,listing):
        known=False
        for item in listing['items']:
            old=conn.execute('SELECT provider_updated FROM publisher_subscription_items WHERE user_id=? AND article_id=? AND article_index=?',(uid,item['article_id'],item['index'])).fetchone()
            known=known or old is not None
            revision=item.get('updated_at')
            revision=float(revision) if type(revision) in (int,float) and revision>0 else None
            conn.execute('''INSERT INTO publisher_subscription_items(user_id,article_id,article_index,title,provider_updated) VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,article_id,article_index) DO UPDATE SET title=excluded.title,
                checked_at=CASE WHEN excluded.provider_updated IS NOT NULL AND (publisher_subscription_items.provider_updated IS NULL OR excluded.provider_updated>publisher_subscription_items.provider_updated) THEN 0 ELSE publisher_subscription_items.checked_at END,
                provider_updated=CASE WHEN excluded.provider_updated IS NULL THEN publisher_subscription_items.provider_updated WHEN publisher_subscription_items.provider_updated IS NULL OR excluded.provider_updated>publisher_subscription_items.provider_updated THEN excluded.provider_updated ELSE publisher_subscription_items.provider_updated END''',
                (uid,item['article_id'],item['index'],item['title'],revision))
        return known
    try:
        # Bootstrap reads only the chosen recent publication range. Later polls
        # refresh the head and retain a catch-up cursor until a known item appears.
        bootstrap=snapshot['remaining_pages']>0
        offset=(snapshot['cursor_offset'] or 0) if bootstrap else 0
        listing=publisher.articles(offset)
        with db.connect(write=True) as conn:
            if not current(conn):return None
            known=enqueue(conn,listing)
            if bootstrap:
                remaining=max(0,snapshot['remaining_pages']-1) if listing['next_offset'] is not None else 0
                cursor=listing['next_offset'] if remaining else None
                conn.execute('UPDATE publisher_subscriptions SET initialized=1,remaining_pages=?,cursor_offset=? WHERE user_id=?',(remaining,cursor,uid))
            elif snapshot['cursor_offset'] is None and not known:
                conn.execute('UPDATE publisher_subscriptions SET cursor_offset=? WHERE user_id=?',(listing['next_offset'],uid))
        if not bootstrap and snapshot['cursor_offset'] is not None:
            catchup=publisher.articles(snapshot['cursor_offset'])
            with db.connect(write=True) as conn:
                if not current(conn):return None
                known=enqueue(conn,catchup)
                conn.execute('UPDATE publisher_subscriptions SET cursor_offset=? WHERE user_id=?',(None if known else catchup['next_offset'],uid))
        with db.connect() as conn:
            pending=[dict(r) for r in conn.execute('SELECT * FROM publisher_subscription_items WHERE user_id=? ORDER BY checked_at,provider_updated DESC LIMIT 8',(uid,))]
        for item in pending:
            try:
                title,source=publisher.article(item['article_id'],item['article_index'])
                with db.connect(write=True) as conn:
                    if not current(conn):return None
                    result=ingest_notice(conn,uid,title=title,sources=[source],source_label='获授权公众号',
                        external_key='wechat:'+snapshot['app_id']+':'+item['article_id']+':'+str(item['article_index']),
                        materials_complete=False,observed_at=item['provider_updated'] or time.time())
                    created+=bool(result.get('created'));updated+=bool(result.get('updated'))
                    conn.execute('UPDATE publisher_subscription_items SET checked_at=?,error=? WHERE user_id=? AND article_id=? AND article_index=?',(int(time.time()),'',uid,item['article_id'],item['article_index']))
            except HTTPException as exc:
                errors.append(str(exc.detail))
                with db.connect(write=True) as conn:
                    conn.execute('UPDATE publisher_subscription_items SET checked_at=?,error=? WHERE user_id=? AND article_id=? AND article_index=?',(int(time.time()),str(exc.detail)[:500],uid,item['article_id'],item['article_index']))
    except HTTPException as exc:
        errors.append(str(exc.detail))
    except Exception:
        logging.getLogger('campus').error('publisher_sync_failed')
        errors.append('公众号同步失败，将稍后重试；已保存通知保留')
    finally:
        with db.connect(write=True) as conn:
            if current(conn):
                state=status(conn,uid)
                backlog=state['pending_count'] or state['remaining_pages'] or state['cursor_offset'] is not None
                delay=60 if backlog and not errors else snapshot['interval_minutes']*60
                conn.execute('UPDATE publisher_subscriptions SET running_until=0,next_poll=?,error=?,succeeded_at=CASE WHEN ? THEN succeeded_at ELSE ? END,received_count=received_count+?,updated_count=updated_count+? WHERE user_id=?',
                    (int(time.time())+delay,'；'.join(dict.fromkeys(errors))[:1000],bool(errors),int(time.time()),created,updated,uid))
    with db.connect() as conn:return status(conn,uid)


def sync_due(db,publisher):
    with db.connect() as conn:
        users=[r[0] for r in conn.execute('SELECT user_id FROM publisher_subscriptions WHERE enabled=1 AND next_poll<=? AND running_until<=? ORDER BY next_poll LIMIT 4',(int(time.time()),int(time.time())))]
    for uid in users:sync_one(db,publisher,uid)


def install(app,db,publisher,admin):
    @app.get('/api/integrations/wechat/subscription')
    def read(current=Depends(admin)):
        with db.connect() as conn:return status(conn,current['id'])

    @app.put('/api/integrations/wechat/subscription')
    def configure(payload:PublisherSubscription,current=Depends(admin)):
        if payload.enabled and not (publisher.settings.wechat_publisher_app_id and publisher.settings.wechat_publisher_secret):
            raise HTTPException(503,'请先配置获授权发布账号的公众号凭证')
        with db.connect(write=True) as conn:
            previous=status(conn,current['id'])
            if previous['version']!=payload.version:raise HTTPException(409,'公众号同步设置已改变，请刷新后再保存')
            reset=previous.get('app_id')!=publisher.settings.wechat_publisher_app_id
            if reset:conn.execute('DELETE FROM publisher_subscriptions WHERE user_id=?',(current['id'],))
            conn.execute('''INSERT INTO publisher_subscriptions(user_id,app_id,enabled,interval_minutes,initial_pages,remaining_pages) VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,version=version+1,interval_minutes=excluded.interval_minutes,next_poll=0,running_until=0,error='' ''',
                (current['id'],publisher.settings.wechat_publisher_app_id,payload.enabled,payload.interval_minutes,payload.initial_pages,payload.initial_pages))
            return status(conn,current['id'])

    @app.post('/api/integrations/wechat/refresh')
    async def refresh(current=Depends(admin)):
        rate_limit(db,'publisher-refresh:'+current['id'],20,3600)
        return await run_in_threadpool(sync_one,db,publisher,current['id'],True)
