"""Synthetic durable Web Push tests. Every delivery is intercepted locally."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pytest

from app.db import Database, dumps, ident
from app import push_delivery as push
from tests.test_workflow import account, env, manual, notice, task, confirm


def keys():
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    return {'p256dh': push.b64(public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
            'auth': push.b64(b'0123456789abcdef')}


def subscribe(client, **changes):
    payload = {'endpoint': 'https://fcm.googleapis.com/fcm/send/synthetic-' + uuid4().hex,
               'keys': keys(), **changes}
    response = client.post('/api/push/subscriptions', json=payload)
    assert response.status_code == 200, response.text
    return response.json()['id'], payload


def owner(db, name='alice'):
    with db.connect() as conn:
        return conn.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()[0]


def jobs(db):
    with db.connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM push_outbox ORDER BY rowid')]


def create_task(client):
    n = manual(client, notice(client, 'Synthetic push task ' + uuid4().hex))
    tid = confirm(client, n, task(n, deadline_confirmed=False))
    return n['id'], tid


def revise_task(db, tid, **data):
    with db.connect(write=True) as conn:
        original = json.loads(conn.execute('SELECT data FROM tasks WHERE id=?', (tid,)).fetchone()[0])
        conn.execute('UPDATE tasks SET data=? WHERE id=?', (dumps({**original, **data}), tid))


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def due_reminder(db, tid, now):
    revise_task(db, tid, due_date=None, due_time=None, deadline_confirmed=False,
                planned_at=iso(now + 120), reminder_at=iso(now - 1))


def captured(monkeypatch, code=201):
    calls = []
    def deliver(device, payload, config):
        calls.append({'device': device, 'payload': payload, 'config': config})
        return SimpleNamespace(status_code=code)
    monkeypatch.setattr(push, 'deliver', deliver)
    return calls


def insert_job(db, uid, device, now, *, payload=None, key=None, **fields):
    jid = ident()
    value = dumps(payload if payload is not None else {'user_id': uid, 'title': 'synthetic', 'body': '', 'url': '/#tasks', 'tag': 'test'})
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO push_outbox(id,user_id,device_id,event_key,payload,due_at,created_at) VALUES(?,?,?,?,?,?,?)',
                     (jid, uid, device, key or 'test:' + jid, value, now, now))
        for name, field in fields.items():
            assert name in {'state', 'lease_until', 'attempts', 'next_attempt'}
            conn.execute('UPDATE push_outbox SET ' + name + '=? WHERE id=?', (field, jid))
    return jid


def test_queue_and_vapid_keys_survive_restart_and_send_once(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, _ = subscribe(client); _, tid = create_task(client)
    due_reminder(db, tid, now)
    public = client.get('/api/push/config').json()
    assert set(public) == {'supported', 'public_key'}
    with db.connect(write=True) as conn:
        push.reconcile(conn, uid, now)
    assert len(jobs(db)) == 1 and jobs(db)[0]['state'] == 'pending'
    restored = Database(db.path); calls = captured(monkeypatch)
    push.tick(restored, now); push.tick(restored, now + 10)
    assert len(calls) == 1 and calls[0]['payload']['user_id'] == uid
    assert calls[0]['config']['public_key'] == public['public_key']
    assert jobs(db)[0]['state'] == 'accepted' and jobs(db)[0]['attempts'] == 1
    assert client.get('/api/push/status').json()['last_delivery']['state'] == 'accepted'


def test_reschedule_done_cancel_and_deleted_tasks_revoke_pending_jobs(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    subscribe(client); _, tid = create_task(client); due_reminder(db, tid, now)
    with db.connect(write=True) as conn: push.reconcile(conn, uid, now)
    old = jobs(db)[0]['id']
    revise_task(db, tid, reminder_at=iso(now + 60))
    calls = captured(monkeypatch); push.tick(db, now)
    assert not calls and next(j for j in jobs(db) if j['id'] == old)['state'] == 'cancelled'
    push.tick(db, now + 60)
    assert len(calls) == 1
    for state in ('done', 'cancelled'):
        revise_task(db, tid, reminder_at=iso(now + 70))
        with db.connect(write=True) as conn:
            conn.execute("UPDATE tasks SET status='pending' WHERE id=?", (tid,)); push.reconcile(conn, uid, now + 65)
            conn.execute('UPDATE tasks SET status=? WHERE id=?', (state, tid))
        push.tick(db, now + 70)
        assert len(calls) == 1
    with db.connect(write=True) as conn:
        conn.execute("UPDATE tasks SET status='pending' WHERE id=?", (tid,)); push.reconcile(conn, uid, now + 65)
        conn.execute('DELETE FROM tasks WHERE id=?', (tid,))
    push.tick(db, now + 70)
    assert len(calls) == 1


def test_old_done_task_receives_new_notice_change_and_new_version_replaces_old(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    subscribe(client); nid, tid = create_task(client); cid = ident()
    with db.connect(write=True) as conn:
        conn.execute("UPDATE tasks SET status='done',updated_at=? WHERE id=?", (now - 7 * 86400, tid))
        conn.execute('INSERT INTO notice_changes VALUES(?,?,?,?,?,?,?,?)',
                     (cid, nid, uid, dumps({'kind': 'correction', 'targets': [{'task_id': tid}]}), 'pending', 1, now, now))
        push.reconcile(conn, uid, now)
        conn.execute('UPDATE notice_changes SET version=2,updated_at=? WHERE id=?', (now + 1, cid))
    calls = captured(monkeypatch); push.tick(db, now + 1)
    assert len(calls) == 1 and calls[0]['payload']['url'] == '/#notice/' + nid
    assert sorted(j['state'] for j in jobs(db)) == ['accepted', 'cancelled']
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM tasks WHERE id=?', (tid,)).fetchone()[0] == 'done'


def test_pending_change_review_notifies_done_and_suspends_old_timing(env, monkeypatch):
    client = account(env); db = env[0].state.db; now = int(time.time())
    subscribe(client); nid, tid = create_task(client); due_reminder(db, tid, now)
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO task_reviews(task_id,version,state,data,updated_at) VALUES(?,?,?,?,?)',
                     (tid, 1, 'pending', dumps({'causes': []}), now))
    calls = captured(monkeypatch); push.tick(db, now)
    assert len(calls) == 1 and '办理依据已变化' in calls[0]['payload']['body']
    assert jobs(db)[0]['event_key'].startswith('review:')
    with db.connect(write=True) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (tid,))
        conn.execute('UPDATE task_reviews SET version=2,updated_at=? WHERE task_id=?', (now + 1, tid))
    push.tick(db, now + 1)
    assert len(calls) == 2 and calls[-1]['payload']['url'] == '/#notice/' + nid


def test_date_only_deadlines_and_late_event_wakeup_do_not_invent_times(env):
    client = account(env); db = env[0].state.db; uid = owner(db)
    _, tid = create_task(client)
    moment = datetime(2027, 10, 20, 10, 0, tzinfo=timezone(timedelta(hours=8))); now = int(moment.timestamp())
    revise_task(db, tid, due_date='2027-10-20', due_time=None, deadline_confirmed=True, reminder_at=None)
    with db.connect() as conn: items = push.candidates(conn, uid, now)
    assert items and all('23:59' not in value['payload']['body'] for value in items.values())
    assert any('原通知未写明时刻' in value['payload']['body'] for value in items.values())
    revise_task(db, tid, deadline_confirmed=False, scheduled={'kind': 'event', 'start_date': '2027-10-20', 'start_time': '10:05', 'confirmed': True})
    with db.connect() as conn: items = push.candidates(conn, uid, now)
    event = next(value for key, value in items.items() if key.startswith('event:'))
    assert '10:05' in event['payload']['body'] and '15 分钟' not in event['payload']['body']


def test_late_restart_only_sends_the_latest_deadline_offset(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); subscribe(client)
    _, tid = create_task(client)
    deadline = datetime(2027, 10, 20, 17, 0, tzinfo=timezone(timedelta(hours=8)))
    now = int(deadline.timestamp()) - 1800
    revise_task(db, tid, deadline_confirmed=True)
    with db.connect(write=True) as conn:
        push.reconcile(conn, uid, now - 86400)
    calls = captured(monkeypatch); push.tick(db, now)
    assert len(calls) == 1
    assert sorted(job['state'] for job in jobs(db)) == ['accepted', 'cancelled']
    assert next(job for job in jobs(db) if job['state'] == 'accepted')['event_key'].startswith('deadline:' + tid + ':3600:')


@pytest.mark.parametrize('status', [503, 429, 0])
def test_transient_failure_retries_after_delay_without_exposing_endpoint(env, monkeypatch, status):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, _ = subscribe(client); insert_job(db, uid, device, now); calls = []
    def deliver(*args):
        calls.append(args)
        if len(calls) == 1:
            if not status: raise RuntimeError('secret endpoint and provider body')
            return SimpleNamespace(status_code=status)
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, 'deliver', deliver)
    push.tick(db, now)
    current = jobs(db)[0]
    assert current['state'] == 'pending' and current['attempts'] == 1 and current['next_attempt'] == now + 30
    assert 'secret' not in current['error']
    push.tick(db, now + 29); assert len(calls) == 1
    push.tick(db, now + 30); assert len(calls) == 2 and jobs(db)[0]['state'] == 'accepted'


@pytest.mark.parametrize('status', [404, 410])
def test_expired_device_stops_sending_and_explicit_reenable_can_retry(env, monkeypatch, status):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, payload = subscribe(client); insert_job(db, uid, device, now); insert_job(db, uid, device, now)
    calls = captured(monkeypatch, status); push.tick(db, now)
    state = client.get('/api/push/status').json()
    assert len(calls) == 1 and not state['enabled'] and state['failures'] == 1
    assert client.post('/api/push/subscriptions', json=payload).status_code == 200
    calls = captured(monkeypatch); push.tick(db, now + 1)
    assert len(calls) == 2 and all(job['state'] == 'accepted' for job in jobs(db))


def test_permanent_failure_and_maximum_attempts_do_not_loop(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, _ = subscribe(client); insert_job(db, uid, device, now)
    calls = captured(monkeypatch, 400); push.tick(db, now); push.tick(db, now + 1)
    assert len(calls) == 1 and jobs(db)[0]['state'] == 'failed'
    insert_job(db, uid, device, now, attempts=4)
    calls = captured(monkeypatch, 503); push.tick(db, now); push.tick(db, now + 1)
    assert len(calls) == 1 and jobs(db)[-1]['attempts'] == 5 and jobs(db)[-1]['state'] == 'failed'


def test_owner_isolation_csrf_url_and_key_validation(env, monkeypatch):
    client = account(env); other = account(env, 'other'); db = env[0].state.db
    device, payload = subscribe(client)
    assert other.get('/api/push/status').json()['devices'] == []
    assert other.post('/api/push/subscriptions', json=payload).status_code == 409
    assert other.post('/api/push/test', json={'endpoint': payload['endpoint']}).status_code == 404
    assert other.request('DELETE', '/api/push/subscriptions', json={'endpoint': payload['endpoint']}).status_code == 200
    assert client.get('/api/push/status').json()['devices'][0]['id'] == device
    assert client.post('/api/push/subscriptions', json=payload, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    for endpoint in ('http://fcm.googleapis.com/test', 'https://localhost/test', 'https://fcm.googleapis.com.evil.example/test',
                     'https://user@fcm.googleapis.com/test', 'https://fcm.googleapis.com:444/test', 'https://fcm.googleapis.com/test#fragment',
                     'https://[::1]/test', 'https://fcm.googleapis.com:invalid/test'):
        assert client.post('/api/push/subscriptions', json={**payload, 'endpoint': endpoint}).status_code == 422
    for invalid in ({**payload['keys'], 'auth': '!' * 22}, {**payload['keys'], 'auth': push.b64(b'too-long-auth-value')},
                    {**payload['keys'], 'p256dh': push.b64(b'\x04' + b'\x00' * 64)}):
        assert client.post('/api/push/subscriptions', json={**payload, 'keys': invalid}).status_code == 422
    result = client.post('/api/push/test', json={'endpoint': payload['endpoint']})
    assert result.status_code == 202 and result.json()['queued']
    calls = captured(monkeypatch); push.tick(db)
    assert len(calls) == 1 and calls[0]['payload']['user_id'] == owner(db)


def test_corrupt_payload_and_wrong_owner_never_send_or_block_next_job(env, monkeypatch):
    client = account(env); other = account(env, 'other'); db = env[0].state.db
    uid = owner(db); device, _ = subscribe(client); now = int(time.time())
    insert_job(db, uid, device, now, payload={'user_id': owner(db, 'other')})
    corrupt = insert_job(db, uid, device, now)
    with db.connect(write=True) as conn: conn.execute('UPDATE push_outbox SET payload=? WHERE id=?', ('not json', corrupt))
    insert_job(db, uid, device, now)
    calls = captured(monkeypatch); push.tick(db, now)
    assert len(calls) == 1 and [j['state'] for j in jobs(db)] == ['cancelled', 'cancelled', 'accepted']


def test_worker_lease_recovery_and_parallel_ticks_do_not_double_send(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, _ = subscribe(client); insert_job(db, uid, device, now, state='leased', lease_until=now-1, attempts=1)
    entered, release = threading.Event(), threading.Event(); calls = []
    def deliver(*args):
        calls.append(args); entered.set(); assert release.wait(5)
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, 'deliver', deliver)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(push.tick, db, now)
        assert entered.wait(5)
        second = pool.submit(push.tick, db, now); second.result(timeout=5)
        release.set(); first.result(timeout=5)
    assert len(calls) == 1 and jobs(db)[0]['state'] == 'accepted' and jobs(db)[0]['attempts'] == 2


def test_old_worker_response_cannot_overwrite_new_lease_or_user_unsubscribe(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); now = int(time.time())
    device, payload = subscribe(client); jid = insert_job(db, uid, device, now)
    def deliver(*args):
        with db.connect(write=True) as conn:
            conn.execute('UPDATE push_outbox SET lease_until=?,attempts=2 WHERE id=?', (now + 120, jid))
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, 'deliver', deliver); push.tick(db, now)
    assert jobs(db)[0]['state'] == 'leased' and jobs(db)[0]['attempts'] == 2
    def remove(*args):
        assert client.request('DELETE', '/api/push/subscriptions', json={'endpoint': payload['endpoint']}).status_code == 200
        return SimpleNamespace(status_code=201)
    monkeypatch.setattr(push, 'deliver', remove); push.tick(db, now + 121)
    assert not jobs(db)


def external_receipt(db, client, uid, at):
    n = notice(client, 'Synthetic external receipt ' + uuid4().hex)
    with db.connect(write=True) as conn:
        conn.execute('UPDATE notices SET created_at=? WHERE id=?', (at, n['id']))
        conn.execute('INSERT INTO notice_ingest_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (ident(), uid, n['id'], 'source:synthetic:' + uuid4().hex, uuid4().hex, 'Synthetic official source', '', '[]', at, at))
    return n['id']


def test_future_queue_does_not_replace_last_attempted_delivery(env, monkeypatch):
    c=account(env);db=env[0].state.db;uid=owner(db);device,_=subscribe(c);now=int(time.time())
    insert_job(db,uid,device,now);captured(monkeypatch);push.tick(db,now)
    insert_job(db,uid,device,now+3600)
    value=c.get('/api/push/status').json()
    assert value['last_delivery']['state']=='accepted' and value['pending_count']==1


def test_receipts_wait_for_analysis_and_skip_current_nonmatching_drafts(env):
    from app.notice_automation import mark_profile,profile_hash
    c=account(env);db=env[0].state.db;uid=owner(db);now=int(time.time())
    nid=external_receipt(db,c,uid,now-240)
    with db.connect(write=True) as conn:
        profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
        conn.execute('INSERT INTO notice_automation_settings VALUES(?,?,?,1,10,?)',(uid,1,now,now))
        conn.execute("INSERT INTO notice_automation_jobs(id,user_id,notice_id,input_version,profile_hash,state,created_at) VALUES(?,?,?,?,?,'queued',?)",(ident(),uid,nid,1,profile_hash(profile),now-120))
        assert not any(k.startswith('received:') for k in push.candidates(conn,uid,now))
        conn.execute("UPDATE notice_automation_jobs SET state='failed' WHERE notice_id=?",(nid,))
        pending=[v for k,v in push.candidates(conn,uid,now).items() if k.startswith('received:')]
        assert len(pending)==1 and '需要判断' in pending[0]['payload']['body']
        conn.execute("UPDATE notices SET status='draft',draft_version=version,draft=? WHERE id=?",(dumps({'applicability':'not_matching'}),nid))
        mark_profile(conn,nid,uid,1,profile)
        assert not any(k.startswith('received:') for k in push.candidates(conn,uid,now))
        conn.execute("UPDATE notices SET draft=? WHERE id=?",(dumps({'applicability':'matches_known'}),nid))
        matched=[v for k,v in push.candidates(conn,uid,now).items() if k.startswith('received:')]
        assert '符合已知个人条件' in matched[0]['payload']['body']
        # Changing the profile invalidates the old applicability decision.
        updated=json.loads(profile);updated['college']='另一个学院'
        conn.execute('UPDATE users SET profile=? WHERE id=?',(dumps(updated),uid))
        changed=[v for k,v in push.candidates(conn,uid,now).items() if k.startswith('received:')]
        assert '需要判断' in changed[0]['payload']['body']


def test_long_analysis_queue_reports_review_needed_instead_of_disappearing(env):
    from app.notice_automation import profile_hash
    c=account(env);db=env[0].state.db;uid=owner(db);now=int(time.time())
    nid=external_receipt(db,c,uid,now-3600)
    with db.connect(write=True) as conn:
        profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
        conn.execute('INSERT INTO notice_automation_settings VALUES(?,?,?,1,10,?)',(uid,1,now,now))
        conn.execute("INSERT INTO notice_automation_jobs(id,user_id,notice_id,input_version,profile_hash,state,created_at) VALUES(?,?,?,?,?,'queued',?)",(ident(),uid,nid,1,profile_hash(profile),now-1801))
        reminders=[v for k,v in push.candidates(conn,uid,now).items() if k.startswith('received:')]
        assert len(reminders)==1 and '需要判断' in reminders[0]['payload']['body']


def test_external_digest_counts_only_receipts_since_this_device_enabled(env, monkeypatch):
    client = account(env); other = account(env, 'other'); db = env[0].state.db; uid = owner(db)
    device, _ = subscribe(client); start = int(time.time()) // 120 * 120
    with db.connect(write=True) as conn: conn.execute('UPDATE push_devices SET created_at=? WHERE id=?', (start + 40, device))
    external_receipt(db, client, uid, start + 20)
    external_receipt(db, client, uid, start + 60)
    external_receipt(db, client, uid, start + 90)
    external_receipt(db, other, owner(db, 'other'), start + 80)
    notice(client, 'manual only notice never enters external digest')
    calls = captured(monkeypatch); push.tick(db, start + 121)
    assert len(calls) == 1 and calls[0]['payload']['body'].startswith('2 则')
    assert calls[0]['payload']['url'] == '/#notices' and calls[0]['payload']['user_id'] == uid
    push.tick(db, start + 122); assert len(calls) == 1


def test_reenabled_device_does_not_replay_old_digest_and_expired_test(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); device, _ = subscribe(client)
    now = int(time.time()); start = now // 120 * 120
    with db.connect(write=True) as conn: conn.execute('UPDATE push_devices SET created_at=? WHERE id=?', (start, device))
    external_receipt(db, client, uid, start + 5)
    with db.connect(write=True) as conn:
        push.reconcile(conn, uid, start + 10)
        conn.execute('UPDATE push_devices SET created_at=? WHERE id=?', (start + 20, device))
    insert_job(db, uid, device, start - 400)
    calls = captured(monkeypatch); push.tick(db, start + 121)
    assert not calls and all(job['state'] == 'cancelled' for job in jobs(db))


def test_reconciliation_refreshes_payload_before_actual_delivery(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db); device, _ = subscribe(client); now = int(time.time())
    reads = []
    def current(conn, owner_id, stamp):
        reads.append(stamp)
        return {'synthetic': {'due_at': now, 'created_at': now, 'payload': {'user_id': uid, 'title': 'revision-' + str(len(reads)), 'url': '/#tasks'}}}
    monkeypatch.setattr(push, 'candidates', current); calls = captured(monkeypatch)
    push.tick(db, now)
    assert len(calls) == 1 and calls[0]['payload']['title'] == 'revision-2'


def test_push_extension_upgrade_is_additive_but_damaged_schema_is_rejected(env):
    db = env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute('DROP TABLE push_outbox')
    with pytest.raises(ValueError, match='推送记录版本'):
        Database(db.path)


def test_installed_webpush_encrypts_and_uses_our_transport_without_network(env, monkeypatch):
    """Exercise real crypto/signature integration while replacing its only POST."""
    from requests import Response
    client = account(env); db = env[0].state.db; device_id, subscribed = subscribe(client)
    sent = []
    def intercept(self, endpoint, **kwargs):
        sent.append((endpoint, kwargs)); response = Response()
        response.status_code = 201; response._content = b''
        return response
    monkeypatch.setattr(push.PublicPushSession, 'post', intercept)
    with db.connect(write=True) as conn:
        config = push.configuration(conn)
        device = dict(conn.execute('SELECT * FROM push_devices WHERE id=?', (device_id,)).fetchone())
    response = push.deliver(device, {'title': 'Synthetic encryption only', 'body': 'private test message'}, config)
    assert response.status_code == 201 and len(sent) == 1
    endpoint, options = sent[0]
    assert endpoint == subscribed['endpoint']
    assert b'private test message' not in options['data']
    assert options['headers']['content-encoding'] == 'aes128gcm'
    assert options['headers']['Authorization'].startswith('vapid ')
