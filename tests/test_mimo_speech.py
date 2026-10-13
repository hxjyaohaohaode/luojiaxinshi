import base64
import io
import json
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from app import speech
from app.ai import AIError
from app.config import Settings
from test_workflow import env,account,ORIGIN


def wav(seconds=1):
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
        audio.writeframes(b'\0\0'*int(16000*seconds))
    return output.getvalue()


def provider(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(speech.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))


def test_only_mimo_key_and_models_are_loaded(monkeypatch,tmp_path):
    monkeypatch.setenv('DATA_DIR',str(tmp_path));monkeypatch.setenv('APP_ENV','local');monkeypatch.setenv('APP_ORIGIN',ORIGIN)
    monkeypatch.setenv('MIMO_API_KEY','');monkeypatch.setenv('AI_API_KEY','old-key-must-not-be-used')
    monkeypatch.setenv('AI_BASE_URL','https://legacy.invalid/v1');monkeypatch.setenv('AI_MODEL','legacy')
    settings=Settings.from_env()
    assert settings.ai_api_key=='' and settings.ai_model=='mimo-v2.6-pro'
    assert settings.ai_base_url=='https://api.xiaomimimo.com/v1'
    monkeypatch.setenv('MIMO_API_KEY','xiaomi-test-key');assert Settings.from_env().ai_api_key=='xiaomi-test-key'
    monkeypatch.setenv('MIMO_BASE_URL','https://other.invalid/v1')
    with pytest.raises(ValueError,match='小米'):Settings.from_env()


def test_asr_endpoint_uses_chat_audio_and_keeps_text_for_confirmation(env,monkeypatch):
    c=account(env);env[1].ai_api_key='synthetic';seen=[]
    def handle(req):
        body=json.loads(req.content);seen.append(body)
        assert req.url==httpx.URL('https://api.xiaomimimo.com/v1/chat/completions')
        assert req.headers['authorization']=='Bearer synthetic'
        assert body['model']=='mimo-v2.5-asr' and body['asr_options']=={'language':'auto'}
        assert base64.b64decode(body['messages'][0]['content'][0]['input_audio']['data'].split(',')[1])==wav()
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'请核对申请日期'}}],'usage':{'seconds':1}})
    provider(monkeypatch,handle)
    response=c.post('/api/speech/transcribe',data={'allow_external_processing':'true'},files={'audio':('test.wav',wav(),'audio/wav')})
    assert response.status_code==200 and response.json()['text']=='请核对申请日期'
    assert len(seen)==1
    with env[0].state.db.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0


@pytest.mark.parametrize('mode,model',[('default','mimo-v2.5-tts'),('design','mimo-v2.5-tts-voicedesign'),('clone','mimo-v2.5-tts-voiceclone')])
def test_tts_modes_have_distinct_contracts(env,monkeypatch,mode,model):
    c=account(env);env[1].ai_api_key='synthetic';seen=[]
    def handle(req):
        body=json.loads(req.content);seen.append(body)
        assert body['model']==model and body['messages'][-1]=={'role':'assistant','content':'10月20日提交申请。'}
        assert 'response_format' not in body and 'thinking' not in body
        if mode=='default':assert body['audio']['voice']=='mimo_default'
        elif mode=='design':
            assert body['messages'][0]['content']=='清晰温和的青年声音'
            assert 'voice' not in body['audio'] and body['audio']['optimize_text_preview'] is False
        else:assert body['audio']['voice'].startswith('data:audio/wav;base64,')
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'audio':{'data':base64.b64encode(wav()).decode()}}}]})
    provider(monkeypatch,handle)
    data={'mode':mode,'text':'10月20日提交申请。','allow_external_processing':'true','description':'清晰温和的青年声音'}
    files=None
    if mode=='clone':data['clone_authorized']='true';files={'reference':('ref.wav',wav(),'audio/wav')}
    response=c.post('/api/speech/synthesize',data=data,files=files)
    assert response.status_code==200,response.text[:100]
    assert response.content==wav() and response.headers['x-speech-model']==model and len(seen)==1


def test_consent_authorization_and_invalid_audio_rejected_before_provider(env,monkeypatch):
    c=account(env);env[1].ai_api_key='synthetic'
    monkeypatch.setattr(speech,'complete',lambda *a:pytest.fail('must not fetch'))
    assert c.post('/api/speech/transcribe',files={'audio':('a.wav',wav())}).status_code==422
    assert c.post('/api/speech/transcribe',data={'allow_external_processing':'true'},files={'audio':('a.wav',b'fake')}).status_code==422
    assert c.post('/api/speech/synthesize',data={'mode':'clone','text':'测试','allow_external_processing':'true'},files={'reference':('r.wav',wav())}).status_code==422
    assert c.post('/api/speech/synthesize',data={'mode':'design','text':'测试','allow_external_processing':'true'}).status_code==422
    assert c.post('/api/speech/synthesize',data={'mode':'default','text':'x'*2001,'allow_external_processing':'true'}).status_code==422
    c.headers['X-CSRF-Token']='wrong'
    assert c.post('/api/speech/synthesize',data={'text':'test'}).status_code==403
    assert TestClient(env[0],base_url=ORIGIN).get('/api/speech/config').status_code==401


def test_empty_key_and_quota_do_not_call_provider(env,monkeypatch):
    c=account(env)
    assert c.get('/api/speech/config').json()['configured'] is False
    assert c.post('/api/speech/synthesize',data={'text':'测试','allow_external_processing':'true'}).status_code==503
    env[1].ai_api_key='synthetic';env[1].ai_daily_limit=1;calls=[]
    def handle(req):
        calls.append(1);return httpx.Response(429,json={'secret':'do not expose'})
    provider(monkeypatch,handle)
    response=c.post('/api/speech/synthesize',data={'text':'测试','allow_external_processing':'true'})
    assert response.status_code==502 and 'do not expose' not in response.text
    assert c.post('/api/speech/synthesize',data={'text':'测试','allow_external_processing':'true'}).status_code==429
    assert len(calls)==1


@pytest.mark.parametrize('data',[b'not wav',wav()[:-100],wav(61)],ids=['not-wav','truncated','overlong'])
def test_invalid_or_overlong_recording(data):
    with pytest.raises(ValueError):speech.wav_data_url(data)


def test_invalid_provider_audio_does_not_reach_playback(env,monkeypatch):
    env[1].ai_api_key='synthetic'
    provider(monkeypatch,lambda req:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'audio':{'data':'bad-base64'}}}]}))
    with pytest.raises(AIError,match='音频无效'):speech.synthesize(env[1],speech.tts_payload(env[1],'测试'))
