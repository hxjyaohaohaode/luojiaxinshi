"""Real candidate/reconcile/dispatch regressions for PR #4 notification review.

Only the transport is intercepted: both channels derive their own current
owner-scoped plans and persist their actual delivery/idempotency ledgers.
"""
import json

import pytest

from app import mail_delivery as mail, push_delivery as push
from app.db import ident
from tests.test_mail_delivery import enable
from tests.test_push_delivery import captured, owner, subscribe
from tests.test_schedule import payload
from tests.test_sprint_notifications import preferences, stamp
from tests.test_workflow import account, env, notice
from verification_helpers import CapturedMessages


def channels(env, client, monkeypatch):
    _, settings = enable(env, client)
    subscribe(client)
    return settings, captured(monkeypatch), CapturedMessages()


def tick_both(db, settings, provider, now):
    push.tick(db, now)
    mail.tick(db, settings, provider, now)


def reconcile_both(db, uid, now):
    with db.connect(write=True) as conn:
        push.reconcile(conn, uid, now)
        mail.reconcile(conn, uid, now)


def outbox(db, channel):
    assert channel in {'push', 'mail'}
    with db.connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM ' + channel + '_outbox ORDER BY rowid')]


def accepted_refs(db, channel, field='receipt_refs'):
    return {ref for row in outbox(db, channel) if row['state'] == 'accepted'
            for ref in json.loads(row['payload']).get(field, [])}


def incoming(client, db, uid, at, *, source='review-source'):
    item = notice(client, '合成收件内容，仅用于通知投递边界核验。' + ident())
    with db.connect(write=True) as conn:
        conn.execute('UPDATE notices SET created_at=?,updated_at=? WHERE id=?', (at, at, item['id']))
        conn.execute('INSERT INTO notice_ingest_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (ident(), uid, item['id'], 'wechat:' + source + ':' + item['id'],
                      ident(), '合成授权收件来源', '', '[]', at, at))
    return item


def explicit_route(client, item, target, mode, **other):
    changes = {'receipt_delivery': 'off', 'task_delivery': 'off', 'digest_hour': 9, **other}
    if target == 'notice':
        changes['notice_delivery'] = {item['id']: mode}
    else:
        routes = client.get('/api/notifications/routes').json()['sources']
        assert len(routes) == 1
        changes['source_delivery'] = {routes[0]['id']: mode}
    preferences(client, **changes)


@pytest.mark.parametrize('poll_seconds', [1, 15, 59, 60])
def test_start_time_reminder_survives_poll_grace_in_both_channels(env, monkeypatch, poll_seconds):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    start = stamp('2027-10-20T14:00')
    client.post('/api/arrangements', json=payload(start_date='2027-10-20', end_date='2027-10-20',
        start_time='14:00', end_time='15:00', reminder_minutes=0)).raise_for_status()
    reconcile_both(db, uid, start - 1)
    assert all(len(outbox(db, channel)) == 1 for channel in ('push', 'mail'))
    tick_both(db, settings, provider, start + poll_seconds)
    expected = int(poll_seconds < 60)
    assert len(sent) == len(provider.mail) == expected
    assert all(outbox(db, channel)[0]['state'] == ('accepted' if expected else 'cancelled')
               for channel in ('push', 'mail'))
    tick_both(db, settings, provider, start + poll_seconds + 1)
    assert len(sent) == len(provider.mail) == expected


