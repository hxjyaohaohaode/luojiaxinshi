from concurrent.futures import ThreadPoolExecutor
import threading
import time

from app import speech_cache
from app.main import create_app
from test_workflow import env, account
from test_mimo_speech import wav


def enable(env, monkeypatch):
    env[1].ai_api_key='synthetic'
    calls=[]
    def synthesize(settings,payload):
        calls.append(payload)
        return wav(.1)
    monkeypatch.setattr('app.speech.synthesize',synthesize)
    return calls


def say(client, **data):
    return client.post('/api/speech/synthesize',data={'text':'2026年10月22日，17点提交材料。',
                     'allow_external_processing':'true',**data})


def message(env,client):
    cid=client.post('/api/conversations',json={'title':'缓存测试'}).json()['id']
    with env[0].state.db.connect() as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,created_at) VALUES(?,?,'assistant','complete',?)",
                     ('speech-'+cid,cid,int(time.time())))
    return cid,'speech-'+cid


def test_replay_uses_private_cache_even_after_quota_and_app_restart(env,monkeypatch):
    c=account(env);calls=enable(env,monkeypatch);env[1].ai_daily_limit=1
    first=say(c);second=say(c)
    assert first.status_code==second.status_code==200
    assert first.headers['x-speech-cache']=='miss' and second.headers['x-speech-cache']=='hit'
    from app.speech import label_audio
    assert first.content==second.content==label_audio(wav(.1),'mimo-v2.5-tts') and len(calls)==1
    from fastapi.testclient import TestClient
    restarted=TestClient(create_app(env[1]),base_url='http://127.0.0.1:8765')
    restarted.cookies.update(c.cookies);restarted.headers.update(c.headers)
    assert say(restarted).headers['x-speech-cache']=='hit' and len(calls)==1
    assert say(c,text='不同内容').status_code==429


def test_cache_separates_accounts_voices_instructions_and_text(env,monkeypatch):
    a=account(env);b=account(env,'bob');calls=enable(env,monkeypatch)
    assert say(a).status_code==say(b).status_code==200
    assert len(calls)==2
    env[1].tts_voice='冰糖';assert say(a).headers['x-speech-cache']=='miss'
    assert say(a,description='自然朗读').headers['x-speech-cache']=='miss'
    assert say(a,text='另一条内容').headers['x-speech-cache']=='miss'
    env[1].ai_api_key='rotated';assert say(a).headers['x-speech-cache']=='miss'
    assert len(calls)==6


def test_reply_ownership_and_deletion_apply_before_audio_reuse(env,monkeypatch):
    a=account(env);b=account(env,'bob');calls=enable(env,monkeypatch);cid,mid=message(env,a)
    assert say(a,message_id=mid).status_code==200
    assert say(b,message_id=mid).status_code==404
    with env[0].state.db.connect() as conn:
        conn.execute('DELETE FROM conversations WHERE id=?',(cid,))
        assert conn.execute('SELECT count(*) FROM speech_audio_cache').fetchone()[0]==0
    assert say(a,message_id=mid).status_code==404 and len(calls)==1


def test_failed_generation_is_not_cached_or_automatically_retried(env,monkeypatch):
    c=account(env);enable(env,monkeypatch)
    from app.ai import AIError
    calls=[]
    def fail(*args):calls.append(1);raise AIError('fixture unavailable')
    monkeypatch.setattr('app.speech.synthesize',fail)
    assert say(c).status_code==502 and len(calls)==1
    assert say(c).status_code==502 and len(calls)==2
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM speech_audio_cache').fetchone()[0]==0


def test_concurrent_duplicates_share_one_generation_and_expired_audio_refreshes(env):
    c=account(env);uid=c.get('/api/session').json()['user']['id'];cache=speech_cache.SpeechCache(env[0].state.db)
    entered=threading.Event();release=threading.Event();calls=[]
    def generate():calls.append(1);entered.set();assert release.wait(5);return wav(.1)
    def run():return cache.get_or_create(uid,None,env[1],{'text':'same'},generate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(run);assert entered.wait(5);two=pool.submit(run);time.sleep(.05);release.set()
        assert one.result()[0]==two.result()[0]==wav(.1)
    assert len(calls)==1
    with env[0].state.db.connect() as conn:
        conn.execute('UPDATE speech_audio_cache SET created_at=0')
    assert run()[1] is False and len(calls)==2


def test_cache_storage_is_bounded_and_account_deletion_cascades(env,monkeypatch):
    c=account(env);uid=c.get('/api/session').json()['user']['id'];cache=speech_cache.SpeechCache(env[0].state.db)
    monkeypatch.setattr(speech_cache,'OWNER_BYTES',12);monkeypatch.setattr(speech_cache,'TOTAL_BYTES',12)
    for i in range(4):cache.get_or_create(uid,None,env[1],{'text':str(i)},lambda:b'12345678')
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT SUM(length(audio)) FROM speech_audio_cache').fetchone()[0]<=12
        conn.execute('DELETE FROM users WHERE id=?',(uid,))
        assert conn.execute('SELECT count(*) FROM speech_audio_cache').fetchone()[0]==0


def test_cache_never_bypasses_consent_or_session_authorization(env,monkeypatch):
    c=account(env);calls=enable(env,monkeypatch);assert say(c).status_code==200
    assert say(c,allow_external_processing='false').status_code==422
    c.headers['X-CSRF-Token']='invalid';assert say(c).status_code==403
    from fastapi.testclient import TestClient
    anonymous=TestClient(env[0],base_url='http://127.0.0.1:8765')
    anonymous.headers.update({'Origin':'http://127.0.0.1:8765','X-Requested-With':'campus-notice'})
    assert say(anonymous).status_code in {401,403}
    assert len(calls)==1


def test_deletion_during_generation_cannot_recreate_a_cached_reply(env):
    c=account(env);cid,mid=message(env,c);uid=c.get('/api/session').json()['user']['id'];cache=speech_cache.SpeechCache(env[0].state.db)
    def generate():
        with env[0].state.db.connect() as conn:conn.execute('DELETE FROM conversations WHERE id=?',(cid,))
        return wav(.1)
    assert cache.get_or_create(uid,mid,env[1],{'text':'test'},generate)[0]==wav(.1)
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM speech_audio_cache').fetchone()[0]==0


def test_cache_write_failure_does_not_discard_generated_audio(env,monkeypatch):
    c=account(env);uid=c.get('/api/session').json()['user']['id'];cache=speech_cache.SpeechCache(env[0].state.db)
    import sqlite3
    def fail(*args):raise sqlite3.OperationalError('fixture disk full')
    monkeypatch.setattr(cache,'_store',fail)
    assert cache.get_or_create(uid,None,env[1],{'text':'test'},lambda:wav(.1))[0]==wav(.1)
