"""Tree navigation, direct editing and owner-checked organization."""
import time
from fastapi import Depends,HTTPException,Query
from pydantic import Field
from .models import Strict
from .db import dumps
from . import memory_tree as tree


class Folder(Strict):
    parent_id:str=Field(max_length=40)
    title:str=Field(min_length=1,max_length=60)


class FolderEdit(Folder):
    version:int=Field(ge=1)


class Placement(Strict):
    node_id:str=Field(max_length=40)
    version:int=Field(ge=1)


def install(app,db,user):
    @app.get('/api/memory/passages/{pid}')
    def passage(pid:str,current=Depends(user)):
        from .memory_resources import source_for
        with db.connect() as conn:
            row=conn.execute('SELECT * FROM memory_source_units WHERE id=? AND user_id=?',(pid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'资料片段不存在')
            value=dict(row);source=source_for(conn,current['id'],row['source_kind'],row['source_id'])
            if not source or not source['available'] or int(source['fingerprint'])!=row['fingerprint']:raise HTTPException(409,'原资料已变化，请刷新目录')
            value['href']='#notice/'+source['notice_id'] if source.get('notice_id') else '#chat/'+source['conversation_id'] if source.get('conversation_id') else '#memory'
            return value
    @app.get('/api/memory/tree')
    def read_tree(parent_id:str|None=Query(None,max_length=40),offset:int=Query(0,ge=0),current=Depends(user)):
        with db.connect(write=True) as conn:
            value=tree.snapshot(conn,current['id'],parent_id,offset)
            value['session_count']=conn.execute('SELECT count(*) FROM memory_session_items WHERE user_id=? AND expires_at>?',(current['id'],int(time.time()))).fetchone()[0]
            value['source_passages']=conn.execute('SELECT count(*) FROM memory_source_units WHERE user_id=?',(current['id'],)).fetchone()[0]
            return value

    @app.get('/api/memory/tree/entries')
    def entries(node_id:str|None=Query(None,max_length=40),q:str=Query('',max_length=1000),
                offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),current=Depends(user)):
        from .memory_reliability import memory_catalog
        from .memory_store import settings_for
        from .memory_policy import normalized
        with db.connect(write=True) as conn:
            _,root=tree.reconcile(conn,current['id']);nid=node_id or root
            branch=tree.descendants(conn,current['id'],nid)
            members={r[0] for r in conn.execute('SELECT memory_id FROM memory_node_items WHERE node_id IN (SELECT value FROM json_each(?))',(dumps(branch),))}
            items=[m for m in memory_catalog(conn,current['id']) if m['id'] in members]
            if q:items=[m for m in items if normalized(q) in normalized(m['content']+' '+' '.join(m['labels']))]
            items.sort(key=lambda m:(m['state']!='active',-m['updated_at'],m['id']))
            passages=[dict(r) for r in conn.execute('''SELECT u.id,u.node_id,u.title,u.content,u.locator,u.start_offset,u.source_kind,u.source_id,
              u.fingerprint,u.created_at FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
              WHERE u.user_id=? AND u.node_id IN (SELECT value FROM json_each(?)) AND u.fingerprint=v.version
              AND (?='' OR instr(lower(u.content||u.title),lower(?))>0)
              AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id)
              ORDER BY u.created_at DESC,u.source_id,u.ordinal LIMIT ? OFFSET ?''',
              (current['id'],dumps(branch),q,q,limit,max(0,offset-len(items))))]
            # Do not load a whole library to show a single page.
            unit_count=conn.execute('''SELECT count(*) FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
              WHERE u.user_id=? AND u.node_id IN (SELECT value FROM json_each(?)) AND u.fingerprint=v.version
              AND (?='' OR instr(lower(u.content||u.title),lower(?))>0)
              AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id)''',(current['id'],dumps(branch),q,q)).fetchone()[0]
            regular=items[offset:offset+limit]
            return {'memories':regular,'passages':passages[:limit-len(regular)],'matched':len(items)+unit_count,
                    'total':len(items),'offset':offset,'limit':limit,'node_id':nid,
                    'breadcrumbs':tree.ancestry(conn,current['id'],nid),'settings':settings_for(conn,current['id']),
                    'projects':[dict(r) for r in conn.execute('SELECT * FROM memory_projects WHERE user_id=? ORDER BY name',(current['id'],))]}

    @app.post('/api/memory/tree/folders')
    def create(payload:Folder,current=Depends(user)):
        with db.connect(write=True) as conn:
            tree.node_for(conn,current['id'],payload.parent_id)
            if len(tree.ancestry(conn,current['id'],payload.parent_id))>=8:raise HTTPException(422,'目录最多八层')
            if not payload.title.strip():raise HTTPException(422,'目录名称不能为空')
            if conn.execute('SELECT count(*) FROM memory_nodes WHERE user_id=?',(current['id'],)).fetchone()[0]>=4000:raise HTTPException(422,'目录数量已达上限')
            nid=tree.ensure_node(conn,current['id'],payload.parent_id,payload.title.strip(),'folder:'+payload.parent_id+':'+payload.title.strip(),False)
            return tree.node_for(conn,current['id'],nid)

    @app.put('/api/memory/tree/folders/{nid}')
    def change(nid:str,payload:FolderEdit,current=Depends(user)):
        with db.connect(write=True) as conn:
            node=tree.node_for(conn,current['id'],nid);tree.node_for(conn,current['id'],payload.parent_id)
            if node['system']:raise HTTPException(422,'系统分类会自动维护，请在其下创建自己的目录')
            if node['version']!=payload.version:raise HTTPException(409,'目录已变化，请重新载入')
            branch=tree.descendants(conn,current['id'],nid)
            if payload.parent_id in branch:raise HTTPException(422,'不能把目录移到它自身或子目录')
            height=max(len(tree.ancestry(conn,current['id'],i))-len(tree.ancestry(conn,current['id'],nid)) for i in branch)+1
            if len(tree.ancestry(conn,current['id'],payload.parent_id))+height>8:raise HTTPException(422,'目录最多八层')
            if not payload.title.strip():raise HTTPException(422,'目录名称不能为空')
            conn.execute('UPDATE memory_nodes SET title=?,parent_id=?,version=version+1,updated_at=? WHERE id=?',
                         (payload.title.strip(),payload.parent_id,int(time.time()),nid))
            return tree.node_for(conn,current['id'],nid)

    @app.put('/api/memory/items/{mid}/placement')
    def move(mid:str,payload:Placement,current=Depends(user)):
        from .memory_store import record_revision
        with db.connect(write=True) as conn:
            tree.reconcile(conn,current['id']);tree.node_for(conn,current['id'],payload.node_id)
            row=conn.execute('SELECT version FROM personal_memories WHERE user_id=? AND id=?',(current['id'],mid)).fetchone()
            if not row:raise HTTPException(404,'记忆不存在')
            if row['version']!=payload.version:raise HTTPException(409,'记忆已变化，请重新载入')
            conn.execute('UPDATE memory_node_items SET node_id=?,custom=1 WHERE memory_id=?',(payload.node_id,mid))
            conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),mid))
            record_revision(conn,mid,'user-placement')
            return {'id':mid,'node_id':payload.node_id,'version':payload.version+1,'permissions_changed':False}
