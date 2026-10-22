"""Owner-scoped memory tree. Classification never changes use permissions.

Nodes contain navigational metadata, not authoritative facts. Original entries,
versions, source permissions and forgetting boundaries remain authoritative.
"""
import hashlib
import time

from fastapi import HTTPException
from .db import dumps

KINDS = {'preference':'偏好与习惯','constraint':'要求与约束','decision':'决定',
         'fact':'事实与背景','episode':'经历','skill':'方法与经验','intention':'目标与计划','summary':'概览'}
LAYERS = (('long','长期记忆'),('episodes','经历与经验'),('resources','资料与知识'))


def ensure_node(conn, uid, parent, title, key, system=True):
    existing=conn.execute('SELECT id FROM memory_nodes WHERE user_id=? AND node_key=?',(uid,key)).fetchone()
    nid=existing['id'] if existing else hashlib.sha256((uid+'\0'+key).encode()).hexdigest()[:32]
    # A renamed/moved folder keeps its public ID but releases its old path key.
    if not existing and conn.execute('SELECT 1 FROM memory_nodes WHERE id=?',(nid,)).fetchone():
        from .db import ident
        nid=ident()
    now = int(time.time())
    conn.execute('''INSERT OR IGNORE INTO memory_nodes VALUES(?,?,?,?,?,?,1,?,?)''',
                 (nid,uid,parent,title,key,int(system),now,now))
    if system:
        conn.execute('''UPDATE memory_nodes SET title=?,version=version+1,updated_at=?
            WHERE id=? AND title<>?''',(title,now,nid,title))
    return nid


def roots(conn, uid):
    root=ensure_node(conn,uid,None,'全部记忆','root')
    return {key:ensure_node(conn,uid,root,title,'layer:'+key) for key,title in LAYERS},root


def node_for(conn, uid, nid):
    row=conn.execute('SELECT * FROM memory_nodes WHERE id=? AND user_id=?',(nid,uid)).fetchone()
    if not row:raise HTTPException(404,'记忆目录不存在')
    return dict(row)


def ancestry(conn, uid, nid):
    node_for(conn,uid,nid)
    rows=list(conn.execute('''WITH RECURSIVE path(id,parent_id,title,system,version,node_key,depth) AS (
      SELECT id,parent_id,title,system,version,node_key,0 FROM memory_nodes WHERE id=? AND user_id=?
      UNION ALL SELECT n.id,n.parent_id,n.title,n.system,n.version,n.node_key,p.depth+1 FROM memory_nodes n JOIN path p ON n.id=p.parent_id
      WHERE n.user_id=? AND p.depth<12) SELECT * FROM path ORDER BY depth DESC''',(nid,uid,uid)))
    return [dict(row) for row in rows]


def descendants(conn, uid, nid):
    node_for(conn,uid,nid)
    return [r[0] for r in conn.execute('''WITH RECURSIVE branch(id,depth) AS (
       SELECT id,0 FROM memory_nodes WHERE user_id=? AND id=? UNION ALL
       SELECT n.id,b.depth+1 FROM memory_nodes n JOIN branch b ON n.parent_id=b.id
       WHERE n.user_id=? AND b.depth<12) SELECT id FROM branch''',(uid,nid,uid))]


def reconcile(conn, uid):
    """Only dirty records; custom placement survives automatic maintenance."""
    layers,root=roots(conn,uid)
    records=list(conn.execute('''SELECT m.*,d.origin,s.tier,coalesce(i.custom,0) custom
      FROM memory_tree_dirty q JOIN personal_memories m ON m.id=q.memory_id
      JOIN memory_details d ON d.memory_id=m.id JOIN memory_semantics s ON s.memory_id=m.id
      LEFT JOIN memory_node_items i ON i.memory_id=m.id WHERE m.user_id=?''',(uid,)))
    names={r['id']:r['name'] for r in conn.execute('SELECT id,name FROM memory_projects WHERE user_id=?',(uid,))}
    cache={}
    for record in records:
        item=dict(record)
        if not item['custom']:
            layer='resources' if item['origin'] in ('resource','source_claim') else 'episodes' if item['tier']=='episodic' or item['kind']=='episode' else 'long'
            scope_key=item['scope']+':'+(item['project_id'] or item['topic'] or '')
            scope_title=names.get(item['project_id'],'项目') if item['scope']=='project' else item['topic'] if item['scope']=='topic' else '通用'
            key='layer:'+layer+'/scope:'+scope_key
            if key not in cache:cache[key]=ensure_node(conn,uid,layers[layer],scope_title,key)
            category=key+'/kind:'+item['kind']
            if category not in cache:cache[category]=ensure_node(conn,uid,cache[key],KINDS[item['kind']],category)
            conn.execute('''INSERT INTO memory_node_items VALUES(?,?,0) ON CONFLICT(memory_id)
              DO UPDATE SET node_id=excluded.node_id,custom=0''',(item['id'],cache[category]))
        conn.execute('DELETE FROM memory_tree_dirty WHERE memory_id=?',(item['id'],))
    # Project renames update directory labels without moving human folders.
    for pid,name in names.items():
        for layer in layers:
            key='layer:'+layer+'/scope:project:'+pid
            conn.execute('UPDATE memory_nodes SET title=?,version=version+1,updated_at=? WHERE user_id=? AND node_key=? AND title<>?',(name,int(time.time()),uid,key,name))
    return layers,root


