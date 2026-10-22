"""Host Agent operations on actually supplied sources and memory versions.

The server validates provenance; the model does the semantic selection during
an already authorized answer. No additional paid background call is needed.
"""
import json
import time
from .memory_store import insert_memory


def supplied(conn,cid,message_id):
    values=[]
    for row in conn.execute('''SELECT g.sources FROM reply_grounding g JOIN conversation_messages a ON a.id=g.message_id
       WHERE a.parent_id=? AND a.conversation_id=?''',(message_id,cid)):
        values.extend(json.loads(row['sources']))
    return values


def apply_source(conn,uid,cid,message,action):
    from .memory_learning import SECRET,REJECT_INSTRUCTION
    from .memory_resources import source_for
    from .memory_passages import sections
    from .memory_tree import place
    proof=action.source_evidence
    if not proof:raise ValueError('资料记忆需要实际提供的来源与原文位置')
    source=next((s for s in supplied(conn,cid,message['id']) if s.get('id')==proof.source_id and s.get('evidence_kind') in ('notice','material')),None)
    if not source:raise ValueError('资料没有实际提供给本轮回答')
    quote=proof.quote.strip()
    if not quote or SECRET.search(quote) or REJECT_INSTRUCTION.search(quote):raise ValueError('资料片段为空或含不适合保存的内容')
    if not any(quote in str(s.get('text','')) and s.get('locator')==proof.locator for s in source.get('sections',[])):
        raise ValueError('引用不在本轮实际提供的资料位置')
    kind='resource_notice' if source['evidence_kind']=='notice' else 'resource_material'
    current=source_for(conn,uid,kind,proof.source_id)
    if not current or not current['available'] or not any(quote in str(p.get('text',p.get('content',''))) for p in sections(current,kind) if isinstance(p,dict)):
        raise ValueError('原始资料已改变或不可用')
    # No linguistic guess is treated as a new fact. Extraction can omit complete
    # sentences, but every retained sentence must occur in the supplied quote.
    import re
    content=action.content.strip()
    parts=[p.strip() for p in re.split(r'[\n。；]',content) if p.strip()]
    if not parts or any(p not in quote for p in parts) or SECRET.search(content) or REJECT_INSTRUCTION.search(content):
        raise ValueError('资料记忆需要忠实摘录，不接受来源外推断')
    if action.kind not in ('fact','summary','skill'):raise ValueError('资料知识不能变为个人偏好或本人决定')
    existing=conn.execute('''SELECT m.id FROM personal_memories m JOIN memory_details d ON d.memory_id=m.id
       JOIN memory_resource_sources b ON b.memory_id=m.id WHERE m.user_id=? AND d.origin='source_claim'
       AND b.source_kind=? AND b.source_id=? AND m.content=? AND b.fingerprint=?''',
       (uid,kind,proof.source_id,content,current['fingerprint'])).fetchone()
    if existing:return {'status':'unchanged','id':existing['id']}
    # A document is not evidence of a person's enduring habit. Use a source
    # label and its own resource boundary, independent of the current chat.
    value={'scope':'global','project_id':None,'topic':'','kind':action.kind,'content':content,
           'source_conversation_id':current.get('conversation_id'),'semantic_key':''}
    mid=insert_memory(conn,uid,value,origin='source_claim',review='accepted',locked=False,
          evidence=[{'source_kind':kind,'source_id':proof.source_id,'source_version':int(current['fingerprint']),
                     'quote':proof.locator+'\n'+quote}],labels=['资料知识',current['title'][:40]])
    if mid:
        conn.execute('INSERT INTO memory_resource_sources VALUES(?,?,?,?)',(mid,kind,proof.source_id,current['fingerprint']))
        conn.execute('UPDATE memory_semantics SET review_after=NULL WHERE memory_id=?',(mid,))
        if action.path:place(conn,uid,mid,action.path)
    return {'status':'source_saved' if mid else 'forgotten_blocked','id':mid}


def apply_organization(conn,uid,cid,message,action):
    from .memory_tree import place
    ids={s.get('memory_id') for s in supplied(conn,cid,message['id']) if s.get('evidence_kind')=='memory'}
    if action.target_id not in ids or action.expected_version is None:raise ValueError('只能整理本轮实际提供且版本未变的记忆')
    if not action.path:raise ValueError('整理需要目标子目录路径')
    node=place(conn,uid,action.target_id,action.path,expected=action.expected_version)
    return {'status':'organized','id':action.target_id,'node_id':node}
