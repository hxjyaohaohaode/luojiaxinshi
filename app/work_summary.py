"""Short Flash summaries of real work records, never a fabricated reasoning log.

The secondary model gets no chain of thought, draft answer or file contents.
Its only input is a bounded status record from the actual execution pipeline.
"""
import asyncio
import json
import re
import time
from copy import deepcopy

from .evidence_web import completion
from .ai import AIError

STAGES = {
    'planning': ('确认问题与范围', '范围规划'),
    'retrieving': ('查找相关资料与日程', '资料与日程检索'),
    'searching': ('查找公开来源', '联网搜索'),
    'coverage': ('检查覆盖与个人条件', '证据覆盖检查'),
    'writing': ('组织回答与互动界面', '回答与界面生成'),
    'verifying': ('核对事实与互动内容', '引用与结构核验'),
}
BRIEFS = {
    'planning':['梳理当前问题、用户补充与检索范围，确认本轮需要处理的内容。','确认问题范围与上下文，整理当前任务要求。'],
    'retrieving':['按当前问题检索本账号资料、通知与日程，选取相关原文片段。','检索相关本地记录，整理供回答使用的资料与日程证据。'],
    'searching':['检索公开来源，整理网页出处及可取得的内容。','查找公开网页，记录来源与实际取得的证据。'],
    'coverage':['检查已有证据对问题的覆盖情况，核对个人条件与待补充的内容。','核对需求、证据与个人条件，识别仍需查证的部分。'],
    'writing':['根据当前证据组织回答，自由编排需要的内容结构与交互。','整理回答与互动内容，为后续核验准备草稿。'],
    'verifying':['核对引文、事实、计算和互动结构，检查草稿是否得到证据支持。','检查回答与界面中的结论、引用和计算，修正发现的问题。'],
}


def safe_summary(text, record):
    if text not in BRIEFS.get(record.get('stage'),[]):
        return None
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 96:
        return None
    if re.search(r'https?://|```|<[^>]+>|sk-|保证|绝对|百分之百|全部资料|所有资料|查遍|全网|已提交|已修改|已发送|已办理', text):
        return None
    # Summary prose cannot invent counts or claim the current phase is finished.
    if re.search(r'\d|已完成|已核实|已验证|已确认', text):
        return None
    return text.strip()


async def summarize(settings, record):
    prompt = '''按服务器实际工作阶段，为用户选择最贴切的简短工作摘要。输出 JSON {"summary":"..."}。
summary 必须逐字使用 allowed_summaries 中的一项；不得加上任务主题、文件、网站、数字或新的步骤，不写内部推理。说明仅概括该阶段，阶段是否完成及检索数量由服务器另行展示。'''
    message, usage = await completion(settings, {'model': settings.ai_summary_model, 'thinking': {'type': 'disabled'}, 'max_completion_tokens': 300,
        'response_format': {'type': 'json_object'}, 'messages': [{'role':'system','content':prompt}, {'role':'user','content':json.dumps({'record':record,'allowed_summaries':BRIEFS.get(record.get('stage'),[])},ensure_ascii=False)}]}, max_bytes=20000)
    try:
        return safe_summary(json.loads(message['content']).get('summary'), record), usage
    except (ValueError, KeyError, TypeError):
        return None, usage


async def stream(settings, db, mid, source_events):
    """Keep status streaming while Pro works; Flash never delays the answer.

    Cancellation tears down the main request and every summary task. Stage IDs
    make late summaries update the right record without moving progress backward.
    """
    queue = asyncio.Queue(maxsize=32)
    steps = []
    jobs = set()
    summary_usage = {'input_tokens': 0, 'output_tokens': 0}
    lock = asyncio.Semaphore(1)
    sentinel = object()
    published = False

    def persist():
        with db.connect(write=True) as conn:
            row = conn.execute('SELECT report FROM reply_grounding WHERE message_id=?', (mid,)).fetchone()
            report = json.loads(row['report']) if row else {'status':'checking','started_at':int(time.time())}
            report['steps'] = steps
            report['summary_model'] = settings.ai_summary_model
            report['summary_usage'] = summary_usage
            conn.execute("INSERT INTO reply_grounding(message_id,report) VALUES(?,?) ON CONFLICT(message_id) DO UPDATE SET report=excluded.report", (mid,json.dumps(report,ensure_ascii=False)))

    async def brief(record):
        if record['stage']=='retrieving' and record['tools']!=['资料与日程检索']:
            return
        try:
            async with lock:
                # Work completed before the summary got a turn: no reason to spend tokens.
                if record['state'] != 'running':
                    return
                async with asyncio.timeout(10):
                    summary, usage = await summarize(settings, {k:v for k,v in record.items() if k in ('stage','title','state','tools','detail')})
            summary_usage['input_tokens'] += int(usage.get('prompt_tokens') or 0)
            summary_usage['output_tokens'] += int(usage.get('completion_tokens') or 0)
            if summary:
                record['summary'] = summary
                record['summary_origin'] = 'flash'
                persist()
                await queue.put({'type':'work','steps':deepcopy(steps)})
        except Exception:
            # The exact server status stays visible when optional prose is unavailable.
            return

    async def produce():
        nonlocal published
        try:
            async for event in source_events:
                if event['type'] == 'phase':
                    now = int(time.time())
                    if steps and steps[-1]['state'] == 'running':
                        steps[-1].update(state='complete',finished_at=now)
                    title, tool = STAGES[event['phase']]
                    if event['phase']=='retrieving' and event.get('local_scope')=='message':title,tool='核对限定消息材料','限定材料核对'
                    if event['phase']=='retrieving' and event.get('local_scope')=='public':title,tool='核对对话条件，跳过私有库','对话条件核对'
                    if event['phase']=='retrieving' and event.get('local_scope')=='limited':title,tool='核对允许范围的资料','限定资料检索'
                    record = {'id':'step-'+str(len(steps)+1),'stage':event['phase'],'title':title,'state':'running','started_at':now,
                              'summary':event['label'],'summary_origin':'server','tools':[tool], 'detail':event.get('detail', '')}
                    steps.append(record)
                    persist()
                    event = {**event, 'steps':deepcopy(steps)}
                    job = asyncio.create_task(brief(record))
                    jobs.add(job)
                    job.add_done_callback(jobs.discard)
                if event['type'] == 'complete':
                    published = True
                    if steps:
                        steps[-1].update(state='complete',finished_at=int(time.time()))
                    persist()
                    await queue.put({'type':'work','steps':deepcopy(steps)})
                    # The persisted verified report, not status prose, is the final record.
                await queue.put(event)
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            await queue.put(error)
        finally:
            await source_events.aclose()
            # A cancelled consumer cannot drain a full queue. Do not deadlock cleanup.
            if not asyncio.current_task().cancelling():
                await queue.put(sentinel)

    runner = asyncio.create_task(produce())
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        runner.cancel()
        for task in list(jobs):
            task.cancel()
        await asyncio.gather(runner, *list(jobs), return_exceptions=True)
        if steps and steps[-1]['state'] == 'running':
            steps[-1].update(state='complete' if published else 'interrupted',finished_at=int(time.time()))
        persist()
