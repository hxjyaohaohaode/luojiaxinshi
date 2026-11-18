"""Carry user-authored questions forward, never old answers, evidence numbers or permissions."""
import json
import re

MAX_TOPICS = 48


def explicit_topics(request):
    lines = re.split(r'(?:^|\n)\s*(?:[-*]|\d{1,2}[、.)）])\s*', request)
    if len(lines)<3:
        lines=re.findall(r'([^。！？?；;\n]{3,80}[?？])',request)
    else:
        lines=lines[1:]
    topics=list(dict.fromkeys(line.strip()[:80] for line in lines if len(line.strip())>=3))
    return topics[:MAX_TOPICS] if len(topics)>=2 else []


def previous_topics(conn, uid, cid, messages):
    from ..memory_lifecycle import current_key, generation
    from ..retrieval_scope import user_request
    # Only consider visible prior user messages after history/forget filtering.
    prior=[m for m in messages[:-1] if m.get('role')=='user' and m.get('id')]
    if not prior:return []
    allowed={m['id']:user_request(m) for m in prior[-5:]}
    row=conn.execute('''SELECT e.data, m.parent_id FROM agent_events e
        JOIN agent_turns r ON r.id=e.turn_id JOIN agent_threads t ON t.id=r.thread_id
        JOIN conversation_messages m ON m.id=r.request_id AND m.conversation_id=t.conversation_id
        JOIN memory_message_context x ON x.message_id=m.parent_id
        WHERE t.user_id=? AND t.conversation_id=? AND e.type='research.updated'
        AND x.learning_allowed=1 AND x.context_key=? AND x.generation=?
        AND m.parent_id IN (SELECT value FROM json_each(?))
        ORDER BY e.seq DESC LIMIT 1''',(uid,cid,current_key(conn,cid),generation(conn,uid),json.dumps(list(allowed)))).fetchone()
    if not row:return []
    # Old references are turn-local, and a later source correction may reverse an answer.
    return [i['topic'] for i in json.loads(row['data']).get('items',[])
            if i.get('state') in ('open','blocked') and i.get('topic') and i['topic'] in allowed[row['parent_id']]][:MAX_TOPICS]


def first_tools(workflow):
    common={'adapt_workflow','submit_answer','research_complete','track_research','campus_search','read_source',
            'public_search','current_time','compose_interface','openui_capabilities','spawn_agent'}
    if workflow in ('workspace','continue','memory','draft'):common.update(('workspace_read','workspace_capabilities','memory_recall','memory_capabilities'))
    if workflow=='research':common.update(('load_skill','workspace_read','memory_recall'))
    return common
