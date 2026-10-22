"""Check that an answer still describes the context the user authorized.

The fingerprint contains no recoverable content. It is rechecked before model
stages and publication, and inside the final database transaction. A changed
context stops the run rather than silently sending a fresh set of private data.
"""
import hashlib
import json

from .ai import AIError
from .db import dumps
from .memory import context_for,eligible_versions
from .preferences import PERSONAL_KEYS

STALE_MESSAGE='生成期间相关资料、日程或记忆已变化，本次旧回答未采纳。请核对最新内容后重试。'


def capture(conn, uid, cid, access, memory_ids=None, *, canonical=True):
    if not conn.in_transaction:conn.execute('BEGIN')
    chat=conn.execute('SELECT version FROM conversations WHERE id=? AND user_id=?',(cid,uid)).fetchone()
    if not chat:raise AIError(STALE_MESSAGE)
    values={'chat_version':chat['version']}
    def records(sql,args):return [list(row) for row in conn.execute(sql,args)]
    if access.get('profile'):
        person=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()
        profile=json.loads(person['profile']) if person else {}
        values['profile']={k:v for k,v in profile.items() if k in PERSONAL_KEYS}
    if access.get('memory'):
        from .memory_store import settings_for
        values['context']=context_for(conn,cid)
        values['memory']=eligible_versions(conn,uid,cid,True,access,memory_ids)
        if memory_ids is not None:
            values['memory']={key:value for key,value in values['memory'].items() if key in memory_ids}
        values['memory_settings']=settings_for(conn,uid)
        from .memory_lifecycle import config,current_key
        values['memory_lifecycle']=config(conn,uid)
        values['working_memory']=records('SELECT version FROM memory_working_frames WHERE conversation_id=? AND context_key=?',(cid,current_key(conn,cid)))
        values['session_memory']=records('SELECT id,expires_at,promoted_id FROM memory_session_items WHERE conversation_id=? ORDER BY id',(cid,))
        values['session_edits']=records('SELECT e.session_id,e.version FROM memory_session_edits e JOIN memory_session_items s ON s.id=e.session_id WHERE s.conversation_id=? ORDER BY e.session_id',(cid,))
    if access.get('library'):
        values['library']=records('''SELECT s.id,s.sha256,s.status,s.warning,l.path,v.version
            FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id
            LEFT JOIN material_library l ON l.source_id=s.id
            LEFT JOIN memory_resource_versions v ON v.source_kind='resource_material' AND v.source_id=s.id
            WHERE c.user_id=? ORDER BY s.id''',(uid,))
        values['notices']=records('''SELECT s.id,s.sha256,s.status,s.active,n.version,v.version FROM sources s
            JOIN notices n ON n.id=s.notice_id LEFT JOIN memory_resource_versions v
            ON v.source_kind='resource_notice' AND v.source_id=s.id WHERE n.user_id=? ORDER BY s.id''',(uid,))
    elif access.get('attachments'):
        values['attachments']=records('''SELECT s.id,s.sha256,s.status,s.warning,l.path,v.version
            FROM conversation_sources s LEFT JOIN material_library l ON l.source_id=s.id
            LEFT JOIN memory_resource_versions v ON v.source_kind='resource_material' AND v.source_id=s.id
            WHERE s.conversation_id=? ORDER BY s.id''',(cid,))
    if access.get('schedule'):
        values['tasks']=records('''SELECT t.id,t.version,t.status,w.version,r.version FROM tasks t
            LEFT JOIN task_workflows w ON w.task_id=t.id LEFT JOIN task_reviews r ON r.task_id=t.id
            WHERE t.user_id=? ORDER BY t.id''',(uid,))
        values['arrangements']=records('SELECT id,version FROM arrangements WHERE user_id=? ORDER BY id',(uid,))
        values['pending_changes']=records("SELECT id,version FROM notice_changes WHERE user_id=? AND state='pending' ORDER BY id",(uid,))
    serialized=json.dumps(values,ensure_ascii=False,separators=(',',':'),sort_keys=True) if canonical else dumps(values)
    return {'version':'context-snapshot-v2' if canonical else 'context-snapshot-v1','access':access,
            'digest':hashlib.sha256(serialized.encode()).hexdigest(),
            **({'memory_ids':sorted(memory_ids)} if memory_ids is not None else {})}


def assert_current(conn, uid, cid, snapshot):
    if not snapshot:return
    args=(conn,uid,cid,snapshot['access'],snapshot.get('memory_ids'))
    current=capture(*args,canonical=False) if snapshot.get('version') in (None,'context-snapshot-v1') else capture(*args)
    if current['digest']!=snapshot['digest']:
        raise AIError(STALE_MESSAGE)


def bind_memories(conn,uid,cid,snapshot,memories):
    """Bind every memory actually exposed across stages; unrelated edits may proceed."""
    assert_current(conn,uid,cid,snapshot)
    expected={'memory-'+item['id']:item['version'] for item in memories}
    versions=eligible_versions(conn,uid,cid,True,snapshot['access'],set(expected)) if snapshot['access'].get('memory') else {}
    if any(versions.get(key)!=version for key,version in expected.items()):raise AIError(STALE_MESSAGE)
    ids=set(snapshot.get('memory_ids',[]))|set(expected)
    result=capture(conn,uid,cid,snapshot['access'],ids)
    if 'session_ids' in snapshot:result['session_ids']=snapshot['session_ids']
    return result


def bind_sessions(snapshot,fields):
    ids=[*fields.get('_session_source_ids',[]),*[item['id'] for item in fields.get('_session_memory',{}).get('facts',[]) if item.get('id')]]
    return {**snapshot,'session_ids':list(dict.fromkeys(ids))}


def publication_current(conn, mid, uid, cid):
    """Run under the same write transaction that commits a completed answer."""
    row=conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(mid,)).fetchone()
    if not row:return True
    report=json.loads(row['report'])
    try:assert_current(conn,uid,cid,report.get('context_snapshot'))
    except AIError:
        report['status']='not_published'
        report['invalidation']='context_changed'
        if report.get('harness'):report['harness']['stop_reason']='context_changed'
        conn.execute('UPDATE reply_grounding SET report=? WHERE message_id=?',(dumps(report),mid))
        return False
    return True
