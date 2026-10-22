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


def test_work_receipt_contains_only_completed_execution_and_actual_citations():
    steps=[{'stage':'agent_tool','state':'complete','summary':'读取文件 申请表.txt','summary_origin':'execution'},
           {'stage':'agent_tool','state':'interrupted','summary':'写入失败','summary_origin':'execution'},
           {'stage':'writing','state':'complete','summary':'组织回答','summary_origin':'server'}]
    receipt=work_summary.completed_work({'answer':'整理完毕','citations':[{'source_id':'source-a'},{'source_id':'source-a'}]}, {'status':'checked'}, steps)
    assert receipt['outcomes']==['读取文件 申请表.txt']
    assert receipt['cited_sources']==['source-a'] and receipt['tool_calls']==2 and receipt['failed_tools']==1
    assert receipt['verified'] and not hasattr(work_summary,'BRIEFS')


def test_optional_summary_failure_preserves_main_answer_and_stage_history(env,monkeypatch):
    db,mid=stored_message(env)
    async def fail(*args):raise AIError('temporary')
    monkeypatch.setattr(work_summary,'unused_summary',fail,raising=False)
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
    async def summary(*args):calls.append(True);return 'unused',{}
    monkeypatch.setattr(work_summary,'unused_summary',summary,raising=False)
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
    monkeypatch.setattr(work_summary,'unused_summary',brief,raising=False)
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
    monkeypatch.setattr(work_summary,'unused_summary',brief,raising=False)
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
