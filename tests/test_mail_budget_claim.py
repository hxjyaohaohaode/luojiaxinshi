"""Real SQLite queue contention must reserve one budget unit per claimed mail.

Only transport and scheduling boundaries are controlled. Authentication,
outbox reconciliation, quota rows and BEGIN/commit/rollback are production code.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from app import mail_delivery as mail
from app.db import dumps
from tests.test_mail_clock_regressions import queued_mail
from tests.test_mail_delivery import enable
from tests.test_notification_review_regressions import outbox
from tests.test_push_delivery import create_task, due_reminder, owner
from tests.test_sprint_notifications import preferences, stamp
from tests.test_workflow import account, env
from verification_helpers import CapturedMessages


BUDGET = 'mail-reminder-budget'


def quota(db):
    with db.connect() as conn:
        row = conn.execute('SELECT count FROM limits WHERE key=?', (BUDGET,)).fetchone()
        return row['count'] if row else 0


def messages(env, count=1):
    client = account(env)
    app, settings = enable(env, client)
    settings.notification_mail_daily_limit = 2
    for _ in range(count):
        client.post('/api/notifications/email/test').raise_for_status()
    return client, app.state.db, settings, int(time.time()) + 1


def after_first_peek(db, monkeypatch, action):
    """Pause after the actual read connection closes, never fake a DB result."""
    original = db.connect
    local = threading.local()
    selected = []
    lock = threading.Lock()

    class Cursor:
        def __init__(self, cursor, observed):
            self.cursor, self.observed = cursor, observed

        def fetchone(self):
            row = self.cursor.fetchone()
            if row is not None:
                self.observed.append(row['id'])
            return row

    class Connection:
        def __init__(self, connection, observed):
            self.connection, self.observed = connection, observed

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, parameters=()):
            cursor = self.connection.execute(sql, parameters)
            if sql.startswith("SELECT id FROM mail_outbox WHERE state='pending'"):
                return Cursor(cursor, self.observed)
            return cursor

    @contextmanager
    def connect(write=False):
        observed = []
        with original(write=write) as connection:
            yield Connection(connection, observed)
        if observed and not getattr(local, 'paused', False):
            local.paused = True
            with lock:
                selected.extend(observed)
            action(observed[0], original)

    monkeypatch.setattr(db, 'connect', connect)
    return selected


def test_two_dispatch_workers_claim_two_mails_with_only_two_quota_units(env, monkeypatch):
    _, db, settings, now = messages(env, count=2)
    both_read = threading.Barrier(2)
    selected = after_first_peek(db, monkeypatch, lambda *_: both_read.wait(timeout=10))
    provider = CapturedMessages()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mail.tick, db, settings, provider, now) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    assert len(selected) == 2 and selected[0] == selected[1], 'Both workers really selected the same pending row'
    assert len(provider.mail) == 2, 'A losing claimant must leave quota for the second eligible message'
    assert [row['state'] for row in outbox(db, 'mail')] == ['accepted', 'accepted']
    assert quota(db) == 2
    mail.tick(db, settings, provider, now + 120)
    assert len(provider.mail) == quota(db) == 2


@pytest.mark.parametrize('claimed_state', ['sending', 'accepted', 'uncertain'])
def test_a_job_claimed_after_the_peek_never_reserves_a_second_unit(env, monkeypatch, claimed_state):
    _, db, settings, now = messages(env)
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,1,?)', (BUDGET, int(time.time()) + 86400))

    def another_claim(jid, original):
        with original(write=True) as conn:
            conn.execute('UPDATE mail_outbox SET state=?,lease_until=?,finished_at=? WHERE id=?',
                         (claimed_state, now + 300, now, jid))

    after_first_peek(db, monkeypatch, another_claim)
    provider = CapturedMessages()
    mail.tick(db, settings, provider, now)
    assert not provider.mail
    assert outbox(db, 'mail')[0]['state'] == claimed_state
    assert quota(db) == 1, 'The existing claimant already owns this quota unit'


@pytest.mark.parametrize('change', ['consent', 'contact', 'owner_deleted', 'row_deleted', 'future_due'])
def test_validation_skips_after_peek_do_not_spend_the_mail_budget(env, monkeypatch, change):
    client, db, settings, now = messages(env)
    uid = client.get('/api/session').json()['user']['id']

    def invalidate(jid, original):
        if change == 'consent':
            client.put('/api/notifications/email', json={'enabled': False}).raise_for_status()
            return
        with original(write=True) as conn:
            if change == 'contact':
                conn.execute("UPDATE verified_contacts SET value='changed@example.invalid' WHERE user_id=? AND channel='email'", (uid,))
            elif change == 'owner_deleted':
                conn.execute('DELETE FROM users WHERE id=?', (uid,))
            elif change == 'row_deleted':
                conn.execute('DELETE FROM mail_outbox WHERE id=?', (jid,))
            else:
                conn.execute('UPDATE mail_outbox SET due_at=? WHERE id=?', (now + 3600, jid))

    after_first_peek(db, monkeypatch, invalidate)
    provider = CapturedMessages()
    mail.tick(db, settings, provider, now)
    assert not provider.mail
    assert quota(db) == 0, 'No sendable claim was made after the current-state check'
    rows = outbox(db, 'mail')
    if change in {'owner_deleted', 'row_deleted'}:
        assert rows == []
    else:
        assert rows[0]['state'] == ('pending' if change == 'future_due' else 'cancelled')


@pytest.mark.parametrize('change', ['expiry', 'quiet'])
def test_actual_arrangement_ineligible_after_peek_keeps_quota_unspent(env, monkeypatch, change):
    client, db, settings, clock, start = queued_mail(env, monkeypatch, first=False)

    def invalidate(*_):
        if change == 'expiry':
            clock[0] = start + 61
        else:
            preferences(client, quiet_start='14:00', quiet_end='15:00')

    after_first_peek(db, monkeypatch, invalidate)
    provider = CapturedMessages()
    mail.tick(db, settings, provider)
    assert not provider.mail
    assert outbox(db, 'mail')[0]['state'] == 'cancelled'
    assert quota(db) == 0


def test_exhausted_budget_leaves_the_job_pending_without_a_sending_lease(env):
    _, db, settings, now = messages(env)
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,2,?)', (BUDGET, int(time.time()) + 86400))
    provider = CapturedMessages()
    mail.tick(db, settings, provider, now)
    row = outbox(db, 'mail')[0]
    assert not provider.mail and quota(db) == 2
    assert row['state'] == 'pending' and row['lease_until'] == 0
    assert row['error'] == '今日邮件额度已用完，等待额度恢复'


def test_expired_budget_window_is_replaced_once_for_a_successful_claim(env):
    _, db, settings, now = messages(env)
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,2,0)', (BUDGET,))
    provider = CapturedMessages()
    mail.tick(db, settings, provider, now)
    assert len(provider.mail) == quota(db) == 1
    assert outbox(db, 'mail')[0]['state'] == 'accepted'


def test_an_ambiguous_provider_attempt_keeps_its_unit_and_never_replays(env):
    _, db, settings, now = messages(env)

    class Ambiguous(CapturedMessages):
        def send_mail(self, *args):
            super().send_mail(*args)
            raise TimeoutError('synthetic provider timeout after submission')

    provider = Ambiguous()
    mail.tick(db, settings, provider, now)
    assert len(provider.mail) == quota(db) == 1
    assert outbox(db, 'mail')[0]['state'] == 'uncertain'
    mail.tick(db, settings, provider, now + 120)
    assert len(provider.mail) == quota(db) == 1


def test_claim_database_failure_rolls_back_the_budget_with_the_claim(env):
    _, db, settings, now = messages(env)
    with db.connect(write=True) as conn:
        conn.execute("""CREATE TRIGGER reject_mail_claim BEFORE UPDATE OF state ON mail_outbox
            WHEN NEW.state='sending' BEGIN SELECT RAISE(ABORT,'synthetic claim failure'); END""")
    provider = CapturedMessages()
    with pytest.raises(sqlite3.IntegrityError, match='synthetic claim failure'):
        mail.tick(db, settings, provider, now)
    assert not provider.mail
    assert outbox(db, 'mail')[0]['state'] == 'pending'
    assert quota(db) == 0, 'The real SQLite rollback must undo quota as well as the rejected claim'
    with db.connect(write=True) as conn:
        conn.execute('DROP TRIGGER reject_mail_claim')
    mail.tick(db, settings, provider, now)
    assert len(provider.mail) == quota(db) == 1
    assert outbox(db, 'mail')[0]['state'] == 'accepted'


def after_real_budget(monkeypatch, action):
    # The fallback lets the same regression run against the pre-fix worker:
    # its real quota transaction still executes before the controlled delay.
    name = 'rate_limit_connection' if hasattr(mail, 'rate_limit_connection') else 'rate_limit'
    budget = getattr(mail, name)
    calls = []

    def delayed(*args, **kwargs):
        try:
            return budget(*args, **kwargs)
        finally:
            calls.append(True)
            action(len(calls))

    monkeypatch.setattr(mail, name, delayed)
    return calls


def quiet_reminder(env, monkeypatch):
    client = account(env); db = env[0].state.db
    before = stamp('2027-10-20T21:59:30'); clock = [before - 10]
    monkeypatch.setattr(mail, 'time', SimpleNamespace(time=lambda: clock[0]))
    _, settings = enable(env, client)
    clock[0] = before
    preferences(client, quiet_start='22:00', quiet_end='08:00')
    _, tid = create_task(client); due_reminder(db, tid, before)
    with db.connect(write=True) as conn:
        mail.reconcile(conn, owner(db), before)
    return client, db, settings, clock


def test_budget_delay_into_quiet_preserves_reschedule_without_spending_quota(env, monkeypatch):
    _, db, settings, clock = quiet_reminder(env, monkeypatch)
    calls = after_real_budget(monkeypatch, lambda n: clock.__setitem__(0, stamp('2027-10-20T22:00:01')) if n == 1 else None)
    provider = CapturedMessages(); mail.tick(db, settings, provider)
    assert calls == [True] and not provider.mail
    row = outbox(db, 'mail')[0]
    assert row['state'] == 'pending' and row['due_at'] == stamp('2027-10-21T08:00')
    assert row['error'] == '' and quota(db) == 0
    clock[0] = stamp('2027-10-21T08:00:01')
    # The first-budget delay must not move a later send into yesterday's quiet.
    mail.tick(db, settings, provider, now=clock[0])
    assert len(provider.mail) == quota(db) == 1


def test_expiry_after_budget_returns_only_this_unit_of_the_existing_window(env, monkeypatch):
    _, db, settings, clock, start = queued_mail(env, monkeypatch, first=False)
    reset = start + 3600
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,1,?)', (BUDGET, reset))
    calls = after_real_budget(monkeypatch, lambda _: clock.__setitem__(0, start + 61))
    provider = CapturedMessages(); mail.tick(db, settings, provider)
    assert calls == [True] and not provider.mail
    assert outbox(db, 'mail')[0]['state'] == 'cancelled'
    with db.connect() as conn:
        row = conn.execute('SELECT count,reset_at FROM limits WHERE key=?', (BUDGET,)).fetchone()
    assert tuple(row) == (1, reset), 'Keep the prior spent unit and its actual stored window'


@pytest.mark.parametrize('change', ['expiry', 'quiet'])
def test_exhausted_budget_delay_reconciles_before_labelling_the_pending_job(env, monkeypatch, change):
    if change == 'expiry':
        _, db, settings, clock, start = queued_mail(env, monkeypatch, first=False)
        after = start + 61
    else:
        _, db, settings, clock = quiet_reminder(env, monkeypatch)
        after = stamp('2027-10-20T22:00:01')
    settings.notification_mail_daily_limit = 2
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,2,?)', (BUDGET, clock[0] + 86400))
    calls = after_real_budget(monkeypatch, lambda _: clock.__setitem__(0, after))
    provider = CapturedMessages(); mail.tick(db, settings, provider)
    assert calls == [True] and not provider.mail and quota(db) == 2
    row = outbox(db, 'mail')[0]
    assert row['state'] == ('cancelled' if change == 'expiry' else 'pending')
    if change == 'quiet':
        assert row['due_at'] == stamp('2027-10-21T08:00')
    assert row['error'] == '', 'Expired or quiet-delayed work must not get a stale budget error'


def test_clock_crossing_the_quota_window_retries_in_the_new_window(env, monkeypatch):
    _, db, settings, now = messages(env)
    clock = [now]
    monkeypatch.setattr(mail, 'time', SimpleNamespace(time=lambda: clock[0]))
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO limits VALUES(?,1,?)', (BUDGET, now))
    calls = after_real_budget(monkeypatch, lambda n: clock.__setitem__(0, now + 1) if n == 1 else None)
    provider = CapturedMessages(); mail.tick(db, settings, provider)
    assert calls == [True, True]
    assert len(provider.mail) == quota(db) == 1
    row = outbox(db, 'mail')[0]
    assert row['state'] == 'accepted' and row['finished_at'] == now + 1
    with db.connect() as conn:
        assert conn.execute('SELECT reset_at FROM limits WHERE key=?', (BUDGET,)).fetchone()[0] == now + 1 + 86400


@pytest.mark.parametrize('invalid', ['owner', 'json'])
def test_invalid_payload_is_not_submitted_charged_or_replayed(env, invalid):
    _, db, settings, now = messages(env)
    with db.connect(write=True) as conn:
        body = dumps({'user_id': 'another-owner', 'body': 'must not leave this account'}) if invalid == 'owner' else '{broken'
        conn.execute('UPDATE mail_outbox SET payload=?', (body,))
    provider = CapturedMessages(); mail.tick(db, settings, provider, now)
    assert not provider.mail and quota(db) == 0
    row = outbox(db, 'mail')[0]
    assert row['state'] == 'uncertain' and '未提交' in row['error']
    mail.tick(db, settings, provider, now + 120)
    assert not provider.mail and quota(db) == 0
