"""Bounded tree reads, full-path navigation and a text-free change token."""
import hashlib
import time
from .db import dumps
from . import memory_tree as tree


def locations(conn, uid, query='', exclude=None, offset=0, limit=100):
    nodes={r['id']:dict(r) for r in conn.execute('SELECT * FROM memory_nodes WHERE user_id=?',(uid,))}
    blocked=set(tree.descendants(conn,uid,exclude)) if exclude else set()
    paths={}
    def path(nid):
        if nid not in paths:
            n=nodes[nid]
            paths[nid]=(path(n['parent_id'])+' / ' if n['parent_id'] in nodes else '')+n['title']
        return paths[nid]
    from .memory_policy import normalized
    words=normalized(query).split()
    values=[{**n,'path':path(nid)} for nid,n in nodes.items() if nid not in blocked]
    values=[n for n in values if all(w in normalized(n['path']) for w in words)]
    values.sort(key=lambda n:(n['parent_id'] is not None,n['path'],n['id']))
    return {'nodes':values[offset:offset+limit],'matched':len(values),'offset':offset,'limit':limit}


def status(conn,uid):
    # The token contains no remembered text. Include semantic/expiry transitions
    # which may change usability without changing the memory's content version.
    now=int(time.time());h=hashlib.sha256()
    for row in conn.execute('''SELECT m.id,m.version,m.active,d.review_status,s.status,s.version,
        (p.expires_at IS NOT NULL AND p.expires_at<=?),
        (p.valid_from IS NOT NULL AND p.valid_from>?),
        (s.review_after IS NOT NULL AND s.review_after<=?)
        FROM personal_memories m JOIN memory_details d ON d.memory_id=m.id
        JOIN memory_semantics s ON s.memory_id=m.id JOIN memory_policies p ON p.memory_id=m.id
        WHERE m.user_id=? ORDER BY m.id''',(now,now,now,uid)):
        h.update(dumps(list(row)).encode())
    for sql,args in (
        ('SELECT id,parent_id,title,version FROM memory_nodes WHERE user_id=? ORDER BY id',(uid,)),
        ('''SELECT u.source_kind,u.source_id,u.fingerprint,count(*),v.version
           FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
           WHERE u.user_id=? GROUP BY u.source_kind,u.source_id,u.fingerprint ORDER BY u.source_kind,u.source_id''',(uid,)),
        ('SELECT source_kind,source_id FROM memory_blocked_sources WHERE user_id=? ORDER BY source_kind,source_id',(uid,)),
        ('''SELECT s.id,s.promoted_id,coalesce(e.version,0) FROM memory_session_items s
            LEFT JOIN memory_session_edits e ON e.session_id=s.id WHERE s.user_id=? AND s.expires_at>? ORDER BY s.id''',(uid,now)),
        ('SELECT mode,version FROM memory_settings WHERE user_id=?',(uid,)),
    ):
        for row in conn.execute(sql,args):h.update(dumps(list(row)).encode())
    jobs={r['state']:r['n'] for r in conn.execute('SELECT state,count(*) n FROM memory_jobs WHERE user_id=? GROUP BY state',(uid,))}
    h.update(dumps(jobs).encode())
    return {'token':h.hexdigest(),'jobs':jobs,'checked_at':now}


def entries(conn,uid,nid=None,q='',offset=0,limit=50,view='all',state='all',sort='recent'):
    from .memory_reliability import memory_catalog
    from .memory_store import settings_for
    from .memory_policy import normalized
    q=q.strip()
    _,root=tree.reconcile(conn,uid);nid=nid or root
    if view=='auto':
        key=tree.node_for(conn,uid,nid)['node_key']
        view='all' if q or key.startswith(('source:','source-group:')) else 'memories'
    branch=tree.descendants(conn,uid,nid)
    members={r['memory_id']:r['node_id'] for r in conn.execute('''SELECT i.* FROM memory_node_items i
        WHERE node_id IN (SELECT value FROM json_each(?))''',(dumps(branch),))}
    projects=[dict(r) for r in conn.execute('SELECT * FROM memory_projects WHERE user_id=? ORDER BY name',(uid,))]
    names={p['id']:p['name'] for p in projects}
    # Resolve paths once, including ancestors, so project/folder names really
    # are searchable. Source contents are fetched only for the selected page.
    paths={n['id']:n['path'] for n in locations(conn,uid,limit=100000)['nodes']}
    items=[m for m in memory_catalog(conn,uid) if m['id'] in members] if view!='passages' else []
    words=normalized(q).split()
    for m in items:
        m['node_id']=members[m['id']];m['path']=paths.get(m['node_id'],'')
    if words:
        items=[m for m in items if all(w in normalized(' '.join([m['content'],m['topic'],names.get(m['project_id'],''),m['path'],*m['labels']])) for w in words)]
    if state!='all':
        items=[m for m in items if (m['state']=='active' if state=='active' else m['state'] in ('pending','conflict','needs_review','source_changed') if state=='held' else m['state'] in ('inactive','archived','cooling','expired','scheduled'))]
    # SQL sorts a union of lightweight IDs; never fetch offset+limit full
    # passages just to merge a late page with editable memories.
    where='''u.user_id=? AND u.node_id IN (SELECT value FROM json_each(?)) AND u.fingerprint=v.version
        AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id)'''
    args=[uid,dumps(branch)]
    for word in words:
        where+=" AND (u.node_id IN (SELECT value FROM json_each(?)) OR instr(lower(u.content||' '||u.title||' '||u.locator),?)>0)"
        args.extend([dumps([n for n in branch if word in normalized(paths.get(n,''))]),word])
    if view=='memories' or state not in ('all','active'):where+=' AND 0'
    count=conn.execute('SELECT count(*) FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id) WHERE '+where,args).fetchone()[0]
    direction='ASC' if sort=='oldest' else 'DESC'
    page=list(conn.execute('''SELECT json_extract(j.value,'$.id') id,'memory' type,
        json_extract(j.value,'$.updated_at') updated_at FROM json_each(?) j UNION ALL
        SELECT u.id,'passage',u.created_at FROM memory_source_units u
        JOIN memory_resource_versions v USING(source_kind,source_id) WHERE '''+where+f' ORDER BY updated_at {direction},id LIMIT ? OFFSET ?',
        (dumps([{'id':m['id'],'updated_at':m['updated_at']} for m in items]),*args,limit,offset)))
    byid={m['id']:m for m in items}
    ids=[r['id'] for r in page if r['type']=='passage']
    passages=[dict(r) for r in conn.execute('''SELECT u.* FROM json_each(?) j CROSS JOIN memory_source_units u
        ON u.id=j.value WHERE u.user_id=?''',(dumps(ids),uid))]
    for p in passages:p['path']=paths.get(p['node_id'],'')
    return {'memories':[byid[r['id']] for r in page if r['type']=='memory'],'passages':passages,
        'order':[{'type':r['type'],'id':r['id']} for r in page], 'matched':len(items)+count,'total':len(items),
        'offset':offset,'limit':limit,'node_id':nid,'breadcrumbs':tree.ancestry(conn,uid,nid),
        'settings':settings_for(conn,uid),'projects':projects}
