"""Event-driven source indexes, kept distinct from autobiographical memories.

These bounded excerpts help find relevant material. They are never a substitute
for the original document or evidence of a current official requirement.
"""
import json
import time
from .db import dumps


def source_for(conn,uid,kind,key):
    if kind=='resource_notice':
        row=conn.execute('''SELECT s.*,n.title,n.id AS notice_id FROM sources s JOIN notices n ON n.id=s.notice_id
            WHERE s.id=? AND n.user_id=?''',(key,uid)).fetchone()
    elif kind=='resource_material':
        row=conn.execute('''SELECT s.*,coalesce(l.full_sections,s.sections) AS readable FROM conversation_sources s
            JOIN conversations c ON c.id=s.conversation_id LEFT JOIN material_library l ON l.source_id=s.id
            WHERE s.id=? AND c.user_id=?''',(key,uid)).fetchone()
    elif kind=='resource_project':
        row=conn.execute('SELECT * FROM memory_projects WHERE id=? AND user_id=?',(key,uid)).fetchone()
    else:return None
    if not row:return None
    value=dict(row)
    if kind=='resource_project':
        content=value['name']+'\n'+value['description'];title=value['name'];available=True
    else:
        content=value.get('readable',value.get('sections','[]'));title=value['name']
        available=value['status']=='ok' and bool(value.get('active',1))
    revision=conn.execute('SELECT version FROM memory_resource_versions WHERE source_kind=? AND source_id=?',(kind,key)).fetchone()
    fingerprint=str(revision['version']) if revision else ''
    return {**value,'title':title,'body':content,'available':available,'fingerprint':fingerprint}


def excerpt(source,kind):
    from .memory_learning import SECRET,REJECT_INSTRUCTION
    if kind=='resource_project':text=source['body']
    else:
        sections=json.loads(source['body'])
        text='\n'.join(str(part.get('text',part.get('content',''))) for part in sections if isinstance(part,dict))
    # Indexes may include untrusted input. Exclude prompt directives and secrets.
    text='\n'.join(line for line in text.splitlines() if not REJECT_INSTRUCTION.search(line))
    text=SECRET.sub('[凭证已省略]',text).strip()[:1100]
    title=SECRET.sub('[凭证已省略]',source['title'])[:160]
    return ('项目资料索引' if kind=='resource_project' else '资料索引（需查阅当前原文）')+'：'+title+'\n'+(text or '仅有标题；暂无可用正文摘录。')


def ingest_resource(conn,uid,kind,key):
    from .memory_store import insert_memory,settings_for,decorate
    from .memory_policy import rows_for
    from .memory_autonomy import replace_content
    policy=settings_for(conn,uid)
    if policy['mode'] not in ('auto','review'):return None
    source=source_for(conn,uid,kind,key)
    if not source or not source['available']:return None
    if kind=='resource_project' and not source['description'].strip():return None
    if conn.execute('SELECT 1 FROM memory_blocked_sources WHERE user_id=? AND source_kind=? AND source_id=?',(uid,kind,key)).fetchone():return None
    bindings=list(conn.execute('''SELECT r.*,m.active,d.locked,d.review_status,s.status FROM memory_resource_sources r
        JOIN personal_memories m ON m.id=r.memory_id JOIN memory_details d ON d.memory_id=m.id
        JOIN memory_semantics s ON s.memory_id=m.id WHERE m.user_id=? AND r.source_kind=? AND r.source_id=?''',(uid,kind,key)))
    if any(row['fingerprint']==source['fingerprint'] for row in bindings):return None
    current=next((row for row in bindings if row['review_status']=='accepted'),None)
    body=excerpt(source,kind)
    if current:
        # Never reactivate archived entries, and never overwrite a human edit.
        if not current['active'] or current['status']!='active':return None
        if current['locked']:return None
        if policy['mode']=='auto':
            target=decorate(conn,rows_for(conn,uid,[current['memory_id']]))[0]
            replace_content(conn,uid,target,body,'summary',None,'','resource-update')
            conn.execute('UPDATE memory_resource_sources SET fingerprint=? WHERE memory_id=?',(source['fingerprint'],target['id']))
            conn.execute('UPDATE memory_evidence SET quote=?,created_at=? WHERE memory_id=? AND source_kind=? AND source_id=?',(body,int(time.time()),target['id'],kind,key))
            return target['id']
    value={'scope':'project' if kind=='resource_project' else 'global','project_id':key if kind=='resource_project' else None,
        'topic':'','kind':'summary','content':body,'semantic_key':'','source_conversation_id':source.get('conversation_id')}
    mid=insert_memory(conn,uid,value,origin='resource',locked=False,review='pending' if policy['mode']=='review' else 'accepted',
        evidence=[{'source_kind':kind,'source_id':key,'quote':body}],labels=['资料索引'])
    if mid:
        conn.execute('INSERT INTO memory_resource_sources VALUES(?,?,?,?)',(mid,kind,key,source['fingerprint']))
        if current:conn.execute("INSERT INTO memory_links VALUES(?,?,'supersedes',?)",(mid,current['memory_id'],conn.execute('SELECT version FROM personal_memories WHERE id=?',(current['memory_id'],)).fetchone()[0]))
    return mid


def invalid_resources(conn,uid,ids):
    return {row['memory_id'] for row in conn.execute('''SELECT r.memory_id FROM json_each(?) j
        CROSS JOIN memory_resource_sources r ON r.memory_id=j.value CROSS JOIN personal_memories m ON m.id=r.memory_id
        LEFT JOIN memory_resource_versions v ON v.source_kind=r.source_kind AND v.source_id=r.source_id
        WHERE m.user_id=? AND (v.version IS NULL OR r.fingerprint<>CAST(v.version AS TEXT))''',(dumps(list(ids)),uid))}


def queue_existing(conn,uid):
    for kind,sql in (
        ('resource_notice','SELECT s.id FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?'),
        ('resource_material','SELECT s.id FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?'),
        ('resource_project','SELECT id FROM memory_projects WHERE user_id=?')):
        for row in conn.execute(sql,(uid,)):
            conn.execute('''INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at) VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL''',
                ('resource:'+kind+':'+row['id'],uid,kind,row['id'],int(time.time())))