def place(conn, uid, mid, path, *, user=False, expected=None):
    """AI classifies within the entry's existing scope/category by default."""
    reconcile(conn,uid)
    row=conn.execute('''SELECT m.version,i.node_id,i.custom FROM personal_memories m
      JOIN memory_node_items i ON i.memory_id=m.id WHERE m.id=? AND m.user_id=?''',(mid,uid)).fetchone()
    if not row:raise ValueError('目标记忆不存在')
    if expected is not None and row['version']!=expected:raise ValueError('记忆版本已变化')
    if row['custom'] and not user:return row['node_id']
    if len(path)>3 or any(not p.strip() or len(p)>60 for p in path):raise ValueError('最多三层子目录，每层 1 至 60 字')
    current=row['node_id']
    # Reclassification starts at the last system category, not nested custom paths.
    while not node_for(conn,uid,current)['system']:
        current=node_for(conn,uid,current)['parent_id']
    for title in path:
        title=title.strip()
        same=conn.execute('SELECT id FROM memory_nodes WHERE user_id=? AND parent_id=? AND title=? ORDER BY id LIMIT 1',(uid,current,title)).fetchone()
        current=same['id'] if same else ensure_node(conn,uid,current,title,'folder:'+current+':'+title,system=False)
    conn.execute('UPDATE memory_node_items SET node_id=?,custom=? WHERE memory_id=?',(current,int(user),mid))
    return current


def memberships(conn, uid, ids):
    return {r['memory_id']:r['node_id'] for r in conn.execute('''SELECT i.* FROM json_each(?) j
       CROSS JOIN memory_node_items i ON i.memory_id=j.value CROSS JOIN personal_memories m ON m.id=i.memory_id
       WHERE m.user_id=?''',(dumps(list(ids)),uid))}


def catalog(conn, uid, limit=36, question=''):
    """L0/L1 routing hints only; facts are loaded after permission checks."""
    rows=[dict(r) for r in conn.execute('''SELECT n.id,n.parent_id,n.title,n.node_key,
      (SELECT count(*) FROM memory_node_items i WHERE i.node_id=n.id) item_count
      FROM memory_nodes n WHERE n.user_id=? AND n.parent_id IS NOT NULL
      ORDER BY n.system DESC,n.updated_at DESC,n.id''',(uid,))]
    nodes={r['id']:r for r in rows}
    now=int(time.time())
    live={r[0] for r in conn.execute('''SELECT i.node_id FROM memory_node_items i
      JOIN personal_memories m ON m.id=i.memory_id JOIN memory_details d ON d.memory_id=m.id
      JOIN memory_semantics s ON s.memory_id=m.id JOIN memory_policies p ON p.memory_id=m.id
      LEFT JOIN memory_resource_sources b ON b.memory_id=m.id
      LEFT JOIN memory_resource_versions v ON v.source_kind=b.source_kind AND v.source_id=b.source_id
      WHERE m.user_id=? AND m.active=1 AND d.review_status='accepted' AND s.status='active'
      AND (p.expires_at IS NULL OR p.expires_at>?) AND (p.valid_from IS NULL OR p.valid_from<=?)
      AND (b.memory_id IS NULL OR (b.fingerprint=CAST(v.version AS TEXT) AND NOT EXISTS(
        SELECT 1 FROM memory_blocked_sources x WHERE x.user_id=m.user_id AND x.source_kind=b.source_kind AND x.source_id=b.source_id)))
      UNION SELECT u.node_id FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
      WHERE u.user_id=? AND u.fingerprint=v.version AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources x
        WHERE x.user_id=u.user_id AND x.source_kind=u.source_kind AND x.source_id=u.source_id)''',(uid,now,now,uid))}
    for nid in list(live):
        for _ in range(12):
            parent=nodes.get(nid,{}).get('parent_id')
            if not parent or parent in live:break
            live.add(parent);nid=parent
    forbidden={r[0] for r in conn.execute('''SELECT n.id FROM memory_nodes n WHERE n.user_id=?
      AND n.node_key LIKE 'source:%' AND NOT EXISTS(SELECT 1 FROM memory_resource_versions v
        WHERE n.node_key='source:'||v.source_kind||':'||v.source_id AND NOT EXISTS(
          SELECT 1 FROM memory_blocked_sources x WHERE x.user_id=n.user_id AND x.source_kind=v.source_kind AND x.source_id=v.source_id))''',(uid,))}
    from .context_engine import terms
    words=set(terms(question))
    visible=[]
    for row in rows:
        names=[row['title']];parent=row['parent_id']
        denied=row['id'] in forbidden
        for _ in range(12):
            if parent not in nodes:break
            denied=denied or parent in forbidden
            names.append(nodes[parent]['title']);parent=nodes[parent]['parent_id']
        row['path']=' / '.join(reversed(names))
        if row['id'] in live and not denied:visible.append(row)
    rows=visible
    rows.sort(key=lambda n:(-len(words&set(terms(n['path']))),-bool(n['item_count']),n['path'],n['id']))
    return rows[:limit]


