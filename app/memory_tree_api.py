"""Tree navigation, direct editing and owner-checked organization."""
import time
from typing import Literal
from fastapi import Depends,HTTPException,Query,Header
from pydantic import Field
from .models import Strict
from .db import ident
from . import memory_tree as tree


class Folder(Strict):
    parent_id:str=Field(max_length=40)
    title:str=Field(min_length=1,max_length=60)


class FolderEdit(Folder):
    version:int=Field(ge=1)


class Placement(Strict):
    node_id:str=Field(max_length=40)
    version:int=Field(ge=1)


class FolderDelete(Strict):
    version:int=Field(ge=1)


class Selection(Strict):
    id:str=Field(min_length=1,max_length=40)
    version:int=Field(ge=1)


class Placements(Strict):
    node_id:str=Field(max_length=40)
    items:list[Selection]=Field(min_length=1,max_length=100)


def install(app,db,user):
    from .memory_reliability import mutation_lookup,mutation_record
    from . import memory_tree_queries as reads
    @app.get('/api/memory/tree/status')
    def change_status(current=Depends(user)):
        with db.connect() as conn:return reads.status(conn,current['id'])

    @app.get('/api/memory/tree/locations')
    def locations(q:str=Query('',max_length=1000),exclude:str|None=Query(None,max_length=40),
                  offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100),current=Depends(user)):
        with db.connect(write=True) as conn:
            tree.reconcile(conn,current['id'])
            return reads.locations(conn,current['id'],q,exclude,offset,limit)

    @app.get('/api/memory/passages/{pid}')
    def passage(pid:str,current=Depends(user)):
        from .memory_resources import source_for
        with db.connect() as conn:
            row=conn.execute('SELECT * FROM memory_source_units WHERE id=? AND user_id=?',(pid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'资料片段不存在')
            value=dict(row);source=source_for(conn,current['id'],row['source_kind'],row['source_id'])
            if (not source or not source['available'] or int(source['fingerprint'])!=row['fingerprint'] or
                conn.execute('SELECT 1 FROM memory_blocked_sources WHERE user_id=? AND source_kind=? AND source_id=?',(current['id'],row['source_kind'],row['source_id'])).fetchone()):
                raise HTTPException(409,'原资料已变化或已停止记忆，请刷新目录')
            value['href']='#notice/'+source['notice_id'] if source.get('notice_id') else '#chat/'+source['conversation_id'] if source.get('conversation_id') else '#memory'
            return value
    @app.get('/api/memory/tree')
    def read_tree(parent_id:str|None=Query(None,max_length=40),offset:int=Query(0,ge=0),current=Depends(user)):
        from .memory_store import settings_for
        with db.connect(write=True) as conn:
            value=tree.snapshot(conn,current['id'],parent_id,offset)
            value['session_count']=conn.execute('SELECT count(*) FROM memory_session_items WHERE user_id=? AND expires_at>?',(current['id'],int(time.time()))).fetchone()[0]
            value['lifecycle_counts']={r['tier']:r['n'] for r in conn.execute('''SELECT s.tier,count(*) n FROM memory_semantics s
                JOIN personal_memories m ON m.id=s.memory_id WHERE m.user_id=? GROUP BY s.tier''',(current['id'],))}
            value['settings']=settings_for(conn,current['id'])
            value['source_passages']=conn.execute('''SELECT count(*) FROM memory_source_units u JOIN memory_resource_versions v USING(source_kind,source_id)
                WHERE u.user_id=? AND u.fingerprint=v.version AND NOT EXISTS(SELECT 1 FROM memory_blocked_sources b
                WHERE b.user_id=u.user_id AND b.source_kind=u.source_kind AND b.source_id=u.source_id)''',(current['id'],)).fetchone()[0]
            return value

    @app.get('/api/memory/tree/entries')
    def entries(node_id:str|None=Query(None,max_length=40),q:str=Query('',max_length=1000),
                offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),
                view:Literal['auto','all','memories','passages']='all',state:Literal['all','active','held','inactive']='all',
                sort:Literal['recent','oldest']='recent',current=Depends(user)):
        with db.connect(write=True) as conn:
            return reads.entries(conn,current['id'],node_id,q,offset,limit,view,state,sort)

    @app.post('/api/memory/tree/folders')
    def create(payload:Folder,current=Depends(user),key:str|None=Header(None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            operation='folder-create';body=payload.model_dump();receipt=mutation_lookup(conn,current['id'],key,operation,body)
            if receipt:return {**receipt,'replayed':True}
            tree.node_for(conn,current['id'],payload.parent_id)
            if len(tree.ancestry(conn,current['id'],payload.parent_id))>=8:raise HTTPException(422,'目录最多八层')
            if not payload.title.strip():raise HTTPException(422,'目录名称不能为空')
            existing=conn.execute('SELECT * FROM memory_nodes WHERE user_id=? AND parent_id=? AND title=?',(current['id'],payload.parent_id,payload.title.strip())).fetchone()
            if existing:
                if existing['system']:raise HTTPException(409,'当前目录已有同名系统分类，请换个名称')
                result=dict(existing);mutation_record(conn,current['id'],key,operation,body,result);return result
            if conn.execute('SELECT count(*) FROM memory_nodes WHERE user_id=?',(current['id'],)).fetchone()[0]>=4000:raise HTTPException(422,'目录数量已达上限')
            nid=tree.ensure_node(conn,current['id'],payload.parent_id,payload.title.strip(),'user-folder:'+ident(),False)
            result=tree.node_for(conn,current['id'],nid)
            mutation_record(conn,current['id'],key,operation,body,result)
            return result

    @app.put('/api/memory/tree/folders/{nid}')
    def change(nid:str,payload:FolderEdit,current=Depends(user),key:str|None=Header(None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            operation='folder-edit:'+nid;body=payload.model_dump();receipt=mutation_lookup(conn,current['id'],key,operation,body)
            if receipt:return {**receipt,'replayed':True}
            node=tree.node_for(conn,current['id'],nid);tree.node_for(conn,current['id'],payload.parent_id)
            if node['system']:raise HTTPException(422,'系统分类会自动维护，请在其下创建自己的目录')
            if node['version']!=payload.version:raise HTTPException(409,'目录已变化，请重新载入')
            branch=tree.descendants(conn,current['id'],nid)
            if payload.parent_id in branch:raise HTTPException(422,'不能把目录移到它自身或子目录')
            height=max(len(tree.ancestry(conn,current['id'],i))-len(tree.ancestry(conn,current['id'],nid)) for i in branch)+1
            if len(tree.ancestry(conn,current['id'],payload.parent_id))+height>8:raise HTTPException(422,'目录最多八层')
            if not payload.title.strip():raise HTTPException(422,'目录名称不能为空')
            if conn.execute('SELECT 1 FROM memory_nodes WHERE user_id=? AND parent_id=? AND title=? AND id<>?',(current['id'],payload.parent_id,payload.title.strip(),nid)).fetchone():
                raise HTTPException(409,'上级目录已有同名目录，请换个名称')
            conn.execute('UPDATE memory_nodes SET title=?,parent_id=?,node_key=?,version=version+1,updated_at=? WHERE id=?',
                         (payload.title.strip(),payload.parent_id,'user-folder:'+nid,int(time.time()),nid))
            result=tree.node_for(conn,current['id'],nid)
            mutation_record(conn,current['id'],key,operation,body,result)
            return result

    @app.delete('/api/memory/tree/folders/{nid}')
    def dissolve(nid:str,payload:FolderDelete,current=Depends(user),key:str|None=Header(None,alias='Idempotency-Key',max_length=80)):
        from .memory_store import record_revision
        with db.connect(write=True) as conn:
            operation='folder-delete:'+nid;body=payload.model_dump();receipt=mutation_lookup(conn,current['id'],key,operation,body)
            if receipt:return {**receipt,'replayed':True}
            node=tree.node_for(conn,current['id'],nid)
            if node['system']:raise HTTPException(422,'系统目录由 AI 自动维护，不能移除')
            if node['version']!=payload.version:raise HTTPException(409,'目录已变化，请重新打开后操作')
            parent=node['parent_id'];now=int(time.time())
            # Dissolving is not a recursive delete: preserve ALL memories,
            # source passages and child folders, even same-named siblings.
            children=list(conn.execute('SELECT id,title FROM memory_nodes WHERE parent_id=? AND user_id=?',(nid,current['id'])))
            for child in children:
                title=child['title'];suffix=1
                while conn.execute('SELECT 1 FROM memory_nodes WHERE parent_id=? AND title=? AND id<>?',(parent,title,child['id'])).fetchone():
                    suffix+=1;title=child['title'][:50]+f'（{suffix}）'
                conn.execute('UPDATE memory_nodes SET parent_id=?,title=?,node_key=?,version=version+1,updated_at=? WHERE id=?',(parent,title,'user-folder:'+child['id'],now,child['id']))
            memories=[r[0] for r in conn.execute('SELECT memory_id FROM memory_node_items WHERE node_id=?',(nid,))]
            conn.execute('UPDATE memory_node_items SET node_id=?,custom=1 WHERE node_id=?',(parent,nid))
            conn.execute('UPDATE memory_source_units SET node_id=? WHERE node_id=?',(parent,nid))
            for mid in memories:
                conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(now,mid))
                record_revision(conn,mid,'user-folder-removed')
            conn.execute('DELETE FROM memory_nodes WHERE id=? AND user_id=?',(nid,current['id']))
            result={'removed':True,'parent_id':parent,'preserved_memories':len(memories),'preserved_folders':len(children)}
            mutation_record(conn,current['id'],key,operation,body,result)
            return result

    def apply_placements(conn,uid,payload):
        from .memory_store import record_revision
        tree.reconcile(conn,uid);tree.node_for(conn,uid,payload.node_id)
        if len({entry.id for entry in payload.items})!=len(payload.items):raise HTTPException(422,'选择中存在重复记忆')
        for entry in payload.items:
            row=conn.execute('SELECT version FROM personal_memories WHERE user_id=? AND id=?',(uid,entry.id)).fetchone()
            if not row:raise HTTPException(404,'记忆不存在，请刷新后重试')
            if row['version']!=entry.version:raise HTTPException(409,'有记忆已变化，本次没有移动任何条目，请刷新后重试')
        for entry in payload.items:
            conn.execute('UPDATE memory_node_items SET node_id=?,custom=1 WHERE memory_id=?',(payload.node_id,entry.id))
            conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),entry.id))
            record_revision(conn,entry.id,'user-placement')
        return {'node_id':payload.node_id,'permissions_changed':False,'items':[{'id':m.id,'version':m.version+1} for m in payload.items]}

    @app.put('/api/memory/tree/placements')
    def move_many(payload:Placements,current=Depends(user),key:str|None=Header(None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            operation='placements';body=payload.model_dump();receipt=mutation_lookup(conn,current['id'],key,operation,body)
            if receipt:return {**receipt,'replayed':True}
            result=apply_placements(conn,current['id'],payload)
            mutation_record(conn,current['id'],key,operation,body,result)
            return result

    @app.put('/api/memory/items/{mid}/placement')
    def move(mid:str,payload:Placement,current=Depends(user),key:str|None=Header(None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            operation='placement:'+mid;body=payload.model_dump();receipt=mutation_lookup(conn,current['id'],key,operation,body)
            if receipt:return {**receipt,'replayed':True}
            result=apply_placements(conn,current['id'],Placements(node_id=payload.node_id,items=[Selection(id=mid,version=payload.version)]))
            result.update({'id':mid,'version':payload.version+1})
            mutation_record(conn,current['id'],key,operation,body,result)
            return result
