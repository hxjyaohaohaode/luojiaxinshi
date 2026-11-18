"""Carry user-authored questions forward, never old answers, evidence numbers or permissions."""
import json
import re

MAX_TOPICS = 48


def explicit_topics(request):
    # Markers must occur at a clause boundary; decimals, quoted passages and
    # pasted material do not become extra instructions for the coordinator.
    request = re.split(r'(?:附件原文|通知全文|以下是原文|材料内容)\s*[：:]', request, maxsplit=1)[0]
    marker = r'(?:[-*]\s+|\d{1,2}[、.)）](?!\d)\s*|[（(][一二三四五六七八九十\d]{1,3}[）)]\s*|[一二三四五六七八九十]{1,3}、\s*)'
    lines = re.split(r'(?:^|[\n；;：:]|(?<=[。！？]))\s*'+marker,request)
    if len(lines)>2:
        candidates=lines[1:]
    else:
        candidates=re.findall(r'([^。！？?；;\n]{3,80}[?？])',request)
        if len(candidates)<2:
            # These are user-authored task clauses, not model-invented steps.
            candidates=re.findall(r'(?:^|[，,。；;\n])\s*((?:首先|先|然后|接着|再|最后)(?:帮我)?(?:核对|核实|查|整理|比较|规划|列|排|做|写|确认|计算|检查|拟)[^，,。；;\n]{1,76})',request)
    topics=list(dict.fromkeys(line.strip()[:80] for line in candidates if len(line.strip())>=3))
    return topics[:MAX_TOPICS] if len(topics)>=2 else []


def previous_topics(conn, uid, cid, messages):
    from ..memory_lifecycle import current_key, generation
    from ..retrieval_scope import user_request
    # Only consider visible prior user messages after history/forget filtering.
    prior=[m for m in messages[:-1] if m.get('role')=='user' and m.get('id')]
    if not prior:return []
    key, gen = current_key(conn, cid), generation(conn, uid)
    ids = json.dumps([message['id'] for message in prior])
    visible = {r[0] for r in conn.execute('''SELECT x.message_id FROM memory_message_context x
        JOIN conversation_messages m ON m.id=x.message_id WHERE m.conversation_id=? AND x.context_key=?
        AND x.generation=? AND x.learning_allowed=1 AND x.message_id IN (SELECT value FROM json_each(?))''',
        (cid, key, gen, ids))}
    sources = [user_request(message) for message in prior if message['id'] in visible]
    if not sources:
        return []
    row=conn.execute('''SELECT e.data, m.parent_id FROM agent_events e
        JOIN agent_turns r ON r.id=e.turn_id JOIN agent_threads t ON t.id=r.thread_id
        JOIN conversation_messages m ON m.id=r.request_id AND m.conversation_id=t.conversation_id
        JOIN memory_message_context x ON x.message_id=m.parent_id
        WHERE t.user_id=? AND t.conversation_id=? AND e.type='research.updated'
        AND x.learning_allowed=1 AND x.context_key=? AND x.generation=?
        AND m.parent_id IN (SELECT value FROM json_each(?))
        ORDER BY e.seq DESC LIMIT 1''',(uid,cid,key,gen,ids)).fetchone()
    if not row:return []
    # Old references are turn-local, and a later source correction may reverse an answer.
    return [i['topic'] for i in json.loads(row['data']).get('items',[])
            if i.get('state') in ('open','blocked') and i.get('topic') and any(i['topic'] in source for source in sources)][:MAX_TOPICS]


def resume_open_topics(request):
    # The latest instruction may explicitly narrow or cancel the outstanding work.
    return not re.search(r'只(?:要|用|做|看|查|需|处理)|仅(?:需|做|看|查|处理)|改为|先不|不再|取消|不用继续', request)


def first_tools(workflow, approach=None):
    common={'adapt_workflow','submit_answer','research_complete','track_research','campus_search','read_source',
            'public_search','current_time','compose_interface','openui_capabilities','spawn_agent'}
    if workflow in ('workspace','continue','memory','draft'):common.update(('workspace_read','workspace_capabilities','memory_recall','memory_capabilities'))
    if workflow=='research':common.update(('load_skill','workspace_read','memory_recall'))
    if approach=='time_plan':common.update(('workspace_read','current_time'))
    if approach=='follow_through':common.update(('workspace_read','memory_recall','track_research'))
    return common
