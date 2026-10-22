"""Owner-scoped automatic selection and evidence-bound conversational editing."""
import json
import re
import time
from .db import dumps
from .memory_policy import effective,scope_key,normalized


def mode_for(conn,cid):
    row=conn.execute('SELECT mode FROM memory_selection_modes WHERE conversation_id=?',(cid,)).fetchone()
    return row['mode'] if row else 'auto'


def catalog_for(conn,uid):
    projects=[dict(row) for row in conn.execute('SELECT id,name,description FROM memory_projects WHERE user_id=? ORDER BY updated_at DESC,id LIMIT 100',(uid,))]
    topics=[row[0] for row in conn.execute("SELECT DISTINCT topic FROM personal_memories WHERE user_id=? AND scope='topic' ORDER BY topic LIMIT 100",(uid,))]
    return {'projects':[{**item,'description':item['description'][:180]} for item in projects],'topics':topics}


def mentions(name,text):
    name=normalized(name);text=normalized(text)
    if not name:return False
    if name.isascii():return bool(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text))
    if len(name)==1:return any(cue in text for cue in ('项目'+name,name+'项目','“'+name+'”','「'+name+'」'))
    return name in text


def selected_scopes(conn,uid,context,scenario,access):
    if context.get('selection_mode','manual')=='manual':return [context]
    # A snapshot checks the precise selected IDs and their conflict/source peers.
    if scenario is None:return None
    catalog=catalog_for(conn,uid);text=normalized(scenario)
    request=access.get('_memory_selection') or {}
    requested={p['id'] for p in catalog['projects'] if p['id'] in request.get('project_ids',[])}
    project_ids=requested or {p['id'] for p in catalog['projects'] if mentions(p['name'],text)}
    requested_topics={topic for topic in catalog['topics'] if topic in request.get('topics',[])}
    topics=requested_topics or {topic for topic in catalog['topics'] if mentions(topic,text)}
    if not project_ids and not topics:
        # Only local retrieval hints, never permission to another account.
        from .context_engine import terms
        query=set(terms(text))
        scored=[(len(query&set(terms(p['name']+' '+p['description']))),p['id']) for p in catalog['projects']]
        scored=sorted((score,key) for score,key in scored if score>=2)
        if scored and (len(scored)==1 or scored[-1][0]>scored[-2][0]):project_ids.add(scored[-1][1])
    if not project_ids:return [{**context,'project_id':None,'topics':sorted(topics)[:8]}]
    return [{**context,'project_id':key,'topics':sorted(topics)[:8]} for key in sorted(project_ids)[:3]]


def resolve_candidates(items,contexts):
    if contexts is None:
        groups={}
        for item in items:groups.setdefault(scope_key(item),[]).append(item)
        contexts_and_groups=[({'project_id':key[1] or None,'topics':[key[2]] if key[2] else []},group) for key,group in groups.items()]
    else:contexts_and_groups=[(context,items) for context in contexts]
    accepted={};excluded=[]
    for context,group in contexts_and_groups:
        found,blocked=effective(group,context);accepted.update((item['id'],item) for item in found);excluded.extend(blocked)
    return list(accepted.values()),[item for item in excluded if item['id'] not in accepted]


def directed_change(conn,uid,source,target):
    """An explicit correction grants this change, not permanent write access."""
    from .memory_learning import UNCERTAIN
    from .memory_lifecycle import facet
    if UNCERTAIN.search(source) or re.search(r'[“「『>]|```',source):return False
    change=re.search(r'更正|纠正|改为|改成|更新|修改|替换|补充|补上|以后.{0,8}(?:叫我|回答|回复|使用|用)|不再|搬到',source)
    if not change:return False
    compact=lambda text:re.sub(r'[\s，,。.!！；;]','',normalized(text))
    text=compact(source);old=compact(target['content'])
    if old and old in text:return True
    if target.get('semantic_key') and normalized(target['semantic_key']) in normalized(source):return True
    slot=facet(source)
    if not slot or slot!=target.get('facet'):return False
    count=conn.execute('''SELECT count(*) FROM memory_semantics s JOIN personal_memories m ON m.id=s.memory_id
        JOIN memory_details d ON d.memory_id=m.id WHERE m.user_id=? AND s.facet=? AND m.scope=? AND m.project_id IS ? AND m.topic=?
        AND m.active=1 AND s.status='active' AND d.review_status='accepted' ''',
        (uid,slot,target['scope'],target['project_id'],target['topic'])).fetchone()[0]
    return count==1


