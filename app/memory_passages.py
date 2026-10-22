"""Incremental passage memory, grounded in current parsed resources.

Resource passages are document knowledge, never autobiographical assertions or
instructions. Deleting/editing a source invalidates recall before reindexing.
"""
import hashlib
import json
import time

from .db import dumps
from .memory_tree import roots,ensure_node


def sections(source,kind):
    if kind=='resource_project':return [{'locator':'项目说明','text':source['body']}]
    try:return json.loads(source['body'])
    except (TypeError,ValueError):return []


def index_source(conn,uid,kind,key,source):
    from .memory_learning import SECRET,REJECT_INSTRUCTION
    conn.execute('DELETE FROM memory_source_units WHERE user_id=? AND source_kind=? AND source_id=?',(uid,kind,key))
    if not source or not source['available']:return 0
    layers,_=roots(conn,uid)
    group=ensure_node(conn,uid,layers['resources'],{'resource_notice':'通知原文','resource_material':'上传资料','resource_project':'项目资料'}[kind],'source-group:'+kind)
    title=SECRET.sub('[凭证已省略]',source['title'])[:160]
    node=ensure_node(conn,uid,group,title,'source:'+kind+':'+key)
    ordinal=0
    for number,part in enumerate(sections(source,kind)):
        if not isinstance(part,dict):continue
        raw=str(part.get('text',part.get('content','')))
        # Detect on the complete original section, then mask every overlapping
        # slice. A long token/PEM block must not leak a prefixless continuation.
        private=[(match.start(),match.end()) for match in SECRET.finditer(raw)]
        locator=SECRET.sub('[凭证已省略]',str(part.get('locator') or part.get('location') or f'第{number+1}段'))[:200]
        for start in range(0,len(raw),1200):
            if start and start+200>=len(raw):break
            text=raw[start:start+1400]
            end=start+len(text)
            for a,b in reversed(private):
                if a<end and b>start:text=text[:max(a-start,0)]+'[凭证已省略]'+text[min(b-start,end-start):]
            text='\n'.join(line for line in text.splitlines() if not REJECT_INSTRUCTION.search(line))
            text=SECRET.sub('[凭证已省略]',text).strip()
            if not text:continue
            unit='unit-'+hashlib.sha256((uid+'\0'+kind+'\0'+key+'\0'+str(number)+':'+str(start)).encode()).hexdigest()[:30]
            conn.execute('INSERT INTO memory_source_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (unit,uid,node,kind,key,int(source['fingerprint']),locator,ordinal,start,title,text,int(time.time())))
            ordinal+=1
    return ordinal


def allowed(conn,uid,cid,units,access):
    from .memory_lifecycle import config
    cross_session=bool(config(conn,uid)['cross_session'])
    result=[];cache={}
    for unit in units:
        key=(unit['source_kind'],unit['source_id'])
        if key not in cache:
            # Snapshot checks load only ownership/status/version metadata, not
            # every full document represented by the selected passages.
            if key[0]=='resource_notice':
                record=conn.execute('''SELECT s.status,s.active FROM sources s JOIN notices n ON n.id=s.notice_id
                   WHERE s.id=? AND n.user_id=?''',(key[1],uid)).fetchone()
            elif key[0]=='resource_material':
                record=conn.execute('''SELECT s.status,1 active,s.conversation_id FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id
                   WHERE s.id=? AND c.user_id=?''',(key[1],uid)).fetchone()
            else:
                record=conn.execute("SELECT 'ok' status,1 active FROM memory_projects WHERE id=? AND user_id=?",(key[1],uid)).fetchone()
            revision=conn.execute('SELECT version FROM memory_resource_versions WHERE source_kind=? AND source_id=?',key).fetchone()
            source={**dict(record),'fingerprint':revision['version'],'available':record['status']=='ok' and bool(record['active'])} if record and revision else None
            blocked=conn.execute('SELECT 1 FROM memory_blocked_sources WHERE user_id=? AND source_kind=? AND source_id=?',(uid,*key)).fetchone()
            permit=bool(source and source['available'] and not blocked)
            if permit and not cross_session:
                permit=key[0]=='resource_material' and source.get('conversation_id')==cid
            if permit and key[0]=='resource_notice' and not access.get('library',True):permit=False
            if permit and key[0]=='resource_material' and not access.get('library',True):
                permit=access.get('attachments',True) and source.get('conversation_id')==cid
            if permit and key[0]=='resource_project':
                from .memory import context_for
                from .memory_autonomy import selected_scopes
                context=context_for(conn,cid)
                scopes=selected_scopes(conn,uid,context,access.get('_scenario'),access)
                permit=scopes is None or any(s['project_id']==key[1] for s in scopes)
            cache[key]=(source,permit)
        source,permit=cache[key]
        if permit and int(source['fingerprint'])==unit['fingerprint']:result.append(unit)
    return result


def versions(conn,uid,cid,ids,access):
    units=[dict(r) for r in conn.execute('SELECT u.* FROM json_each(?) j CROSS JOIN memory_source_units u ON u.id=j.value WHERE u.user_id=?',(dumps(list(ids)),uid))]
    return {'memory-'+u['id']:u['fingerprint'] for u in allowed(conn,uid,cid,units,access)}


def recall_passages(conn,uid,cid,question,access,queries=None,limit=4,byte_budget=4800):
    from .memory_search import match_query
    from .context_engine import terms
    from .memory_tree import descendants
    query=match_query(question+' '+' '.join(queries or []))
    if not query or limit<=0 or byte_budget<=0:return [],0
    rows=[dict(r) for r in conn.execute('''SELECT u.*,bm25(memory_source_fts) score FROM memory_source_fts
      JOIN memory_source_units u ON u.id=memory_source_fts.unit_id
      JOIN memory_resource_versions v USING(source_kind,source_id)
      WHERE memory_source_fts MATCH ? AND u.user_id=? AND u.fingerprint=v.version
      AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id)
      AND (? OR u.source_kind='resource_project' OR u.source_kind='resource_material' AND ? AND EXISTS(
         SELECT 1 FROM conversation_sources s WHERE s.id=u.source_id AND s.conversation_id=?))
      ORDER BY score,u.id LIMIT 96''',(query,uid,int(access.get('library',True)),int(access.get('attachments',True)),cid))]
    rows=allowed(conn,uid,cid,rows,{**access,'_scenario':question+' '+' '.join(queries or [])})
    requested=access.get('_memory_selection',{}).get('node_ids',[])
    branches=set()
    for nid in requested[:4]:
        row=conn.execute('SELECT 1 FROM memory_nodes WHERE id=? AND user_id=?',(nid,uid)).fetchone()
        if row:branches.update(descendants(conn,uid,nid))
    words=[word for word in terms(question) if len(word)>1]
    selected=[];used=0;seen=set()
    for row in sorted(rows,key=lambda u:(u['node_id'] not in branches,u['score'],u['id'])):
        text=row['content'];pos=next((text.casefold().find(word.casefold()) for word in words if word.casefold() in text.casefold()),0)
        start=max(0,pos-100);snippet=text[start:start+430]
        signature=hashlib.sha256(snippet.encode()).hexdigest()
        if signature in seen:continue
        content=f'资料片段：{row["title"]} · {row["locator"]}\n{snippet}\n[原始资料中的陈述；具体办理要求需核对当前原文]'
        item={'id':row['id'],'scope':'project' if row['source_kind']=='resource_project' else 'global',
              'project_id':row['source_id'] if row['source_kind']=='resource_project' else None,'topic':'',
              'kind':'fact','content':content,'version':row['fingerprint'],'updated_at':row['created_at'],
              'origin':'source_passage','locked':False,'labels':['资料知识'],'recall_score':round(-row['score'],6),
              'recall_reasons':['source-passage','tree-branch'] if row['node_id'] in branches else ['source-passage'],
              'tier':'long_term','facet':'','admission':'source','last_confirmed_at':row['created_at'],
              'scope_name':row['title'],'node_id':row['node_id'],'source_kind':row['source_kind'],
              'source_id':row['source_id'],'locator':row['locator'],'start_offset':row['start_offset']+start}
        from .memory_privacy import redact
        item=redact(item)
        cost=len(dumps(item).encode())+1
        if used+cost>byte_budget:continue
        selected.append(item);used+=cost;seen.add(signature)
        if len(selected)>=limit:break
    return selected,used
