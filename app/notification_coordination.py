"""Per-owner committed revisions plus a bounded temporal fallback for outboxes."""
import hashlib

from .db import dumps

TABLES={'notification_reconcile_state'}
DOMAINS=('account','notices','tasks','calendar','collaboration','sources','delivery','reminders')
FALLBACK_SECONDS=60
SCHEMA="""
CREATE TABLE IF NOT EXISTS notification_reconcile_state(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 channel TEXT NOT NULL CHECK(channel IN ('push','email')),revision TEXT NOT NULL,
 checked_at INTEGER NOT NULL,PRIMARY KEY(user_id,channel));
INSERT OR IGNORE INTO meta VALUES('notification_coordination_schema_version','1');
"""


def initialize(conn):
    marker=conn.execute("SELECT value FROM meta WHERE key='notification_coordination_schema_version'").fetchone()
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if marker and (marker[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('提醒协调数据版本不兼容或必要记录缺失')
    conn.executescript(SCHEMA)


def revision(conn,uid):
    values=[(row['domain'],row['revision']) for row in conn.execute('SELECT domain,revision FROM workspace_revisions WHERE subject=? ORDER BY domain',('user:'+uid,)) if row['domain'] in DOMAINS]
    return hashlib.sha256(dumps(values).encode()).hexdigest()


def needed(conn,uid,channel,now):
    row=conn.execute('SELECT revision,checked_at FROM notification_reconcile_state WHERE user_id=? AND channel=?',(uid,channel)).fetchone()
    return not row or now<row['checked_at'] or now-row['checked_at']>=FALLBACK_SECONDS or row['revision']!=revision(conn,uid)


def coordinate(db,uid,channel,now,reconcile):
    """Skip unchanged accounts without a write transaction; recheck after locking.

    This only coordinates queue planning. Delivery workers must still run their
    unconditional, current-state validation immediately before each dispatch.
    """
    if channel not in {'push','email'}:raise ValueError('Unknown notification channel')
    with db.connect() as conn:
        if not needed(conn,uid,channel,now):return False
    with db.connect(write=True) as conn:
        if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():return False
        if not needed(conn,uid,channel,now):return False
        reconcile(conn,uid,now)
        # Capture AFTER queue mutations so our own writes do not cause a loop.
        conn.execute('INSERT INTO notification_reconcile_state VALUES(?,?,?,?) ON CONFLICT(user_id,channel) DO UPDATE SET revision=excluded.revision,checked_at=excluded.checked_at',(uid,channel,revision(conn,uid),now))
    return True
