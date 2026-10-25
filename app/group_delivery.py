"""Local durable QQ group fan-out. One member's quota never blocks another."""
import asyncio
import hashlib
import json
import logging
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from .db import dumps, ident
from .notice_ingest import ingest_notice

TABLES = {'qq_group_deliveries'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS qq_group_deliveries(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,app_id TEXT NOT NULL,group_id TEXT NOT NULL,
 event_key TEXT NOT NULL,fingerprint TEXT NOT NULL,title TEXT NOT NULL,sources TEXT NOT NULL,
 observed_at REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,finished_at INTEGER,
 error TEXT NOT NULL DEFAULT '',notice_id TEXT,
 UNIQUE(user_id,event_key,fingerprint),
 FOREIGN KEY(user_id,app_id,group_id) REFERENCES qq_group_subscriptions(user_id,app_id,group_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS qq_group_deliveries_due ON qq_group_deliveries(state,next_attempt);
INSERT OR IGNORE INTO meta VALUES('qq_group_delivery_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='qq_group_delivery_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('群收件队列版本不兼容或缺少必要表')
    conn.executescript(SCHEMA)


def deliver_one(conn, row, now):
    """The caller owns the transaction; only this recipient is rolled back."""
    conn.execute('SAVEPOINT group_recipient')
    try:
        result = ingest_notice(conn, row['user_id'], title=row['title'], sources=json.loads(row['sources']),
                               source_label='QQ 群', external_key=row['event_key'],
                               materials_complete=False, observed_at=row['observed_at'])
    except HTTPException as exc:
        conn.execute('ROLLBACK TO group_recipient')
        conn.execute('RELEASE group_recipient')
        attempt = row['attempts'] + 1
        conn.execute('UPDATE qq_group_deliveries SET state=?,attempts=?,next_attempt=?,error=? WHERE id=?',
                     ('failed' if attempt >= 5 else 'pending', attempt, now + min(3600, 60 * 2 ** attempt), str(exc.detail)[:500], row['id']))
        return False
    conn.execute('RELEASE group_recipient')
    conn.execute("UPDATE qq_group_deliveries SET state=?,attempts=attempts+1,finished_at=?,error='',notice_id=?,sources='' WHERE id=?",
                 ('superseded' if result.get('stale') else 'delivered', now, result['notice_id'], row['id']))
    conn.execute('UPDATE qq_group_subscriptions SET last_received_at=? WHERE user_id=? AND app_id=? AND group_id=?',
                 (now, row['user_id'], row['app_id'], row['group_id']))
    return True


def enqueue(conn, uid, app_id, group_id, event_key, title, source, observed_at):
    # Group adapters produce text only. Keep the whole untruncated payload for
    # failed recipients; successful rows retain only the idempotency receipt.
    snapshot = {key: value for key, value in source.items() if key not in {'id', 'content'}}
    snapshot['content'] = None
    fingerprint = hashlib.sha256(dumps(snapshot).encode()).hexdigest()
    now = int(time.time())
    conn.execute('''INSERT OR IGNORE INTO qq_group_deliveries
        (id,user_id,app_id,group_id,event_key,fingerprint,title,sources,observed_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)''',
                 (ident(), uid, app_id, group_id, event_key, fingerprint, title, dumps([snapshot]), observed_at or 1.0, now))
    row = conn.execute('SELECT * FROM qq_group_deliveries WHERE user_id=? AND event_key=? AND fingerprint=?',
                       (uid, event_key, fingerprint)).fetchone()
    if row['state'] == 'pending' and row['next_attempt'] <= now:
        deliver_one(conn, row, now)


def tick(db, app_id, now=None):
    now = int(time.time()) if now is None else now
    # Bounded transactions let independent members proceed even when one
    # account has exhausted its notice/storage allowance.
    for _ in range(16):
        with db.connect(write=True) as conn:
            row = conn.execute("""SELECT * FROM qq_group_deliveries WHERE app_id=? AND state='pending'
                AND next_attempt<=? ORDER BY next_attempt,created_at,rowid LIMIT 1""", (app_id, now)).fetchone()
            if not row:
                return
            deliver_one(conn, row, now)


def status(conn, uid, app_id):
    return [dict(row) for row in conn.execute("""SELECT id,group_id,title,state,attempts,error,created_at
        FROM qq_group_deliveries WHERE user_id=? AND app_id=? AND state IN ('pending','failed')
        ORDER BY created_at DESC,rowid DESC LIMIT 50""", (uid, app_id))]


async def run_worker(db, settings):
    while True:
        try:
            if settings.qq_bot_app_id and settings.qq_bot_secret:
                await run_in_threadpool(tick, db, settings.qq_bot_app_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('campus').error('group_delivery_worker_failed')
        await asyncio.sleep(30)
