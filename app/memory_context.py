"""The same scoped memory contract for grounded and basic conversation paths."""
import json
from .db import dumps
from .memory import context_for, memory_access, recall
from .memory_learning import learning_allowed
from .memory_store import settings_for
from .preferences import PERSONAL_KEYS
from .retrieval_scope import account_access


def runtime_fields(conn, uid, cid, messages):
    from .grounding import message_scope_start
    settings = settings_for(conn, uid)
    allowed = (settings['mode'] != 'off' and context_for(conn, cid)['memory_enabled']
               and account_access(messages)['profile'] and memory_access(messages)
               and message_scope_start(messages) is None)
    working = conn.execute('SELECT content FROM memory_working WHERE conversation_id=?', (cid,)).fetchone() if allowed else None
    receipts = []
    if allowed:
        for row in conn.execute('''SELECT g.report FROM reply_grounding g JOIN conversation_messages m ON m.id=g.message_id
                WHERE m.conversation_id=? AND m.status='complete' ORDER BY m.rowid DESC LIMIT 2''', (cid,)):
            receipts.extend(json.loads(row['report']).get('memory_operations', []))
    return {'_working_memory': working['content'] if working else '',
            '_memory_control': {**settings, 'may_propose': allowed and learning_allowed(conn, uid, cid, messages),
                                'context':context_for(conn,cid),'recent_operations': receipts[:16]}}


def basic_profile(db, uid, cid, mid, messages, profile):
    """No model calls. Store version evidence so later edits revoke old answers."""
    from .grounding import message_scope_start
    from .context_snapshot import capture, assert_current
    access = account_access(messages)
    if message_scope_start(messages) is not None:
        access = {key: False for key in access}
    access = {**access, 'memory': access['profile'] and memory_access(messages)}
    with db.connect() as conn:
        snapshot = capture(conn, uid, cid, access)
        fields = runtime_fields(conn, uid, cid, messages)
    question = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
    memories, report = recall(db, uid, cid, question, access)
    with db.connect(write=True) as conn:
        assert_current(conn, uid, cid, snapshot)
        sources = [{'id': 'memory-'+item['id'], 'evidence_kind': 'memory',
                    'memory_version': item['version'], 'memory_id': item['id'],
                    'name': '可用记忆', 'sections': []} for item in memories]
        conn.execute('INSERT OR REPLACE INTO reply_grounding VALUES(?,?,?)',
                     (mid, dumps(sources), dumps({'status': 'context_only', 'memory': report,
                       'context_snapshot': snapshot, 'prompt_version': 'memory-engine-v1'})))
    permitted = {key: value for key, value in profile.items() if access['profile'] or key not in PERSONAL_KEYS}
    return {**permitted, **fields, '_memory_entries': memories}
