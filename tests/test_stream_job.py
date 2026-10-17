import asyncio
import socket
import threading
import time
import httpx
import uvicorn
from app.stream_job import StreamJob
from app import genui_ai
from test_workflow import env,account
from test_workspace import conversation
from test_genui_transport import payload


def test_disconnect_continues_work_without_unbounded_queue():
    async def run():
        produced=[];closed=[];workers=set()
        async def source():
            try:
                for i in range(300):produced.append(i);yield str(i)
            finally:closed.append(True)
        job=StreamJob(source(),workers);stream=job.subscribe()
        assert await anext(stream)=='0'
        await stream.aclose()
        await asyncio.wait_for(job.task,1)
        assert produced==list(range(300)) and closed and job.queue.qsize()<=1
        await asyncio.sleep(0)
        assert not workers
    asyncio.run(run())


def test_explicit_cancel_closes_provider_and_heartbeat_does_not_forge_events():
    async def run():
        started=asyncio.Event();closed=[];workers=set()
        async def source():
            try:
                started.set();await asyncio.sleep(10)
                yield 'late'
            finally:closed.append(True)
        job=StreamJob(source(),workers,heartbeat=.01);stream=job.subscribe()
        await started.wait()
        assert await anext(stream)==': keepalive\n\n'
        job.task.cancel()
        await asyncio.gather(job.task,return_exceptions=True)
        assert [p async for p in stream]==[] and closed
    asyncio.run(run())


def test_real_http_disconnect_finishes_and_restores_the_full_reply(env,monkeypatch):
    c=account(env);chat=conversation(c);finished=threading.Event()
    expected='长回复开始。'+'后续中文内容🌸。'*2000+'完整结束。'
    async def provider(*args):
        try:
            yield {'type':'delta','text':'长回复开始。'}
            await asyncio.sleep(.2)
            yield {'type':'delta','text':expected[len('长回复开始。'):]}
            yield {'type':'complete','result':{'answer':expected,'citations':[],'image_sources':[]}}
        finally:finished.set()
    monkeypatch.setattr(genui_ai,'stream_reply',provider)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(env[0],log_level='critical',lifespan='on'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+3
        while not server.started and time.monotonic()<deadline:time.sleep(.01)
        assert server.started
        headers=dict(c.headers);headers['Cookie']='; '.join(k+'='+v for k,v in c.cookies.items())
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers=headers,timeout=3,trust_env=False) as network:
            with network.stream('POST',f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)) as response:
                assert response.status_code==200
                for line in response.iter_lines():
                    if line=='event: delta':break
            assert finished.wait(3),'disconnect cancelled the provider'
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                restored=network.get('/api/conversations/'+chat['id']).json()
                if not restored['processing']:break
                time.sleep(.01)
        message=restored['messages'][-1]
        assert message['status']=='complete' and message['content']==expected and message['genui']['raw']==expected
    finally:
        server.should_exit=True;thread.join(4)
        assert not thread.is_alive()