def snapshot(conn,uid,parent=None,offset=0,limit=100):
    layers,root=reconcile(conn,uid)
    parent=parent or root
    node_for(conn,uid,parent)
    # One aggregate for each table, rather than one SELECT per tree row.
    nodes=[dict(r) for r in conn.execute('''SELECT n.*,coalesce(c.children,0) children,
      coalesce(m.items,0)+coalesce(u.units,0) item_count FROM memory_nodes n
      LEFT JOIN (SELECT parent_id,count(*) children FROM memory_nodes WHERE user_id=? GROUP BY parent_id)c ON c.parent_id=n.id
      LEFT JOIN (SELECT i.node_id,count(*) items FROM memory_node_items i JOIN personal_memories p ON p.id=i.memory_id WHERE p.user_id=? GROUP BY i.node_id)m ON m.node_id=n.id
      LEFT JOIN (SELECT u.node_id,count(*) units FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
        WHERE u.user_id=? AND u.fingerprint=v.version AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b
        WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id) GROUP BY u.node_id)u ON u.node_id=n.id
      WHERE n.user_id=? AND n.parent_id=? ORDER BY n.system DESC,n.title,n.id LIMIT ? OFFSET ?''',(uid,uid,uid,uid,parent,limit+1,offset))]
    parents={r['id']:r['parent_id'] for r in conn.execute('SELECT id,parent_id FROM memory_nodes WHERE user_id=?',(uid,))};totals={}
    for row in conn.execute('''SELECT i.node_id,count(*) n FROM memory_node_items i JOIN personal_memories m ON m.id=i.memory_id
        WHERE m.user_id=? GROUP BY i.node_id UNION ALL SELECT u.node_id,count(*) FROM memory_source_units u
        JOIN memory_resource_versions v USING(source_kind,source_id) WHERE u.user_id=? AND u.fingerprint=v.version
        AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id) GROUP BY u.node_id''',(uid,uid)):
        nid=row['node_id']
        for _ in range(13):
            if nid is None:break
            totals[nid]=totals.get(nid,0)+row['n'];nid=parents.get(nid)
    for n in nodes:n['subtree_count']=totals.get(n['id'],0)
    return {'root_id':root,'parent_id':parent,'nodes':nodes[:limit],'total_items':totals.get(root,0),'has_more':len(nodes)>limit,'offset':offset,'next_offset':offset+limit if len(nodes)>limit else None,
            'breadcrumbs':ancestry(conn,uid,parent),'layers':layers}


def import_layout(conn,uid,layout,memory_map,project_map):
    """Map exported node identities into the current owner; never import ACLs."""
    if not isinstance(layout,dict):raise ValueError('目录结构无效')
    nodes=layout.get('nodes',[]);placements=layout.get('placements',[])
    if not isinstance(nodes,list) or len(nodes)>4000 or not isinstance(placements,list) or len(placements)>10000:raise ValueError('目录数量无效')
    _,root=reconcile(conn,uid)
    known={r['node_key']:r['id'] for r in conn.execute('SELECT node_key,id FROM memory_nodes WHERE user_id=?',(uid,))}
    mapped={};pending={}
    for raw in nodes:
        if not isinstance(raw,dict) or not isinstance(raw.get('id'),str) or len(raw['id'])>80 or raw['id'] in pending:raise ValueError('目录标识无效')
        pending[raw['id']]=raw
    for _ in range(9):
        progress=False
        for old,raw in list(pending.items()):
            parent=raw.get('parent_id');title=raw.get('title')
            if not isinstance(title,str) or not title.strip() or len(title)>160:raise ValueError('目录名称无效')
            if parent is not None and parent not in mapped:continue
            key=raw.get('node_key','')
            if not isinstance(key,str):raise ValueError('目录键无效')
            for before,after in project_map.items():key=key.replace('scope:project:'+before,'scope:project:'+after)
            if parent is None:mapped[old]=root
            elif key in known:mapped[old]=known[key]
            else:
                if len(ancestry(conn,uid,mapped[parent]))>=8:raise ValueError('导入目录超过八层')
                mapped[old]=ensure_node(conn,uid,mapped[parent],title.strip(),'import-folder:'+mapped[parent]+':'+hashlib.sha256(title.encode()).hexdigest()[:32],False)
            del pending[old];progress=True
        if not pending:break
        if not progress:raise ValueError('目录有循环或缺少上级')
    if pending:raise ValueError('目录层级过多')
    for raw in placements:
        if not isinstance(raw,dict):raise ValueError('记忆位置无效')
        mid=memory_map.get(raw.get('memory_id'));nid=mapped.get(raw.get('node_id'))
        if mid and nid:conn.execute('UPDATE memory_node_items SET node_id=?,custom=1 WHERE memory_id=?',(nid,mid))