def test_start_time_grace_does_not_override_quiet_hours_or_expiry(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    preferences(client, quiet_start='13:00', quiet_end='15:00')
    start = stamp('2027-10-20T14:00')
    client.post('/api/arrangements', json=payload(start_date='2027-10-20', end_date='2027-10-20',
        start_time='14:00', end_time='15:00', reminder_minutes=0)).raise_for_status()
    with db.connect() as conn:
        plan = push.candidates(conn, uid, start - 1, include_suppressed=True)
    assert len(plan) == 1 and next(iter(plan.values()))['policy']['suppressed']
    tick_both(db, settings, provider, start + 15)
    assert not sent and not provider.mail


@pytest.mark.parametrize('category_mode', ['off', 'in_app'])
@pytest.mark.parametrize('target', ['notice', 'source'])
@pytest.mark.parametrize('mode', ['immediate', 'digest'])
def test_receipt_route_override_survives_aggregation_in_both_channels(
        env, monkeypatch, category_mode, target, mode):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    at = stamp('2027-10-20T10:00')
    item = incoming(client, db, uid, at + 10)
    explicit_route(client, item, target, mode, receipt_delivery=category_mode)
    due = at + 120 if mode == 'immediate' else stamp('2027-10-21T09:00')
    with db.connect() as conn:
        planned = push.candidates(conn, uid, at + 20)
    assert len(planned) == 1
    event = next(iter(planned.values()))
    assert event['due_at'] == due
    assert {entry['id'] for entry in event['received_items']} == {item['id']}
    reconcile_both(db, uid, at + 20)
    tick_both(db, settings, provider, due - 1)
    assert not sent and not provider.mail
    tick_both(db, settings, provider, due + 1)
    assert len(sent) == len(provider.mail) == 1
    for channel in ('push', 'mail'):
        refs = accepted_refs(db, channel)
        assert len(refs) == 1 and next(iter(refs)).startswith(item['id'] + ':')
    tick_both(db, settings, provider, due + 16)
    assert len(sent) == len(provider.mail) == 1


def test_mixed_receipt_routes_keep_slots_private_and_revoke_digest_before_sending(env, monkeypatch):
    client = account(env); other = account(env, 'other'); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    at = stamp('2027-10-20T10:00')
    immediate = incoming(client, db, uid, at + 10)
    digest = incoming(client, db, uid, at + 20)
    blocked = incoming(client, db, uid, at + 30)
    foreign = incoming(other, db, owner(db, 'other'), at + 40)
    preferences(client, receipt_delivery='off', digest_hour=9,
                notice_delivery={immediate['id']: 'immediate', digest['id']: 'digest'})
    with db.connect() as conn:
        planned = push.candidates(conn, uid, at + 45)
    assert len(planned) == 2
    assert {entry['id'] for event in planned.values() for entry in event['received_items']} == {
        immediate['id'], digest['id']}
    reconcile_both(db, uid, at + 45)
    tick_both(db, settings, provider, at + 121)
    assert len(sent) == len(provider.mail) == 1
    # A stored future digest is not authority: an owner route change must be
    # applied by the real send-time reconcile, including the email channel.
    preferences(client, notice_delivery={immediate['id']: 'immediate', digest['id']: 'off'})
    tick_both(db, settings, provider, stamp('2027-10-21T09:00') + 1)
    assert len(sent) == len(provider.mail) == 1
    for channel in ('push', 'mail'):
        refs = accepted_refs(db, channel)
        assert len(refs) == 1 and next(iter(refs)).startswith(immediate['id'] + ':')
        assert any(row['state'] == 'cancelled' for row in outbox(db, channel))
        assert all(not ref.startswith((digest['id'] + ':', blocked['id'] + ':', foreign['id'] + ':'))
                   for ref in refs)


@pytest.mark.parametrize('target', ['notice', 'source'])
@pytest.mark.parametrize('quiet', [False, True])
def test_unchosen_source_update_digest_is_scheduled_once_and_not_replayed(env, monkeypatch, target, quiet):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    at = stamp('2027-10-20T10:00')
    item = incoming(client, db, uid, at)
    explicit_route(client, item, target, 'digest',
                   quiet_start='22:00' if quiet else '', quiet_end='10:00' if quiet else '')
    client.put('/api/proactive/notices/' + item['id'] + '/feedback',
               json={'notice_version': item['version'], 'version': 0, 'mode': 'include'}).raise_for_status()
    update_id = ident()
    with db.connect(write=True) as conn:
        receipt = conn.execute('SELECT id FROM notice_ingest_receipts WHERE notice_id=?', (item['id'],)).fetchone()[0]
        conn.execute('INSERT INTO notice_ingest_updates(id,notice_id,receipt_id,previous_source_ids,new_source_ids,created_at) VALUES(?,?,?,?,?,?)',
                     (update_id, item['id'], receipt, '[]', '[]', at))
        conn.execute('INSERT INTO notice_delivery_suppressions VALUES(?,?)', (item['id'], 'initial_snapshot'))
        planned = push.candidates(conn, uid, at + 1)
    key = 'intake-change:' + update_id
    assert set(planned) == {key}
    due = stamp('2027-10-21T10:00' if quiet else '2027-10-21T09:00')
    assert planned[key]['due_at'] == due
    assert planned[key]['category'] == 'receipt'
    reconcile_both(db, uid, at + 1)
    tick_both(db, settings, provider, due - 1)
    assert not sent and not provider.mail
    tick_both(db, settings, provider, due + 1)
    assert len(sent) == len(provider.mail) == 1
    assert all(accepted_refs(db, channel, 'event_refs') == {key} for channel in ('push', 'mail'))
    # Switching timing cannot replay the already-accepted underlying update.
    explicit_route(client, item, target, 'immediate')
    tick_both(db, settings, provider, due + 16)
    assert len(sent) == len(provider.mail) == 1
