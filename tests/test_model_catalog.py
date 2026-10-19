import pytest

from app.config import Settings
from app.model_catalog import PAYG,TOKEN_PLAN,TEXT_MODELS,validate,public_configuration
from test_workflow import env,account


@pytest.mark.parametrize('model',sorted(TEXT_MODELS))
def test_current_text_models_have_explicit_adapters(tmp_path,model):
    cfg=Settings(tmp_path,ai_model=model,ai_composition_model=model)
    validate(cfg)
    assert public_configuration(cfg)['model']==model


@pytest.mark.parametrize('base,key,model',[
    (PAYG,'tp-synthetic','mimo-v2.6-pro'),(TOKEN_PLAN,'sk-synthetic','mimo-v2.6-pro'),
    (TOKEN_PLAN,'tp-synthetic','mimo-v2.6-pro-ultraspeed'),(PAYG,'sk-synthetic','mimo-v2.5-pro'),
    ('https://api.xiaomimimo.com.evil.invalid/v1','sk-synthetic','mimo-v2.6-pro'),
    ('https://user@api.xiaomimimo.com/v1','sk-synthetic','mimo-v2.6-pro'),
    ('https://api.xiaomimimo.com/v1?redirect=1','sk-synthetic','mimo-v2.6-pro')])
def test_mismatched_credentials_models_and_hosts_are_rejected(tmp_path,base,key,model):
    with pytest.raises(ValueError):validate(Settings(tmp_path,ai_base_url=base,ai_api_key=key,ai_model=model))


def test_token_plan_configuration_is_separate_and_never_reveals_credentials(tmp_path):
    cfg=Settings(tmp_path,ai_base_url=TOKEN_PLAN,ai_api_key='ttp-synthetic-secret')
    validate(cfg);public=public_configuration(cfg)
    assert public['billing_channel']=='token_plan' and not public['speech_available']
    assert 'mimo-v2.6-pro-ultraspeed' not in public['available_text_models']
    assert cfg.ai_api_key not in str(public)


def test_session_explains_billing_channel_and_keeps_credentials_server_side(env):
    env[1].ai_api_key='sk-synthetic-secret';c=account(env)
    ai=c.get('/api/session').json()['ai']
    assert ai['billing_channel']=='pay_as_you_go' and ai['catalog_verified_at']=='2026-10-18'
    assert env[1].ai_api_key not in str(ai)