def faithful_explicit(quote,content):
    """Conservative guard for obvious additions, not a semantic proof."""
    from .memory_lifecycle import facet,canonical
    from .memory_store import tokens
    if content.strip() in quote:return True
    if set(re.findall(r'\d+',content))-set(re.findall(r'\d+',quote)):return False
    if facet(quote)==facet(content) and facet(quote) in ('identity.name','style.language'):
        if canonical(quote)!=canonical(content):return False
    if bool(re.search(r'不要|禁止|不能|不得|不再',content))!=bool(re.search(r'不要|禁止|不能|不得|不再',quote)):return False
    grammar=lambda text:re.sub(r'保持|希望|喜欢|偏好|通常|一直|我','',text)
    words=set(tokens(grammar(content)).split());original=set(tokens(grammar(quote)).split())
    return bool(words) and len(words&original)/len(words)>=.55


def replace_content(conn,uid,target,content,kind,mid,quote,actor='agent-update'):
    from .memory import Memory
    from .memory_lifecycle import set_semantics,event
    from .memory_store import invalidate_dependents,record_revision
    value=Memory.model_validate({**{key:target[key] for key in Memory.model_fields if key in target},'content':content,'kind':kind})
    changed=value.content!=target['content'] or kind!=target['kind']
    lock_changed=actor=='user-ai-edit' and not target['locked'] or actor=='source-sync' and target['locked']
    if not changed and not lock_changed:return target['id']
    if changed:invalidate_dependents(conn,target['id'])
    if actor=='user-ai-edit':conn.execute('UPDATE memory_details SET locked=1 WHERE memory_id=?',(target['id'],))
    conn.execute('UPDATE personal_memories SET content=?,kind=?,version=version+1,updated_at=? WHERE id=? AND user_id=?',
        (value.content,kind,int(time.time()),target['id'],uid))
    if mid:conn.execute('INSERT OR REPLACE INTO memory_evidence VALUES(?,?,?,?,?,?)',(target['id'],'message',mid,1,quote,int(time.time())))
    set_semantics(conn,target['id'],admission='manual' if actor=='user-ai-edit' else 'explicit',tier=target['tier'] if kind==target['kind'] else None)
    if actor in ('resource-update','source-sync'):conn.execute('UPDATE memory_semantics SET review_after=NULL WHERE memory_id=?',(target['id'],))
    conn.execute('UPDATE memory_semantics SET status=? WHERE memory_id=?',(target['status'],target['id']))
    record_revision(conn,target['id'],actor)
    if mid:
        # The same turn's local proposal is obsolete once the directed edit is
        # actually committed. Keep the applied revision and its source instead.
        conn.execute('''DELETE FROM personal_memories WHERE id IN (
            SELECT e.memory_id FROM memory_evidence e JOIN memory_links l ON l.child_id=e.memory_id
            JOIN memory_details d ON d.memory_id=e.memory_id WHERE e.source_kind='message' AND e.source_id=?
            AND e.quote=? AND l.parent_id=? AND l.relation='supersedes' AND d.review_status='pending'
            AND d.locked=0 AND d.origin IN ('automatic','agent'))''',(mid,quote,target['id']))
    event(conn,uid,target['id'],'updated','按本人明确要求修订' if actor=='user-ai-edit' else '原资料变化后自动更新索引' if actor=='resource-update' else '本人要求恢复跟随当前原资料' if actor=='source-sync' else '对话中依据新原话自动更新，保留历史版本')
    return target['id']
