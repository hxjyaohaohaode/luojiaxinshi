import json

import pytest

from app.config import Settings
from app.model_catalog import TOKEN_PLAN,notice_processing_modes,notice_settings
from test_workflow import env,account,notice
from test_notice_semantics import install_provider


@pytest.mark.parametrize('mode',['configured','fast'])
def test_request_selects_both_models_with_bounded_review_and_immutable_configuration(env,monkeypatch,mode):
    fast='mimo-v2.6-pro-ultraspeed'
    c,n,seen=install_provider(env,monkeypatch,expected_review_model=fast if mode=='fast' else None)
    cfg=env[1];cfg.notice_fast_enabled=True
    before=(cfg.ai_model,cfg.notice_review_model)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True,'processing_mode':mode})
    assert response.status_code==200,response.text
    expected=[fast,fast] if mode=='fast' else list(before)
    assert [p['model'] for p in seen]==expected
    assert (cfg.ai_model,cfg.notice_review_model)==before
    metrics=c.get('/api/executions').json()['items'][0]['metrics']
    assert [call['model'] for call in metrics['calls']]==expected and metrics['call_count']==2
    assert response.json()['calls'][0]['model']==expected[0]
    with env[0].state.db.connect() as conn:
        consent=json.loads(conn.execute("SELECT after_json FROM audit WHERE action='ai_processing_consent'").fetchone()[0])
    assert consent['processing_mode']==mode and consent['model']==expected[0] and consent['review_model']==expected[1]
    assert consent['maximum_requests']==2


@pytest.mark.parametrize('mode,enabled,base',[('fast',False,None),('invented',True,None),('fast',True,TOKEN_PLAN)])
def test_unavailable_mode_rejected_before_attempt_or_existing_notice_changes(env,monkeypatch,mode,enabled,base):
    c=account(env);n=notice(c);cfg=env[1];cfg.ai_api_key='synthetic';cfg.notice_fast_enabled=enabled
    if base:cfg.ai_base_url=base
    from app import ai
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('disallowed mode must not reach a provider'))
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True,'processing_mode':mode})
    assert response.status_code==422,response.text
    current=c.get('/api/notices/'+n['id']).json()
    assert current['version']==n['version'] and current['status']==n['status'] and not current['calls']
    with env[0].state.db.connect() as conn:assert not conn.execute("SELECT 1 FROM limits WHERE key LIKE 'ai:%'").fetchone()


def test_fast_option_is_owner_enabled_and_never_crosses_subscription_channel(tmp_path):
    cfg=Settings(tmp_path)
    assert [x['id'] for x in notice_processing_modes(cfg)]==['configured']
    cfg.notice_fast_enabled=True
    modes=notice_processing_modes(cfg);assert [x['id'] for x in modes]==['configured','fast']
    assert '30' in modes[1]['price_note'] and '60' in modes[1]['price_note']
    fast=notice_settings(cfg,'fast');assert fast is not cfg and cfg.ai_model=='mimo-v2.6-pro'
    assert fast.notice_semantic_review==cfg.notice_semantic_review
    cfg.ai_base_url=TOKEN_PLAN
    assert [x['id'] for x in notice_processing_modes(cfg)]==['configured']
    with pytest.raises(ValueError):notice_settings(cfg,'fast')


def test_disabled_review_is_described_without_promising_a_second_call(tmp_path):
    cfg=Settings(tmp_path,notice_fast_enabled=True,notice_semantic_review=False)
    modes=notice_processing_modes(cfg)
    assert len(modes)==2
    for mode in modes:
        assert mode['review_model'] is None and '复核已由维护者关闭' in mode['description']
    assert not notice_settings(cfg,'fast').notice_semantic_review
