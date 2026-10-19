"""Complete-input rejection happens locally, before provider calls or quota use."""
import io

from PIL import Image
import pytest

from app import ai
from app.config import Settings
from app.visual_evidence import estimated_image_tokens
from test_workflow import env, account, notice, manual, raw_ai


def picture(size):
    out=io.BytesIO()
    Image.new('RGB',size,'white').save(out,format='PNG')
    return out.getvalue()


@pytest.mark.parametrize('size,tokens',[((1024,1024),1024),((64,64),9),((4000,3000),8112)])
def test_documented_image_scaling_examples(size,tokens):
    assert estimated_image_tokens(picture(size))==tokens


def test_preflight_preserves_draft_originals_and_daily_attempt(env,monkeypatch):
    client=account(env);n=manual(client,notice(client))
    cfg=env[1];cfg.ai_api_key='synthetic-budget-key';cfg.notice_input_tokens=4096;cfg.ai_daily_limit=1
    def forbidden(*args):raise AssertionError('over-budget input must not reach a provider')
    monkeypatch.setattr(ai,'generate',forbidden)
    payload={'version':n['version'],'allow_external_processing':True}
    response=client.post(f"/api/notices/{n['id']}/generate",json=payload)
    assert response.status_code==422 and '未发送' in response.text
    after=client.get('/api/notices/'+n['id']).json()
    for field in ('version','draft','sources','status'):
        assert after[field]==n[field]
    assert after['calls']==[]
    with env[0].state.db.connect() as conn:
        assert not conn.execute("SELECT 1 FROM limits WHERE key LIKE 'ai:%'").fetchone()
    # The same unchanged notice can be retried after an intentional budget adjustment.
    cfg.notice_input_tokens=65536
    monkeypatch.setattr(ai,'generate',lambda *args:(raw_ai(n),{'input_tokens':123,'output_tokens':456}))
    assert client.post(f"/api/notices/{n['id']}/generate",json=payload).status_code==200


def test_many_short_paragraphs_count_locators_and_json_overhead(env,monkeypatch):
    client=account(env);body='甲\n'*4500;n=notice(client,text=body)
    env[1].ai_api_key='synthetic-budget-key'
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('metadata budget must reject before generation'))
    response=client.post(f"/api/notices/{n['id']}/generate",json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==422 and '输入估算' in response.text
    saved=client.get('/api/notices/'+n['id']).json()
    assert len(saved['sources'][0]['sections'])==4500 and saved['calls']==[]


def test_compressed_image_pixel_cost_counts_without_changing_original(env,monkeypatch):
    client=account(env);blob=picture((4096,2048))
    assert len(blob)<40000  # Compressed file bytes are not image input tokens.
    n=notice(client,text='',files=[('files',('large.png',blob,'image/png'))])
    cfg=env[1];cfg.ai_api_key='synthetic-budget-key';cfg.notice_input_tokens=12000
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('image budget must reject before generation'))
    response=client.post(f"/api/notices/{n['id']}/generate",json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==422 and '输入估算' in response.text
    sid=n['sources'][0]['id']
    assert client.get(f"/api/notices/{n['id']}/sources/{sid}/download").content==blob


def test_direct_model_entry_also_rejects_before_opening_http(env,monkeypatch):
    client=account(env);n=notice(client);cfg=env[1];cfg.ai_api_key='synthetic-budget-key';cfg.notice_input_tokens=4096
    monkeypatch.setattr(ai.httpx,'Client',lambda **kwargs:pytest.fail('must not open a provider connection'))
    with pytest.raises(ai.AIError,match='未发送'):
        ai.generate(cfg,n,n['sources'],{})


def test_notice_changed_after_preflight_is_not_sent(env,monkeypatch):
    client=account(env);n=notice(client);env[1].ai_api_key='synthetic-budget-key'
    original=ai.prepare_notice_input
    def change_after_check(*args):
        prepared=original(*args)
        response=client.post(f"/api/notices/{n['id']}/supplement",data={'version':n['version'],'body':'虚构更正：请重新核对本次要求。'})
        assert response.status_code==200
        return prepared
    monkeypatch.setattr(ai,'prepare_notice_input',change_after_check)
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('stale input must not be sent'))
    response=client.post(f"/api/notices/{n['id']}/generate",json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==409
    saved=client.get('/api/notices/'+n['id']).json()
    assert len(saved['sources'])==2 and saved['calls']==[]


@pytest.mark.parametrize('limit',['4095','900001','bad'])
def test_invalid_notice_budget_configuration_is_rejected(monkeypatch,limit):
    monkeypatch.setenv('NOTICE_INPUT_TOKENS',limit)
    with pytest.raises(ValueError):Settings.from_env()
