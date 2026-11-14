"""Late real queue dispatch must obey the current quiet window on both channels."""
import pytest

from app.db import dumps, ident
from tests.test_notification_review_regressions import (
    accepted_refs, channels, incoming, outbox, reconcile_both, tick_both,
)
from tests.test_push_delivery import create_task, due_reminder, owner
from tests.test_schedule import payload
from tests.test_sprint_notifications import preferences, stamp
from tests.test_workflow import account, env


@pytest.mark.parametrize('kind', ['reminder', 'receipt'])
def test_late_delivery_waits_for_current_quiet_end_and_still_sends_once(env, monkeypatch, kind):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    preferences(client, quiet_start='22:00', quiet_end='08:00')
    before = stamp('2027-10-20T21:59:30')
    if kind == 'reminder':
        _, tid = create_task(client)
        due_reminder(db, tid, before)
    else:
        incoming(client, db, uid, stamp('2027-10-20T21:57:10'))
    reconcile_both(db, uid, before)
    assert all(len(outbox(db, channel)) == 1 for channel in ('push', 'mail'))
    # The original due time preceded quiet hours, but dispatch happens inside
    # them after a delayed worker wake-up. No transport is called at this time.
    tick_both(db, settings, provider, stamp('2027-10-20T22:00:01'))
    assert not sent and not provider.mail
    end = stamp('2027-10-21T08:00')
    for channel in ('push', 'mail'):
        current = [row for row in outbox(db, channel) if row['state'] == 'pending']
        assert len(current) == 1 and current[0]['due_at'] == end
    tick_both(db, settings, provider, end + 1)
    assert len(sent) == len(provider.mail) == 1
    tick_both(db, settings, provider, end + 16)
    assert len(sent) == len(provider.mail) == 1


def test_late_quiet_deferral_cancels_an_arrangement_past_its_valid_window(env, monkeypatch):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    preferences(client, quiet_start='22:00', quiet_end='08:00')
    client.post('/api/arrangements', json=payload(start_date='2027-10-20', end_date='2027-10-20',
        start_time='22:01', end_time='23:00', reminder_minutes=2)).raise_for_status()
    reconcile_both(db, uid, stamp('2027-10-20T21:59:30'))
    tick_both(db, settings, provider, stamp('2027-10-20T22:00:01'))
    assert not sent and not provider.mail
    assert all(outbox(db, channel)[0]['state'] == 'cancelled' for channel in ('push', 'mail'))
    tick_both(db, settings, provider, stamp('2027-10-21T08:00:01'))
    assert not sent and not provider.mail


@pytest.mark.parametrize('allow_urgent', [False, True])
def test_late_formal_change_only_bypasses_quiet_with_current_explicit_opt_in(env, monkeypatch, allow_urgent):
    client = account(env); db = env[0].state.db; uid = owner(db)
    settings, sent, provider = channels(env, client, monkeypatch)
    preferences(client, quiet_start='22:00', quiet_end='08:00', allow_urgent_during_quiet=allow_urgent)
    nid, tid = create_task(client)
    before = stamp('2027-10-20T21:59:30')
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO notice_changes VALUES(?,?,?,?,?,?,?,?)',
                     (ident(), nid, uid, dumps({'kind': 'correction', 'targets': [{'task_id': tid}]}),
                      'pending', 1, before, before))
    reconcile_both(db, uid, before)
    tick_both(db, settings, provider, stamp('2027-10-20T22:00:01'))
    assert len(sent) == len(provider.mail) == int(allow_urgent)
    preferences(client, allow_urgent_during_quiet=False)
    tick_both(db, settings, provider, stamp('2027-10-21T08:00:01'))
    assert len(sent) == len(provider.mail) == 1
    assert all(len(accepted_refs(db, channel, 'event_refs')) == 1 for channel in ('push', 'mail'))
