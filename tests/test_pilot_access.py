from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.security import new_invite
from test_workflow import env, account, PASSWORD, ORIGIN


def test_invited_pilot_blocks_public_signup_without_locking_out_existing_users(env):
    app, settings = env
    account(env)
    settings.registration_mode = 'invite'
    client = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Requested-With': 'campus-notice'})
    assert client.get('/api/auth/policy').json() == {'registration_mode': 'invite'}
    body = {'username': 'newmember', 'display_name': '受邀试点', 'password': PASSWORD, 'accepted_terms': True}
    assert client.post('/api/auth/register', json=body).status_code == 403
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1


def test_invitation_policy_checks_token_role_and_one_time_use(env):
    app, settings = env; settings.registration_mode = 'invite'
    client = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN, 'X-Requested-With': 'campus-notice'})
    body = {'username': 'newmember', 'display_name': '受邀试点', 'password': PASSWORD, 'accepted_terms': True}
    assert client.post('/api/auth/register', json={**body, 'invite': 'invalid'}).status_code == 400
    token = new_invite(app.state.db)
    assert client.post('/api/auth/register', json={**body, 'invite': token}).status_code == 200
    assert client.get('/api/session').json()['user']['role'] == 'user'
    assert client.post('/api/auth/register', json={**body, 'username': 'secondmember', 'invite': token}).status_code == 400


def test_registration_policy_rejects_unknown_configuration(monkeypatch):
    monkeypatch.setenv('REGISTRATION_MODE', 'unlisted')
    with pytest.raises(ValueError, match='REGISTRATION_MODE'):
        Settings.from_env()
