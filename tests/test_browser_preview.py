import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app, RequestGuard
from test_workflow import env, ORIGIN


def test_annotation_css_hash_is_local_and_scripts_stay_restricted(env):
    app,_=env
    policy=TestClient(app,base_url=ORIGIN).get('/').headers['content-security-policy']
    assert "style-src 'self' 'sha256-WO55anZ1V8A0G22bY2t72RV4dI79SLI4VnYLgsEeWUc='" in policy
    assert "'sha256-62lPaUtpvg47KrxPOXYc0Ki8fkE6PNsbY5I9DpyEwZ4='" in policy
    assert "script-src 'self';" in policy
    assert 'unsafe-inline' not in policy and 'unsafe-eval' not in policy
    assert b'sha256-' not in RequestGuard(None,'http://192.168.1.2:8765',False).csp


@pytest.mark.parametrize('origin,production,allowed', [
    ('http://localhost:8765', False, True),
    ('http://127.0.0.1:8765', False, True),
    ('http://[::1]:8765', False, True),
    ('https://localhost', True, False),
    ('https://127.0.0.1', True, False),
    ('https://campus.example', False, False),
    ('http://localhost.example:8765', False, False),
])
def test_annotation_styles_are_limited_to_local_preview(origin, production, allowed):
    policy=RequestGuard(None,origin,production).csp.decode('ascii')
    assert ("'sha256-62lPaUtpvg47KrxPOXYc0Ki8fkE6PNsbY5I9DpyEwZ4='" in policy) is allowed
    assert "script-src 'self';" in policy
    assert 'unsafe-inline' not in policy and 'unsafe-eval' not in policy


def test_production_retains_strict_style_policy(tmp_path):
    app=create_app(Settings(tmp_path/'prod',origin='https://campus.example',production=True))
    with TestClient(app,base_url='https://campus.example') as client:
        policy=client.get('/').headers['content-security-policy']
        assert "style-src 'self';" in policy and 'sha256-' not in policy
        assert client.get('/api/ui-review/annotations').status_code==404
