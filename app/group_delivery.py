"""Local durable QQ group fan-out. One member's quota never blocks another."""
import asyncio
import hashlib
import json
import logging
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from .db import dumps, ident
from .documents import MAX_CHARS, text_source, total_chars
from .notice_ingest import ingest_notice
from . import qq_group_intake as routing, qq_group_media as media
from .usage_limits import StorageCapacityError

DELIVERY_BATCH_SIZE = 16
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
CREATE INDEX IF NOT EXISTS qq_group_deliveries_event ON qq_group_deliveries(app_id,group_id,event_key,created_at);
INSERT OR IGNORE INTO meta VALUES('qq_group_delivery_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='qq_group_delivery_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('群收件队列版本不兼容或缺少必要表')
    conn.executescript(SCHEMA)
    media.initialize(conn)
    routing.initialize(conn)


def ready_materials(conn, info):
    if not info or not info['media_total']:
        return [], ''
    if not info['media_id']:
        return [], info['media_note'] or '原件暂存已过期，请从群里补传。'
    batch = conn.execute('SELECT state,note FROM qq_group_attachment_batches WHERE id=?',
                         (info['media_id'],)).fetchone()
    if batch['state'] != 'ready':
        return None, ''
    return media.load_files(conn, info['media_id']), batch['note']


def notice_materials(row, originals, media_note):
    sources = json.loads(row['sources'])
    text = sources[0]
    # Keep unresolved material identity separate from the text. Otherwise two
    # different file-only events, or two "看附件" messages, would deduplicate.
    unresolved = '；'.join(dict.fromkeys(note for note in (text['warning'],media_note) if note))
    if text['sections']:
        if originals or unresolved:
            text = {**text,'status':'ok','warning':''}
        result = [text]
    else:
        result = []
    if unresolved or not (result or originals):
        marker = text_source('', 'QQ 待补材料')
        marker.update(sha256=hashlib.sha256(('qq-missing:'+row['event_key']+':'+row['fingerprint']).encode()).hexdigest(),
                      status='review' if result or originals else 'failed',
                      warning=unresolved or '没有可读正文，请核对群内原件。')
        result.append(marker)
    remaining = MAX_CHARS-total_chars(result)
    hashes = set()
    for item in originals:
        if item['sha256'] in hashes:
            continue
        hashes.add(item['sha256'])
        chars = total_chars([item])
        if chars>remaining:
            item = {**item,'sections':[],'status':'review',
                    'warning':'正文与附件文字合计超过通知容量，原件已保存，请下载核对或分开转入。'}
        else:
            remaining -= chars
        result.append(item)
    return result


def deliver_one(conn, row, now):
    """The caller owns the transaction; only this recipient is rolled back."""
    info = conn.execute('SELECT * FROM qq_group_delivery_info WHERE delivery_id=?',(row['id'],)).fetchone()
    originals, media_note = ready_materials(conn,info)
    if originals is None:
        return False
    label = info['source_label'] if info else 'QQ 群'

    def ingest(files, note):
        return ingest_notice(conn,row['user_id'],title=row['title'],sources=notice_materials(row,files,note),
                             source_label=label,external_key=row['event_key'],materials_complete=False,
                             observed_at=row['observed_at'])

    conn.execute('SAVEPOINT group_recipient')
    try:
        try:
            result = ingest(originals,media_note)
        except StorageCapacityError:
            if not originals:
                raise
            conn.execute('ROLLBACK TO group_recipient')
            originals = []
            media_note = '；'.join(filter(None,(media_note,'本人文件空间不足，已保留可读消息；可清理空间后补传原件。')))
            result = ingest(originals,media_note)
    except HTTPException as exc:
        conn.execute('ROLLBACK TO group_recipient')
        conn.execute('RELEASE group_recipient')
        attempt = row['attempts'] + 1
        conn.execute('UPDATE qq_group_deliveries SET state=?,attempts=?,next_attempt=?,error=? WHERE id=?',
                     ('failed' if attempt >= 5 else 'pending', attempt, now + min(3600, 60 * 2 ** attempt), str(exc.detail)[:500], row['id']))
        return False
    routing.record_receipt(conn,result.get('receipt_id'),info)
    if info:
        outcome = ('superseded' if result.get('stale') else 'updated' if result['updated'] else
                   'new' if result['created'] else 'merged')
        saved = 0 if result.get('stale') else len(originals)
        if outcome=='superseded' and info['media_total']:
            media_note = '这次收件版本早于已保存版本。'
        state = 'none' if not info['media_total'] else 'missing' if not saved else (
            'partial' if saved<info['media_total'] else 'complete')
        conn.execute('''UPDATE qq_group_delivery_info SET result=?,media_state=?,media_saved=?,media_note=?
            WHERE delivery_id=?''', (outcome,state,saved,media_note[:1000],row['id']))
    conn.execute('RELEASE group_recipient')
    conn.execute("UPDATE qq_group_deliveries SET state=?,attempts=attempts+1,finished_at=?,error='',notice_id=?,sources='' WHERE id=?",
                 ('superseded' if result.get('stale') else 'delivered', now, result['notice_id'], row['id']))
    conn.execute('UPDATE qq_group_subscriptions SET last_received_at=? WHERE user_id=? AND app_id=? AND group_id=?',
                 (now, row['user_id'], row['app_id'], row['group_id']))
    return True


def enqueue(conn, subscribers, app_id, group_id, event_key, title, source, observed_at, plan):
    """Persist each recipient before acknowledging; share only the download job."""
    snapshot = {key: value for key, value in source.items() if key not in {'id', 'content'}}
    snapshot['content'] = None
    identity = dumps([snapshot,plan.fingerprint]) if plan.fingerprint else dumps(snapshot)
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    text = '\n'.join(part['text'] for part in snapshot['sections'])
    candidates = []
    batch_id = None
    now = int(time.time())
    encoded = dumps([snapshot])
    if plan.files:
        media.refresh_manifest(conn,app_id,group_id,event_key,fingerprint,plan)
    for subscriber in subscribers:
        delivery_id = ident()
        uid = subscriber['user_id']
        added = conn.execute('''INSERT OR IGNORE INTO qq_group_deliveries
            (id,user_id,app_id,group_id,event_key,fingerprint,title,sources,observed_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (delivery_id,uid,app_id,group_id,event_key,fingerprint,title,encoded,observed_at or 1.0,now)).rowcount
        if added:
            if plan.files and not batch_id:
                batch_id = media.stage(conn,app_id,group_id,event_key,fingerprint,plan,now)
            category, reasons = routing.classify(text,material=bool(plan.total or source['warning']),
                                                keywords=json.loads(subscriber['keywords'] or '[]'))
            quiet = category=='discussion' and subscriber['mode']!='all'
            label = 'QQ 群 · '+subscriber['name'] if subscriber['name'] else 'QQ 群'
            conn.execute('''INSERT INTO qq_group_delivery_info
                (delivery_id,category,reasons,rule_version,quiet,source_label,media_id,media_state,media_total,media_note)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (delivery_id,category,dumps(reasons),routing.RULE_VERSION,
                int(quiet),label,batch_id,'waiting' if batch_id else 'missing' if plan.total else 'none',
                plan.total,media.skipped_note(plan.skipped)))
        else:
            delivery_id = conn.execute('SELECT id FROM qq_group_deliveries WHERE user_id=? AND event_key=? AND fingerprint=?',
                                      (uid,event_key,fingerprint)).fetchone()['id']
            conn.execute('UPDATE qq_group_delivery_info SET repeats=repeats+1 WHERE delivery_id=?',(delivery_id,))
        if not added or not batch_id:
            candidates.append(delivery_id)
    for delivery_id in candidates[:DELIVERY_BATCH_SIZE]:
        row = conn.execute('SELECT * FROM qq_group_deliveries WHERE id=?',(delivery_id,)).fetchone()
        if row['state']=='pending' and row['next_attempt']<=now:
            deliver_one(conn,row,now)


def tick(db, app_id, now=None):
    now = int(time.time()) if now is None else now
    # Bounded transactions let independent members proceed even when one
    # account has exhausted its notice/storage allowance.
    for _ in range(DELIVERY_BATCH_SIZE):
        with db.connect(write=True) as conn:
            row = conn.execute("""SELECT d.* FROM qq_group_deliveries d
                LEFT JOIN qq_group_delivery_info i ON i.delivery_id=d.id
                LEFT JOIN qq_group_attachment_batches b ON b.id=i.media_id
                WHERE d.app_id=? AND d.state='pending' AND d.next_attempt<=?
                AND (b.id IS NULL OR b.state='ready')
                ORDER BY d.next_attempt,d.created_at,d.rowid LIMIT 1""", (app_id, now)).fetchone()
            if not row:
                return False
            deliver_one(conn, row, now)
    return True


def status(conn, uid, app_id):
    return [dict(row) for row in conn.execute("""SELECT d.id,d.group_id,d.title,d.state,d.attempts,d.error,d.created_at,
        CASE WHEN b.state IN ('queued','running') THEN 1 ELSE 0 END AS waiting_attachments
        FROM qq_group_deliveries d LEFT JOIN qq_group_delivery_info i ON i.delivery_id=d.id
        LEFT JOIN qq_group_attachment_batches b ON b.id=i.media_id
        WHERE d.user_id=? AND d.app_id=? AND d.state IN ('pending','failed')
        ORDER BY d.created_at DESC,d.rowid DESC LIMIT 50""", (uid, app_id))]


async def run_worker(db, settings):
    while True:
        more = False
        try:
            if settings.qq_bot_app_id and settings.qq_bot_secret:
                more = await run_in_threadpool(tick, db, settings.qq_bot_app_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('campus').error('group_delivery_worker_failed')
        await asyncio.sleep(0.25 if more else 30)
