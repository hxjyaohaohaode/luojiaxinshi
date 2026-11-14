"""Dispatch-time clock checks through the actual email queue and candidates."""
from types import SimpleNamespace

import pytest

from app import mail_delivery as mail
from tests.test_mail_delivery import enable
from tests.test_notification_review_regressions import outbox
from tests.test_push_delivery import owner
from tests.test_schedule import payload
from tests.test_sprint_notifications import preferences, stamp
from tests.test_workflow import account, env
from verification_helpers import CapturedMessages


def queued_mail(env, monkeypatch, *, first=True):
    client = account(env); db = env[0].state.db; uid = owner(db)
    start = stamp('2027-10-20T14:00')
    clock = [start - 1]
    # Replace only mail's clock, not process-wide time or any business data.
    monkeypatch.setattr(mail, 'time', SimpleNamespace(time=lambda: clock[0]))
    _, settings = enable(env, client)
    if first:
        client.post('/api/notifications/email/test').raise_for_status()
    client.post('/api/arrangements', json=payload(title='有一分钟有效窗口的安排',
        start_date='2027-10-20', end_date='2027-10-20', start_time='14:00',
        end_time='15:00', reminder_minutes=0)).raise_for_status()
    clock[0] = start + 59
    with db.connect(write=True) as conn:
        mail.reconcile(conn, uid, clock[0])
    return client, db, settings, clock, start


def provider_advances_clock(clock, after_first=None, *, uncertain=False):
    class Provider(CapturedMessages):
        def send_mail(self, destination, subject, body):
            receipt = super().send_mail(destination, subject, body)
            if len(self.mail) == 1:
                clock[0] += 2
                if after_first:
                    after_first()
                if uncertain:
                    raise TimeoutError('synthetic ambiguous provider result')
            return receipt
    return Provider()


def test_live_mail_tick_rechecks_expiry_after_the_previous_provider_returns(env, monkeypatch):
    client, db, settings, clock, start = queued_mail(env, monkeypatch)
    provider = provider_advances_clock(clock)
    mail.tick(db, settings, provider)
    assert len(provider.mail) == 1, 'The second SMTP submission must not use the batch start timestamp'
    rows = outbox(db, 'mail')
    assert [row['state'] for row in rows] == ['accepted', 'cancelled']
    assert rows[0]['finished_at'] == start + 61
    mail.tick(db, settings, provider)
    assert len(provider.mail) == 1


def test_live_mail_tick_rechecks_expiry_after_real_budget_accounting(env, monkeypatch):
    client, db, settings, clock, start = queued_mail(env, monkeypatch, first=False)
    budget = mail.rate_limit_connection
    calls = []
    def delayed_budget(*args, **kwargs):
        result = budget(*args, **kwargs)
        calls.append(True)
        clock[0] = start + 61
        return result
    monkeypatch.setattr(mail, 'rate_limit_connection', delayed_budget)
    provider = CapturedMessages()
    mail.tick(db, settings, provider)
    assert calls == [True]
    assert not provider.mail, 'Budget/write-lock waiting must precede the final expiry check'
    assert outbox(db, 'mail')[0]['state'] == 'cancelled'
    with db.connect() as conn:
        assert conn.execute("SELECT count FROM limits WHERE key='mail-reminder-budget'").fetchone() is None


def test_explicit_mail_now_keeps_its_fixed_simulation_semantics(env, monkeypatch):
    client, db, settings, clock, start = queued_mail(env, monkeypatch)
    provider = provider_advances_clock(clock)
    mail.tick(db, settings, provider, now=start + 59)
    assert len(provider.mail) == 2
    assert all(row['state'] == 'accepted' and row['finished_at'] == start + 59
               for row in outbox(db, 'mail'))
    mail.tick(db, settings, provider, now=start + 59)
    assert len(provider.mail) == 2


@pytest.mark.parametrize('change', ['consent', 'quiet'])
def test_mail_rechecks_owner_consent_and_new_quiet_settings_before_the_next_send(env, monkeypatch, change):
    client, db, settings, clock, start = queued_mail(env, monkeypatch)
    def update():
        if change == 'consent':
            client.put('/api/notifications/email', json={'enabled': False}).raise_for_status()
        else:
            preferences(client, quiet_start='14:00', quiet_end='15:00')
        # Keep the next arrangement inside the grace window, so suppression
        # must come from current consent/quiet preferences rather than expiry.
        clock[0] = start + 59
    provider = provider_advances_clock(clock, update)
    mail.tick(db, settings, provider)
    assert len(provider.mail) == 1
    assert [row['state'] for row in outbox(db, 'mail')] == ['accepted', 'cancelled']


def test_live_mail_clock_does_not_replay_ambiguous_provider_submission(env, monkeypatch):
    client, db, settings, clock, start = queued_mail(env, monkeypatch)
    provider = provider_advances_clock(clock, uncertain=True)
    mail.tick(db, settings, provider)
    assert len(provider.mail) == 1
    rows = outbox(db, 'mail')
    assert [row['state'] for row in rows] == ['uncertain', 'cancelled']
    assert rows[0]['finished_at'] == start + 61
    clock[0] += 120
    mail.tick(db, settings, provider)
    assert len(provider.mail) == 1
