"""Execution receipts from actual tools and verified outputs, never canned prose."""
import asyncio
import json
import re
import time
from copy import deepcopy


STAGES = {
    'planning': ('确认问题与范围', '范围规划'),
    'retrieving': ('查找相关资料与日程', '资料与日程检索'),
    'searching': ('查找公开来源', '联网搜索'),
    'coverage': ('检查覆盖与个人条件', '证据覆盖检查'),
    'writing': ('组织回答与互动界面', '回答与界面生成'),
    'verifying': ('核对事实与互动内容', '引用与结构核验'),
}


def brief(text, units=150):
    return text.encode('utf-16-le')[:units*2].decode('utf-16-le', errors='ignore')


def completed_work(result, report, steps):
    """A receipt built from actual outputs, with no extra model invocation."""
    outcomes = list(dict.fromkeys(s['summary'] for s in steps if s['stage'] == 'agent_tool'
        and s['state'] == 'complete' and s.get('summary') and s.get('summary_origin') == 'execution'))
    cited = list(dict.fromkeys(c['source_id'] for c in result.get('citations', [])))
    from .genui import parse_message
    components = [n['type'] for part in parse_message(result.get('answer', '')) if part['kind'] == 'ui'
        for n in part['spec']['nodes'].values()]
    if any(p['kind']=='ui' and p['spec'].get('sandbox') for p in parse_message(result.get('answer',''))):components.append('OpenGenerativeUI')
    # Reuse conclusions already checked by the independent reviewer. No new
    # model, inferred success, stage template, or unverified child summary.
    highlights = list(dict.fromkeys(brief(re.sub(r'\[(?:E)?\d+\]', '', c['text']).strip())
        for c in result.get('claims', []) if c.get('kind') in ('fact', 'inference', 'interface') and c.get('text')))
    return {'outcomes': outcomes, 'highlights': highlights[:3] if report.get('status') == 'checked' else [],
        'cited_sources': cited, 'ui_components': list(dict.fromkeys(components)),
        'tool_calls': sum(s['stage'] == 'agent_tool' for s in steps),
        'failed_tools': sum(s['stage'] == 'agent_tool' and s['state'] == 'interrupted' for s in steps),
        'verified': report.get('status') == 'checked',
        'gaps': [c['text'] for c in result.get('claims', []) if c.get('kind') == 'unknown'][:8]}


async def stream(settings, db, mid, source_events):
    """Persist factual events while the answer runs; cancellation closes the producer."""
    queue = asyncio.Queue(maxsize=32)
    steps = []
    summary_usage = {'input_tokens': 0, 'output_tokens': 0}
    sentinel = object()
    published = False

    def visible_steps():
        # Bound repeated SSE snapshots; the persisted report retains every step.
        return deepcopy(steps[-48:])

    def persist(result=None):
        with db.connect(write=True) as conn:
            row = conn.execute('SELECT report FROM reply_grounding WHERE message_id=?', (mid,)).fetchone()
            report = json.loads(row['report']) if row else {'status':'checking','started_at':int(time.time())}
            report['steps'] = steps
            report['summary_model'] = None
            report['summary_usage'] = summary_usage
            if result is not None:report['work_summary'] = completed_work(result, report, steps)
            conn.execute("INSERT INTO reply_grounding(message_id,report) VALUES(?,?) ON CONFLICT(message_id) DO UPDATE SET report=excluded.report", (mid,json.dumps(report,ensure_ascii=False)))

    async def produce():
        nonlocal published
        try:
            async for event in source_events:
                if event['type'] == 'agent':
                    from .agent_runtime.chat import TOOL_LABELS
                    kind, data, now = event['kind'], event['data'], int(time.time())
                    key = 'agent-' + data.get('agent_id', 'root') + '-' + data.get('call_id', '')
                    if kind == 'tool.started':
                        title = TOOL_LABELS.get(data.get('tool'), '调用工具')
                        steps.append({'id': key, 'stage': 'agent_tool', 'title': title, 'state': 'running',
                                      'started_at': now, 'summary': title, 'tools': [title], 'summary_origin': 'server'})
                    elif kind == 'tool.completed':
                        for record in steps:
                            if record['id'] == key:
                                record.update(state='interrupted' if data.get('error') else 'complete', finished_at=now)
                                if data.get('error'):record['summary'] = brief(data['error'])
                                elif data.get('summary'):
                                    record.update(summary=brief(data['summary']), summary_origin='execution', detail=data.get('detail',''))
                    elif kind.startswith('agent.'):
                        key = 'child-' + data.get('agent_id', '')
                        if kind == 'agent.started':
                            steps.append({'id': key, 'stage': 'subagent', 'title': '子任务：' + data.get('name', ''),
                                'state': 'running', 'started_at': now, 'summary': data.get('name', ''), 'tools': [], 'summary_origin': 'server'})
                        elif kind in ('agent.completed', 'agent.failed', 'agent.cancelled'):
                            for record in steps:
                                if record['id'] == key:
                                    record.update(state='complete' if kind == 'agent.completed' else 'interrupted', finished_at=now)
                    persist()
                    await queue.put({'type': 'work', 'steps': visible_steps()})
                if event['type'] == 'phase':
                    now = int(time.time())
                    for record in steps:
                        if record['stage'] in STAGES and record['state'] == 'running':
                            record.update(state='complete',finished_at=now)
                    title, tool = STAGES[event['phase']]
                    if event['phase']=='retrieving' and event.get('local_scope')=='message':title,tool='核对限定消息材料','限定材料核对'
                    if event['phase']=='retrieving' and event.get('local_scope')=='public':title,tool='核对对话条件，跳过私有库','对话条件核对'
                    if event['phase']=='retrieving' and event.get('local_scope')=='limited':title,tool='核对允许范围的资料','限定资料检索'
                    record = {'id':'step-'+str(len(steps)+1),'stage':event['phase'],'title':title,'state':'running','started_at':now,
                              'summary':event['label'],'summary_origin':'server','tools':[tool], 'detail':event.get('detail', '')}
                    steps.append(record)
                    persist()
                    event = {**event, 'steps':visible_steps()}
                    # Real tool events are sufficient; do not spend a model call
                    # choosing between equivalent canned status descriptions.
                if event['type'] == 'complete':
                    published = True
                    for step in steps:
                        if step['state']=='running':step.update(state='complete',finished_at=int(time.time()))
                    persist(event.get('result', {}))
                    await queue.put({'type':'work','steps':visible_steps()})
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
        await asyncio.gather(runner, return_exceptions=True)
        for record in steps:
            if record['state'] == 'running':
                record.update(state='complete' if published else 'interrupted',finished_at=int(time.time()))
        persist()
