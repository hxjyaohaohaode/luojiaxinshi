"""Model transmission consent is per conversation, persisted and revocable."""
import time
import uuid
import sqlite3

from app import chat_ai
from app.db import ident
from test_workflow import env, account
from test_workspace import conversation, send


def test_explicit_consent_persists_refreshes_and_revokes_without_affecting_other_accounts(env,monkeypatch):
    c=account(env);other=account(env,'bob');chat=conversation(c);env[1].ai_api_key='synthetic-only'
    monkeypatch.setattr(chat_ai,'reply',lambda *args:({'answer':'合成传输契约测试','citations':[],'image_sources':[]},{}))
    assert not chat['model_consent']
    path='/api/conversations/'+chat['id']
    request={'version':chat['version'],'content':'测试授权边界','request_id':uuid.uuid4().hex,'allow_external_processing':False}
    assert c.post(path+'/messages',json=request).status_code==422
    assert not c.get(path).json()['messages'] and not c.get(path).json()['model_consent']
    chat,_=send(c,chat);assert chat['model_consent'] and chat['model_consent_at']
    assert c.get(path).json()['model_consent']
    assert other.request('DELETE',path+'/model-consent',json={'version':chat['version']}).status_code==404
    assert c.request('DELETE',path+'/model-consent',json={'version':chat['version']-1}).status_code==409
    chat=c.request('DELETE',path+'/model-consent',json={'version':chat['version']}).json()
    assert not chat['model_consent'] and not chat['processing']
    assert len(chat['messages'])==2


def test_revocation_cancels_active_work_and_stale_steering_cannot_reauthorize(env):
    c=account(env);chat=conversation(c);now=int(time.time());mid=ident();parent=ident();cid=chat['id']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('INSERT INTO conversation_ai_consents VALUES(?,?)',(cid,now))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user','问题','complete',?)",(parent,cid,now))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant','','processing',?,?)",(mid,cid,parent,now))
        conn.execute('UPDATE conversations SET processing_token=?,processing_at=? WHERE id=?',('active-token',now,cid))
    result=c.request('DELETE','/api/conversations/'+cid+'/model-consent',json={'version':chat['version']}).json()
    assert not result['model_consent'] and result['messages'][-1]['status']=='cancelled'
    response=c.post('/api/conversations/'+cid+'/messages/stream',json={'version':chat['version'],'content':'旧页面补充','request_id':uuid.uuid4().hex,'steer_message_id':mid,'allow_external_processing':True})
    assert response.status_code==409
    assert not c.get('/api/conversations/'+cid).json()['model_consent']


def test_backups_and_older_raw_restore_do_not_resurrect_share_or_model_authorizations(env,tmp_path):
    from app.backups import restore_database
    c=account(env);chat=conversation(c);now=int(time.time());mid=ident();cid=chat['id']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'assistant','保留的回答','complete',?)",(mid,cid,now))
        conn.execute('INSERT INTO conversation_ai_consents VALUES(?,?)',(cid,now))
        conn.execute('INSERT INTO reply_shares VALUES(?,?,?,?,?,?,?)',('revocable-token-hash',cid,mid,'标题','公开快照',now+600,now))
    clean=tmp_path/'clean.sqlite3';env[0].state.db.backup(clean)
    raw=tmp_path/'older-raw.sqlite3'
    with env[0].state.db.connect() as original, sqlite3.connect(raw) as target:original.backup(target)
    restored=tmp_path/'restored.sqlite3';restore_database(raw,restored)
    for path in [clean,restored]:
        with sqlite3.connect(path) as conn:
            assert conn.execute('SELECT count(*) FROM reply_shares').fetchone()[0]==0
            assert conn.execute('SELECT count(*) FROM conversation_ai_consents').fetchone()[0]==0
            assert conn.execute('SELECT content FROM conversation_messages WHERE id=?',(mid,)).fetchone()[0]=='保留的回答'


def test_quota_rejected_steering_keeps_the_original_provider_working(env,monkeypatch):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app import genui_ai
    from test_genui_transport import payload, events
    c=account(env);chat=conversation(c);env[1].ai_api_key='synthetic-only';env[1].ai_daily_limit=1
    started=threading.Event();finish=threading.Event()
    async def provider(*args):
        started.set()
        while not finish.is_set():await asyncio.sleep(.01)
        yield {'type':'delta','text':'原回复完整结束。'}
        yield {'type':'complete','result':{'answer':'原回复完整结束。','citations':[],'claims':[],'image_sources':[]},'usage':{}}
    monkeypatch.setattr(genui_ai,'stream_reply',provider)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(c.post,f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat))
        try:
            assert started.wait(5)
            current=c.get('/api/conversations/'+chat['id']).json();mid=current['messages'][-1]['id']
            refused=c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(current,content='补充要求',steer_message_id=mid))
            assert refused.status_code==429
            assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]['status']=='processing'
        finally:finish.set()
        final=events(future.result(timeout=5))[-1]['data']['conversation']
    assert final['messages'][-1]['status']=='complete' and len(final['messages'])==2
