"""Automatic admission decisions, with no human review inbox.

Unproved proposals remain unavailable. Exact evidence can admit them later;
old unresolved proposals retire. This is a provenance check, not an LLM judge.
"""
import re
import time
from .memory_policy import rows_for,scope_key
from .memory_store import decorate,record_revision,settings_for


def triage(conn,uid,limit=100,now=None):
    if settings_for(conn,uid)['mode']!='auto':return {'activated':0,'retired':0,'held':0}
    if conn.execute('SELECT 1 FROM conversations WHERE user_id=? AND processing_token IS NOT NULL',(uid,)).fetchone():return {'activated':0,'retired':0,'held':0,'busy':True}
    now=int(time.time()) if now is None else now
    rows=[dict(r) for r in conn.execute('''SELECT m.*,d.origin,d.locked FROM personal_memories m
       JOIN memory_details d ON d.memory_id=m.id LEFT JOIN memory_auto_state s ON s.memory_id=m.id
       WHERE m.user_id=? AND d.review_status='pending' ORDER BY coalesce(s.checked_at,0),m.created_at,m.id LIMIT ?''',(uid,limit))]
    active=decorate(conn,rows_for(conn,uid)) if rows else []
    activated=retired=held=0
    for row in rows:
        item=next(m for m in active if m['id']==row['id']);reason='依据不足，自动暂缓使用'
        proof=False
        # Pending generated rewrites never become evidence for one another.
        evidence=list(conn.execute('''SELECT e.quote,msg.content FROM memory_evidence e JOIN conversation_messages msg
            ON msg.id=e.source_id JOIN conversations c ON c.id=msg.conversation_id
            WHERE e.memory_id=? AND e.source_kind='message' AND c.user_id=? AND msg.role='user' AND msg.status='complete' ''',(row['id'],uid)))
        from .memory_learning import direct_quote,SECRET,REJECT_INSTRUCTION
        fragments=[p.strip() for p in re.split(r'[。；\n]',row['content']) if p.strip()]
        if row['origin'] in ('agent','automatic') and fragments:
            proof=any(direct_quote(e['quote'],e['content']) and all(p in e['quote'] for p in fragments) for e in evidence)
        if SECRET.search(row['content']) or REJECT_INSTRUCTION.search(row['content']):proof=False
        if item.get('valid_from') is not None or item.get('expires_at') is not None:proof=False;reason='时间边界缺少可靠依据，自动暂缓'
        peers=[p for p in active if p['id']!=row['id'] and p['active'] and p['review_status']=='accepted'
               and scope_key(p)==scope_key(item) and (item.get('semantic_key') and p.get('semantic_key')==item['semantic_key'] or item.get('facet') and p.get('facet')==item['facet'])]
        if peers:proof=False;reason='同一范围存在其他当前值，自动暂缓歧义项'
        if proof:
            conn.execute("UPDATE memory_details SET review_status='accepted' WHERE memory_id=?",(row['id'],))
            conn.execute('UPDATE personal_memories SET active=1,version=version+1,updated_at=? WHERE id=?',(now,row['id']))
            reason='原话依据完整，已自动采用';activated+=1;record_revision(conn,row['id'],'automatic-admission')
        elif now-row['created_at']>30*86400:
            conn.execute("UPDATE memory_details SET review_status='retired' WHERE memory_id=?",(row['id'],))
            conn.execute("UPDATE memory_semantics SET status='archived',version=version+1 WHERE memory_id=?",(row['id'],))
            reason='长期没有足够依据，已自动归档';retired+=1
        else:held+=1
        conn.execute('''INSERT INTO memory_auto_state VALUES(?,?,?) ON CONFLICT(memory_id)
          DO UPDATE SET reason=excluded.reason,checked_at=excluded.checked_at''',(row['id'],reason,now))
    return {'activated':activated,'retired':retired,'held':held}
