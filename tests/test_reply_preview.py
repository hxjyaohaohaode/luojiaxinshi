"""Reload and correction checkpoints are durable but never verified evidence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from app import genui_ai
from app.ai import AIError
from app.reply_preview import PreviewCheckpoint
from test_workflow import env, account
from test_workspace import conversation
from test_genui_transport import events, payload


def test_checkpoint_text_rebase_retains_ui_but_new_generation_clears_it():
    p=PreviewCheckpoint(10000)
    p.apply('preview',{'text':'首稿','reset':True})
    p.apply('ui_preview',{'content':{'reset':True,'css':'p{}','html':[{'index':0,'text':'<p>界面</p>'}],'localReady':True}})
    p.apply('preview',{'text':'首稿定稿','reset':True})
    assert p.ui['html']==['<p>界面</p>']
    p.apply('preview',{'text':'修正稿','reset':True,'clear_ui':True})
    assert p.text=='修正稿' and p.ui is None and p.revision==3


def test_refresh_during_stream_and_review_restores_exact_current_generation(env,monkeypatch):
    c=account(env);other=account(env,'preview-outsider');chat=conversation(c)
    first=threading.Event();repair=threading.Event();finish=threading.Event();checkpoint=threading.Event()
    async def stream(*_):
        yield {'type':'preview','text':'当前预览文字','reset':True}
        yield {'type':'ui_preview','content':{'reset':True,'css':'p{}','cssComplete':True,'html':[{'index':0,'text':'<p>正在生成的界面</p>'}]}}
        first.set()
        while not repair.is_set():await asyncio.sleep(.01)
        yield {'type':'preview','text':'','reset':True,'clear_ui':True}
        yield {'type':'preview','text':'已修正的新文字'}
        checkpoint.set()
        while not finish.is_set():await asyncio.sleep(.01)
        yield {'type':'delta','text':'已修正的新文字'}
        yield {'type':'complete','result':{'answer':'已修正的新文字','citations':[],'image_sources':[]}}
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request=pool.submit(c.post,f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat))
        try:
            assert first.wait(5)
            for _ in range(2):
                live=c.get('/api/conversations/'+chat['id']).json()['messages'][-1]
                assert live['status']=='processing' and live['preview']['text']=='当前预览文字'
                assert live['preview']['ui']['html']==['<p>正在生成的界面</p>']
                assert not live['genui']['raw'] and not live['genui']['validated']
            assert other.get('/api/conversations/'+chat['id']).status_code==404
            repair.set();assert checkpoint.wait(5)
            live=c.get('/api/conversations/'+chat['id']).json()['messages'][-1]
            assert live['preview']['text']=='已修正的新文字' and live['preview']['ui'] is None
            finish.set();final=events(request.result(timeout=5))[-1]['data']['conversation']['messages'][-1]
            assert final['status']=='complete' and final['genui']['raw']=='已修正的新文字'
            assert 'preview' not in final
            assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]==final
        finally:repair.set();finish.set()


def test_failed_new_preview_and_manual_revision_choice_survive_reload(env,monkeypatch):
    c=account(env);chat=conversation(c)
    async def complete(*_):
        yield {'type':'delta','text':'旧的完整回复'}
        yield {'type':'complete','result':{'answer':'旧的完整回复','citations':[],'image_sources':[]}}
    monkeypatch.setattr(genui_ai,'stream_reply',complete)
    chat=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation']
    old=chat['messages'][-1]['id']
    async def fail(*_):
        yield {'type':'preview','text':'最新但未完成的预览'}
        raise AIError('合成核验未通过')
    monkeypatch.setattr(genui_ai,'stream_reply',fail)
    chat=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat,content='',regenerate_message_id=old)))[-1]['data']['conversation']
    new=chat['messages'][-1]
    assert new['status']=='failed' and new['preview']['text']=='最新但未完成的预览'
    assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]['id']==new['id']
    for mid in [old,new['id']]:
        chat=c.post(f"/api/conversations/{chat['id']}/messages/{mid}/select",json={'version':chat['version']}).json()
        assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]['id']==mid
    seen=[]
    def reply(_settings,_sources,messages,_profile):
        seen.extend(m['content'] for m in messages)
        return {'answer':'后续回复','citations':[],'image_sources':[]},{}
    from app import chat_ai
    monkeypatch.setattr(chat_ai,'reply',reply)
    c.post(f"/api/conversations/{chat['id']}/messages",json=payload(chat,content='接着问'))
    assert '旧的完整回复' in seen and '最新但未完成的预览' not in seen


def test_cancel_retains_preview_but_disables_its_local_code(env,monkeypatch):
    c=account(env);chat=conversation(c);started=threading.Event();stopped=threading.Event()
    async def stream(*_):
        try:
            yield {'type':'preview','text':'取消前收到的最新文字'}
            yield {'type':'ui_preview','content':{'reset':True,'html':[{'index':0,'text':'<p>未完成界面</p>'}],'localReady':True}}
            started.set();await asyncio.sleep(20)
            yield {'type':'preview','text':'不得写入的迟到内容'}
        finally:stopped.set()
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request=pool.submit(c.post,f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat))
        assert started.wait(5)
        live=c.get('/api/conversations/'+chat['id']).json()
        cancelled=c.post('/api/conversations/'+chat['id']+'/cancel',json={'version':live['version']})
        assert cancelled.status_code==200
        message=cancelled.json()['messages'][-1]
        assert message['status']=='cancelled' and message['preview']['text']=='取消前收到的最新文字'
        assert message['preview']['ui']['localReady'] is False and not message['genui']['validated']
        request.result(timeout=5);assert stopped.wait(2)
        restored=c.get('/api/conversations/'+chat['id']).json()['messages'][-1]
        assert restored['preview']==message['preview'] and '迟到内容' not in str(restored)
