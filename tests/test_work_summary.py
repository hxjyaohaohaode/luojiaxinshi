"""Stage integrity, optional-model failure and cancellation are real async tests."""
import asyncio
import json
import time

from app import work_summary
from app.ai import AIError
from app.db import ident
from test_workflow import env, account
from test_workspace import conversation


def stored_message(env):
    chat=conversation(account(env));mid=ident();db=env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'assistant','','processing',?)",(mid,chat['id'],int(time.time())))
    return db,mid


def test_summary_safety_and_bounded_status_only_request(env,monkeypatch):
    calls=[]
    async def complete(settings,payload,**kwargs):
        calls.append(payload);return {'content':json.dumps({'summary':work_summary.BRIEFS['coverage'][0]})},{}
    monkeypatch.setattr(work_summary,'completion',complete)
    result,_=asyncio.run(work_summary.summarize(env[1],{'stage':'coverage','state':'running','title':'覆盖检查'}))
    assert result and len(result)<100 and calls[0]['model']=='mimo-v2.6-flash'
    assert calls[0]['thinking']=={'type':'disabled'}
    for bad in ['已验证全部资料','正在检查 19 份文件','保证绝对正确','已修改你的日程','x'*97,'<script>x</script>','检索历史安排，为匹配会议主题做准备。']:
        assert work_summary.safe_summary(bad,{}) is None


def test_optional_summary_failure_preserves_main_answer_and_stage_history(env,monkeypatch):
    db,mid=stored_message(env)
    async def fail(*args):raise AIError('temporary')
    monkeypatch.setattr(work_summary,'summarize',fail)
    async def source():
        yield {'type':'phase','phase':'planning','label':'正在确认范围…'}
        await asyncio.sleep(.01)
        yield {'type':'phase','phase':'writing','label':'正在组织回答…'}
        yield {'type':'complete','result':{'answer':'hello'}}
    async def run():return [e async for e in work_summary.stream(env[1],db,mid,source())]
    events=asyncio.run(run());assert events[-1]['type']=='complete'
    with db.connect() as conn:report=json.loads(conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(mid,)).fetchone()['report'])
    assert all(s['state']=='complete' for s in report['steps']) and all(s['summary_origin']=='server' for s in report['steps'])


def test_message_only_stage_never_claims_library_or_schedule_search(env,monkeypatch):
    db,mid=stored_message(env);calls=[]
    async def summary(*args):calls.append(True);return work_summary.BRIEFS['retrieving'][0],{}
    monkeypatch.setattr(work_summary,'summarize',summary)
    async def source():
        yield {'type':'phase','phase':'retrieving','label':'正在核对你限定消息中的材料…','local_scope':'message'}
        await asyncio.sleep(.02)
        yield {'type':'complete','result':{}}
    async def run():return [e async for e in work_summary.stream(env[1],db,mid,source())]
    packets=asyncio.run(run());step=packets[0]['steps'][0]
    assert not calls and step['tools']==['限定材料核对'] and step['title']=='核对限定消息材料'
    assert step['summary_origin']=='server' and '本账号资料' not in step['summary']


def test_status_updates_use_real_events_without_extra_model_calls(env,monkeypatch):
    env[1].ai_stage_summaries=True
    db,mid=stored_message(env)
    called=[]
    async def brief(settings,record):
        called.append(True)
        await asyncio.sleep(.02)
        assert set(record)<= {'stage','title','state','tools','detail'}
        return '正在按当前任务记录核对范围并整理简短的阶段说明。',{'prompt_tokens':2,'completion_tokens':3}
    monkeypatch.setattr(work_summary,'summarize',brief)
    async def source():
        yield {'type':'phase','phase':'planning','label':'正在确认范围…'}
        await asyncio.sleep(.005)
        yield {'type':'phase','phase':'coverage','label':'正在检查覆盖…'}
        await asyncio.sleep(.06)
        yield {'type':'complete','result':{}}
    async def run():return [e async for e in work_summary.stream(env[1],db,mid,source())]
    events=asyncio.run(run());updates=[e for e in events if e['type']=='work']
    assert updates and updates[-1]['steps'][0]['summary_origin']=='server'
    assert not called
    assert [s['stage'] for s in updates[-1]['steps']]==['planning','coverage']
    assert events[0]['steps'][0]['state']=='running'  # earlier packet is an immutable snapshot


def test_cancellation_closes_provider_and_full_queue_without_deadlock(env,monkeypatch):
    env[1].ai_stage_summaries=True
    db,mid=stored_message(env);closed=[];cancelled=[]
    async def brief(*args):
        try:await asyncio.sleep(10)
        finally:cancelled.append(True)
    monkeypatch.setattr(work_summary,'summarize',brief)
    async def source():
        try:
            for _ in range(50):yield {'type':'phase','phase':'writing','label':'正在组织回答…'}
        finally:closed.append(True)
    async def run():
        stream=work_summary.stream(env[1],db,mid,source())
        await anext(stream)
        await asyncio.sleep(.04)
        await asyncio.wait_for(stream.aclose(),1)
    asyncio.run(run())
    assert closed and not cancelled
    with db.connect() as conn:report=json.loads(conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(mid,)).fetchone()['report'])
    assert report['steps'][-1]['state']=='interrupted'
