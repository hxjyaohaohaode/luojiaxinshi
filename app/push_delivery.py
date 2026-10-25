"""Opt-in Web Push with a durable, revocable per-device delivery queue."""
import asyncio
import base64
from datetime import datetime, timedelta
import hashlib
import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import Depends, HTTPException
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from .db import dumps, ident
from .models import Strict
from .public_http import PublicHTTPTransport
from .security import rate_limit

TABLES = {'push_configuration', 'push_devices', 'push_outbox'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS push_configuration(id INTEGER PRIMARY KEY CHECK(id=1),private_key TEXT NOT NULL,public_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS push_devices(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 endpoint TEXT UNIQUE NOT NULL,keys_json TEXT NOT NULL,created_at INTEGER NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1,last_success INTEGER,error TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS push_devices_owner ON push_devices(user_id,enabled);
CREATE TABLE IF NOT EXISTS push_outbox(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 device_id TEXT NOT NULL REFERENCES push_devices(id) ON DELETE CASCADE,
 event_key TEXT NOT NULL,payload TEXT NOT NULL,due_at INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
 lease_until INTEGER NOT NULL DEFAULT 0,next_attempt INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL,finished_at INTEGER,error TEXT NOT NULL DEFAULT '',
 UNIQUE(device_id,event_key));
CREATE INDEX IF NOT EXISTS push_outbox_due ON push_outbox(state,next_attempt,due_at);
INSERT OR IGNORE INTO meta VALUES('push_delivery_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='push_delivery_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('推送记录版本不兼容或缺少必要表')
    conn.executescript(SCHEMA)


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def configuration(conn):
    row = conn.execute('SELECT * FROM push_configuration WHERE id=1').fetchone()
    if not row:
        private = ec.generate_private_key(ec.SECP256R1())
        secret = b64(private.private_numbers().private_value.to_bytes(32, 'big'))
        public = b64(private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
        conn.execute('INSERT INTO push_configuration VALUES(1,?,?)', (secret, public))
        return {'private_key': secret, 'public_key': public}
    return dict(row)


class Endpoint(Strict):
    endpoint: str = Field(min_length=10, max_length=2000)

    @field_validator('endpoint')
    @classmethod
    def service_endpoint(cls, value):
        parts = urlsplit(value)
        host = parts.hostname or ''
        services = ('fcm.googleapis.com', 'push.services.mozilla.com', 'push.apple.com', 'notify.windows.com')
        if parts.scheme != 'https' or parts.username or parts.password or parts.fragment or parts.port not in (None, 443) or not any(host == s or host.endswith('.' + s) for s in services):
            raise ValueError('此地址不是支持的浏览器推送服务，请从本设备重新启用提醒')
        return value


class PushKeys(Strict):
    p256dh: str = Field(min_length=80, max_length=100)
    auth: str = Field(min_length=20, max_length=30)

    @field_validator('p256dh', 'auth')
    @classmethod
    def base64url_key(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', value):
            raise ValueError('设备密钥必须是有效的 Base64URL')
        return value


class Subscription(Endpoint):
    keys: PushKeys


def _stamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
        return int(result.timestamp()) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def candidates(conn, uid, now):
    """Current truth, recomputed before sending; stored jobs are never the truth."""
    from .workflow import enrich_tasks
    from .insights import deadline_of
    tasks = []
    for row in conn.execute('SELECT t.*,n.title AS notice_title FROM tasks t JOIN notices n ON n.id=t.notice_id WHERE t.user_id=?', (uid,)):
        item = dict(row)
        item['data'] = json.loads(item['data'])
        tasks.append(item)
    enrich_tasks(conn, tasks)
    items = {}
    change_versions = {row['id']: dict(row) for row in conn.execute(
        "SELECT id,created_at,updated_at,version FROM notice_changes WHERE user_id=? AND state='pending'", (uid,))}

    def add(key, at, title, body, url, tag, created_at=0):
        if at is None or at < now - 86400:
            return
        items[key] = {'due_at': int(at), 'created_at': created_at,
                      'payload': {'user_id': uid, 'title': title[:90], 'body': body[:200], 'url': url, 'tag': tag}}

    def deadline_reminders(plans, title, body, url, tag):
        # After a restart or a newly enabled device, collapse superseded
        # offsets into the most recent due reminder instead of ringing twice.
        latest_due = max((at for _, at in plans if at <= now), default=None)
        for key, at in plans:
            if at > now or at == latest_due:
                add(key, at, title, body, url, tag)

    for task in tasks:
        data, workflow = task['data'], task['workflow']['data']
        if data.get('scope') != 'personal' or task.get('action_excluded'):
            continue
        tid, title = task['id'], data['title']
        url = '/#notice/' + task['notice_id']
        if task.get('pending_changes'):
            versions = [{**change, 'version': change_versions[change['id']]['version']} for change in task['pending_changes']]
            change_key = hashlib.sha256(dumps(versions).encode()).hexdigest()
            changed_at = max(change_versions[change['id']]['updated_at'] for change in task['pending_changes'])
            add('change:' + tid + ':' + change_key, changed_at, title, '原通知有变化，请核对已准备或提交的内容', url, 'task:' + tid)
        review = task.get('change_review')
        needs_review = review and review['state'] == 'pending'
        if needs_review:
            add(f"review:{tid}:{review['version']}", review['updated_at'], title, '办理依据已变化，请核对原进度与后续安排', url, 'task:' + tid)
        if task['status'] != 'pending' or needs_review or task.get('pending_changes'):
            continue
        deadline, all_day = deadline_of(data)
        if deadline and data.get('deadline_confirmed'):
            if all_day and deadline.date() >= datetime.fromtimestamp(now, deadline.tzinfo).date():
                # 09:00 is our reminder schedule, never an invented official
                # deadline. Do not use the statistics helper's 23:59 in a push.
                morning = deadline.replace(hour=9, minute=0, second=0)
                plans = []
                for days in (1, 0):
                    moment = int((morning - timedelta(days=days)).timestamp())
                    plans.append((f'deadline-date:{tid}:{days}:{moment}', moment))
                deadline_reminders(plans, title, f'正式截止日期：{deadline:%m月%d日}；原通知未写明时刻，请查看办理要求', url, 'task:' + tid)
            elif not all_day and deadline.timestamp() > now:
                plans = []
                for seconds in (86400, 3600):
                    moment = int(deadline.timestamp()) - seconds
                    plans.append((f'deadline:{tid}:{seconds}:{moment}', moment))
                deadline_reminders(plans, title, f'正式截止：{deadline:%m月%d日 %H:%M}，请查看当前办理状态', url, 'task:' + tid)
        for kind, at, body in (('reminder', _stamp(data.get('reminder_at')), '到了你设置的提醒时间'),
                               ('followup', _stamp(workflow.get('followup_at')), '到了跟进时间，请查看办理进展')):
            if kind != 'reminder' or not any(issue.get('blocking') for issue in task.get('schedule_issues', [])):
                add(f'{kind}:{tid}:{at}', at, title, body, url, 'task:' + tid)
        slot = data.get('scheduled')
        if slot and slot.get('confirmed') and slot.get('start_time'):
            at = _stamp(slot['start_date'] + 'T' + slot['start_time'] + '+08:00')
            if at and at > now:
                add(f'event:{tid}:{at}', at - 900, title, f"活动开始：{slot['start_date']} {slot['start_time']}，请查看地点和准备事项", url, 'task:' + tid)
    for update in conn.execute("SELECT u.id,u.created_at,n.id AS notice_id,n.title FROM notice_ingest_updates u JOIN notices n ON n.id=u.notice_id WHERE n.user_id=? AND u.state='pending'", (uid,)):
        add('intake-change:' + update['id'], update['created_at'], update['title'], '来源内容已更新，已有办理进度已保留，请核对变化', '/#notice/' + update['notice_id'], 'notice:' + update['notice_id'])
    # Group new external receipts into two-minute digests, rather than pushing
    # every forwarded message or replaying the whole library on first enable.
    buckets = {}
    from .notice_automation import profile_hash
    user_profile = profile_hash(conn.execute('SELECT profile FROM users WHERE id=?', (uid,)).fetchone()[0])
    automation = conn.execute('SELECT enabled FROM notice_automation_settings WHERE user_id=?', (uid,)).fetchone()
    rows = conn.execute("""SELECT DISTINCT n.* FROM notices n JOIN notice_ingest_receipts r ON r.notice_id=n.id
        LEFT JOIN notice_dispositions d ON d.notice_id=n.id
        WHERE n.user_id=? AND n.created_at>=? AND COALESCE(d.disposition,'inbox')='inbox'
        AND n.status!='confirmed'
        AND r.external_key NOT LIKE 'manual:%' AND r.external_key NOT LIKE 'conversation:%'""", (uid, now - 86400))
    for row in rows:
        check = conn.execute('SELECT * FROM notice_profile_checks WHERE notice_id=?', (row['id'],)).fetchone()
        current_draft = (row['status'] == 'draft' and row['draft_version'] == row['version'] and check
                         and check['notice_version'] == row['version'] and check['profile_hash'] == user_profile)
        relevance = json.loads(row['draft']).get('applicability') if current_draft else 'needs_review'
        if relevance == 'not_matching':
            continue
        if not current_draft and automation and automation['enabled']:
            job = conn.execute('''SELECT state,created_at FROM notice_automation_jobs
                WHERE notice_id=? AND input_version=? AND profile_hash=? ORDER BY rowid DESC LIMIT 1''',
                               (row['id'], row['version'], user_profile)).fetchone()
            # Let the authorized analysis finish before notifying. A long queue
            # still gets a truthful review-needed reminder, never a match claim.
            if job and job['state'] in {'queued', 'running'} and now - job['created_at'] < 1800:
                continue
            if not job and now - row['created_at'] < 30:
                continue
        buckets.setdefault(row['created_at'] // 120, []).append(
            {'id': row['id'], 'created_at': row['created_at'], 'relevance': relevance})
    for bucket, notices in buckets.items():
        add('received:' + str(bucket), (bucket + 1) * 120, '新收到的通知', receipt_summary(notices), '/#notices', 'notice-inbox', max(n['created_at'] for n in notices))
        key = 'received:' + str(bucket)
        if key in items:
            items[key]['received_items'] = notices
    return items


def receipt_summary(notices):
    matched = sum(item.get('relevance') == 'matches_known' for item in notices)
    pending = len(notices) - matched
    parts = ([f'{matched} 则符合已知个人条件'] if matched else []) + ([f'{pending} 则需要判断是否适用'] if pending else [])
    return '，'.join(parts) + '；请到收件箱核对'


def reconcile(conn, uid, now):
    current = candidates(conn, uid, now)
    devices = conn.execute('SELECT * FROM push_devices WHERE user_id=? AND enabled=1', (uid,)).fetchall()
    device_keys = {device['id']: set() for device in devices}
    for device in devices:
        for key, value in current.items():
            payload = value['payload']
            if key.startswith('received:'):
                received = [item for item in value['received_items'] if item['created_at'] >= device['created_at']]
                if not received:
                    continue
                payload = {**payload, 'body': receipt_summary(received)}
            device_keys[device['id']].add(key)
            conn.execute('''INSERT INTO push_outbox(id,user_id,device_id,event_key,payload,due_at,created_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_id,event_key) DO UPDATE SET
                payload=CASE WHEN push_outbox.state IN ('pending','failed','cancelled') THEN excluded.payload ELSE push_outbox.payload END,
                state=CASE WHEN push_outbox.state='cancelled' THEN 'pending' ELSE push_outbox.state END''',
                (ident(), uid, device['id'], key, dumps(payload), value['due_at'], now))
    for job in conn.execute("SELECT id,device_id,event_key,due_at FROM push_outbox WHERE user_id=? AND state IN ('pending','leased','failed')", (uid,)).fetchall():
        is_test = job['event_key'].startswith('test:')
        expired_test = is_test and job['due_at'] < now - 300
        obsolete = not is_test and job['event_key'] not in device_keys.get(job['device_id'], set())
        if expired_test or obsolete:
            conn.execute("UPDATE push_outbox SET state='cancelled',finished_at=?,error='事项已完成、取消或时间已变更' WHERE id=?", (now, job['id']))


class PublicPushSession:
    def post(self, endpoint, *, data, headers, timeout, **kwargs):
        async def perform():
            async with asyncio.timeout(15), httpx.AsyncClient(transport=PublicHTTPTransport(), trust_env=False,
                    follow_redirects=False, timeout=10) as client:
                async with client.stream('POST', endpoint, content=data, headers=headers) as response:
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise ValueError('push response too large')
                    from requests import Response
                    result = Response()
                    result.status_code, result._content = response.status_code, bytes(content)
                    result.headers.update(response.headers)
                    result.reason = response.reason_phrase
                    return result
        return asyncio.run(perform())


def deliver(device, payload, config):
    from py_vapid import Vapid02
    from pywebpush import webpush
    return webpush({'endpoint': device['endpoint'], 'keys': json.loads(device['keys_json'])},
                   data=dumps(payload), vapid_private_key=Vapid02.from_raw(config['private_key'].encode()),
                   vapid_claims={'sub': 'mailto:notice-operator@localhost'}, ttl=300, timeout=10,
                   headers={'Urgency': 'normal'}, requests_session=PublicPushSession())


def tick(db, now=None):
    fixed_now = now
    def clock():
        return int(fixed_now if fixed_now is not None else time.time())
    now = clock()
    with db.connect(write=True) as conn:
        users = [r[0] for r in conn.execute('SELECT DISTINCT user_id FROM push_devices WHERE enabled=1')]
        for uid in users:
            reconcile(conn, uid, now)
        conn.execute("UPDATE push_outbox SET state='pending' WHERE state='leased' AND lease_until<?", (now,))
        conn.execute("DELETE FROM push_outbox WHERE state IN ('accepted','cancelled','failed') AND finished_at<?", (now - 30 * 86400,))
    for _ in range(12):
        now = clock()
        with db.connect(write=True) as conn:
            job = conn.execute("""SELECT o.* FROM push_outbox o JOIN push_devices d ON d.id=o.device_id
                WHERE d.enabled=1 AND d.user_id=o.user_id AND o.state='pending' AND o.due_at<=? AND o.next_attempt<=?
                ORDER BY o.due_at,o.rowid LIMIT 1""", (now, now)).fetchone()
            if not job:
                return
            job = dict(job)
            reconcile(conn, job['user_id'], now)
            if conn.execute('SELECT state FROM push_outbox WHERE id=?', (job['id'],)).fetchone()[0] != 'pending':
                continue
            # Reconcile may have refreshed the title, count or other payload
            # fields without changing the event identity.
            job = dict(conn.execute('SELECT * FROM push_outbox WHERE id=?', (job['id'],)).fetchone())
            device = dict(conn.execute('SELECT * FROM push_devices WHERE id=? AND enabled=1', (job['device_id'],)).fetchone())
            try:
                payload = json.loads(job['payload'])
            except (ValueError, TypeError):
                payload = None
            if not isinstance(payload, dict) or payload.get('user_id') != job['user_id'] or device['user_id'] != job['user_id']:
                conn.execute("UPDATE push_outbox SET state='cancelled',finished_at=?,error='推送记录归属不一致' WHERE id=?", (now, job['id']))
                continue
            lease_until, attempt = now + 60, job['attempts'] + 1
            conn.execute("UPDATE push_outbox SET state='leased',lease_until=?,attempts=attempts+1 WHERE id=?", (lease_until, job['id']))
            config = configuration(conn)
        code, error = 0, ''
        try:
            response = deliver(device, payload, config)
            code = response.status_code
        except Exception as exc:
            response = getattr(exc, 'response', None)
            code = getattr(response, 'status_code', 0)
            # Provider bodies and endpoints may contain capabilities; never log them.
            error = '推送服务暂时不可达' if not code else '推送服务返回 ' + str(code)
        with db.connect(write=True) as conn:
            now = clock()
            if not conn.execute("SELECT 1 FROM push_outbox WHERE id=? AND state='leased' AND lease_until=? AND attempts=?", (job['id'], lease_until, attempt)).fetchone():
                continue
            if 200 <= code < 300:
                conn.execute("UPDATE push_outbox SET state='accepted',finished_at=?,error='' WHERE id=?", (now, job['id']))
                conn.execute("UPDATE push_devices SET last_success=?,error='' WHERE id=?", (now, device['id']))
            else:
                expired = code in (404, 410)
                terminal = expired or job['attempts'] + 1 >= 5 or 400 <= code < 500 and code != 429
                error = '本设备订阅已失效，请重新启用' if expired else error or '推送服务返回 ' + str(code)
                conn.execute('UPDATE push_outbox SET state=?,next_attempt=?,finished_at=?,error=? WHERE id=?',
                             ('failed' if terminal else 'pending', now + min(3600, 30 * 2 ** job['attempts']), now if terminal else None, error, job['id']))
                conn.execute('UPDATE push_devices SET enabled=?,error=? WHERE id=?', (0 if expired else 1, error, device['id']))


async def run_worker(db):
    while True:
        try:
            await run_in_threadpool(tick, db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.getLogger('campus').error('push_worker_failed error=%s', type(exc).__name__)
        await asyncio.sleep(15)


def install(app, db, user):
    @app.get('/api/push/config')
    def config(current=Depends(user)):
        with db.connect(write=True) as conn:
            return {'supported': True, 'public_key': configuration(conn)['public_key']}

    @app.post('/api/push/subscriptions')
    def subscribe(payload: Subscription, current=Depends(user)):
        try:
            def decode(value):
                return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            public = decode(payload.keys.p256dh)
            auth = decode(payload.keys.auth)
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
            if len(auth) != 16:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, '设备密钥无效，请重新启用提醒') from None
        rate_limit(db, 'push-subscribe:' + current['id'], 20, 3600)
        with db.connect(write=True) as conn:
            previous = conn.execute('SELECT * FROM push_devices WHERE endpoint=?', (payload.endpoint,)).fetchone()
            if previous and previous['user_id'] != current['id']:
                raise HTTPException(409, '本设备仍关联另一账号，请关闭本设备提醒后重新启用')
            if not previous and conn.execute('SELECT COUNT(*) FROM push_devices WHERE user_id=?', (current['id'],)).fetchone()[0] >= 10:
                raise HTTPException(413, '最多登记 10 个设备，请先关闭旧设备提醒')
            device_id = previous['id'] if previous else ident()
            renewed = previous and (not previous['enabled'] or json.loads(previous['keys_json']) != payload.keys.model_dump())
            conn.execute('''INSERT INTO push_devices(id,user_id,endpoint,keys_json,created_at) VALUES(?,?,?,?,?)
                ON CONFLICT(endpoint) DO UPDATE SET keys_json=excluded.keys_json,enabled=1,error='' ''',
                         (device_id, current['id'], payload.endpoint, payload.keys.model_dump_json(), int(time.time())))
            if renewed:
                # Explicit re-enabling/rotating keys invalidates old leases;
                # the next reconciliation removes obsolete event plans first.
                conn.execute('UPDATE push_devices SET created_at=? WHERE id=?', (int(time.time()), device_id))
                conn.execute("UPDATE push_outbox SET state='pending',attempts=0,lease_until=0,next_attempt=0,finished_at=NULL,error='' WHERE device_id=? AND state!='accepted'", (device_id,))
            configuration(conn)
            return {'id': device_id}

    @app.delete('/api/push/subscriptions')
    def unsubscribe(payload: Endpoint, current=Depends(user)):
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM push_devices WHERE user_id=? AND endpoint=?', (current['id'], payload.endpoint))
        return {'ok': True}

    @app.get('/api/push/status')
    def status(current=Depends(user)):
        with db.connect() as conn:
            devices = [dict(r) for r in conn.execute('SELECT id,endpoint,created_at,enabled,last_success,error FROM push_devices WHERE user_id=?', (current['id'],))]
            last = conn.execute("""SELECT state,finished_at,error FROM push_outbox WHERE user_id=?
                AND attempts>0 AND state!='cancelled'
                ORDER BY COALESCE(finished_at,lease_until-60) DESC,rowid DESC LIMIT 1""", (current['id'],)).fetchone()
            failures = conn.execute("SELECT COUNT(*) FROM push_outbox WHERE user_id=? AND state='failed'", (current['id'],)).fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM push_outbox WHERE user_id=? AND state IN ('pending','leased')", (current['id'],)).fetchone()[0]
        return {'enabled': any(d['enabled'] for d in devices), 'devices': devices, 'last_delivery': dict(last) if last else None, 'failures': failures, 'pending_count': pending}

    @app.post('/api/push/test', status_code=202)
    def test_delivery(payload: Endpoint, current=Depends(user)):
        rate_limit(db, 'push-test:' + current['id'], 3, 300)
        with db.connect(write=True) as conn:
            device = conn.execute('SELECT id FROM push_devices WHERE user_id=? AND endpoint=? AND enabled=1', (current['id'], payload.endpoint)).fetchone()
            if not device:
                raise HTTPException(404, '请先在本设备启用提醒')
            now, key = int(time.time()), 'test:' + ident()
            data = {'user_id': current['id'], 'title': '提醒测试', 'body': '如果看到了这条系统通知，本设备已收到测试提醒。', 'url': '/#tasks', 'tag': 'campus-push-test'}
            conn.execute('INSERT INTO push_outbox(id,user_id,device_id,event_key,payload,due_at,created_at) VALUES(?,?,?,?,?,?,?)',
                         (ident(), current['id'], device['id'], key, dumps(data), now, now))
        return {'queued': True, 'message': '已排队；推送服务接收与本设备实际显示分别核验'}
