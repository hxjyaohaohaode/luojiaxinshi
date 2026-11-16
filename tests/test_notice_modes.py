import json

import pytest

from app.config import Settings
from app.model_catalog import TOKEN_PLAN,notice_processing_modes,notice_settings
from test_workflow import env,account,notice
from test_notice_semantics import install_provider


@pytest.mark.parametrize('mode',['configured','fast','daily'])
def test_request_selects_both_models_with_bounded_review_and_immutable_configuration(env,monkeypatch,mode):
    fast='mimo-v2.6-pro-ultraspeed'
    c,n,seen=install_provider(env,monkeypatch,expected_review_model=fast if mode=='fast' else 'mimo-v2.6-flash' if mode=='daily' else None,
        expected_thinking='disabled' if mode=='daily' else 'enabled',expected_output=32768 if mode=='daily' else None)
    cfg=env[1];cfg.notice_fast_enabled=True
    before=(cfg.ai_model,cfg.notice_review_model)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True,'processing_mode':mode})
    assert response.status_code==200,response.text
    expected=[fast,fast] if mode=='fast' else ['mimo-v2.6-flash']*2 if mode=='daily' else list(before)
    assert [p['model'] for p in seen]==expected
    assert (cfg.ai_model,cfg.notice_review_model)==before
    metrics=c.get('/api/executions').json()['items'][0]['metrics']
    assert [call['model'] for call in metrics['calls']]==expected and metrics['call_count']==2
    assert response.json()['calls'][0]['model']==expected[0]
    with env[0].state.db.connect() as conn:
        consent=json.loads(conn.execute("SELECT after_json FROM audit WHERE action='ai_processing_consent'").fetchone()[0])
    assert consent['processing_mode']==mode and consent['model']==expected[0] and consent['review_model']==expected[1]
    assert consent['maximum_requests']==2
    assert [p['thinking']['type'] for p in seen]==['disabled' if mode=='daily' else 'enabled']*2
    assert cfg.notice_thinking=='enabled' and cfg.ai_output_tokens==131072
    if mode=='daily':assert all(p['temperature']==0.1 and p['top_p']==0.8 for p in seen)
    else:assert all('temperature' not in p and 'top_p' not in p for p in seen)


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
    assert [x['id'] for x in notice_processing_modes(cfg)]==['configured','daily']
    cfg.notice_fast_enabled=True
    modes=notice_processing_modes(cfg);assert [x['id'] for x in modes]==['configured','daily','fast']
    assert '30' in modes[-1]['price_note'] and '60' in modes[-1]['price_note']
    fast=notice_settings(cfg,'fast');assert fast is not cfg and cfg.ai_model=='mimo-v2.6-pro'
    assert fast.notice_semantic_review==cfg.notice_semantic_review
    cfg.ai_base_url=TOKEN_PLAN
    assert [x['id'] for x in notice_processing_modes(cfg)]==['configured','daily']
    with pytest.raises(ValueError):notice_settings(cfg,'fast')


def test_disabled_review_is_described_without_promising_a_second_call(tmp_path):
    cfg=Settings(tmp_path,notice_fast_enabled=True,notice_semantic_review=False)
    modes=notice_processing_modes(cfg)
    assert len(modes)==2
    for mode in modes:
        assert mode['review_model'] is None and '复核已由维护者关闭' in mode['description']
    assert not notice_settings(cfg,'fast').notice_semantic_review
    with pytest.raises(ValueError):notice_settings(cfg,'daily')
    cfg.notice_semantic_review=True;cfg.notice_daily_enabled=False
    assert 'daily' not in [mode['id'] for mode in notice_processing_modes(cfg)]
    with pytest.raises(ValueError):notice_settings(cfg,'daily')


def test_notice_specific_context_leaves_chat_budget_unchanged(tmp_path):
    from app.ai import AIError,prepare_notice_input
    from app.documents import text_source
    cfg=Settings(tmp_path,ai_context_tokens=32768,notice_context_tokens=1000000)
    run=notice_settings(cfg,'configured')
    assert cfg.ai_context_tokens==32768 and run.ai_context_tokens==1000000
    notice={'source_label':'测试来源','published_at':None,'materials_complete':False}
    _,_,content=prepare_notice_input(run,notice,[text_source('原文开头'+('甲'*12000)+'原文结尾')],{})
    assert '原文结尾' in content
    cfg.notice_context_tokens=None
    with pytest.raises(AIError,match='输出预算不小于上下文容量'):
        prepare_notice_input(notice_settings(cfg,'configured'),notice,[text_source('正文')],{})
