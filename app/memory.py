"""Explicit user-owned memory with global, project and topic scopes."""
import json
import hashlib
import re
import time
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field, model_validator

from .db import dumps, ident
from .models import Strict, Version
from .context_engine import terms
from .memory_policy import rows_for,save_policy,effective,catalog,duplicate,normalized,scope_key,temporal_state

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_projects(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL,description TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS memory_projects_owner ON memory_projects(user_id);
CREATE TABLE IF NOT EXISTS personal_memories(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 scope TEXT NOT NULL,project_id TEXT REFERENCES memory_projects(id) ON DELETE CASCADE,
 topic TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL,content TEXT NOT NULL,
 source_conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
 active INTEGER NOT NULL DEFAULT 1,pinned INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS personal_memories_owner ON personal_memories(user_id,active,scope);
CREATE TABLE IF NOT EXISTS conversation_context(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 project_id TEXT REFERENCES memory_projects(id) ON DELETE SET NULL,
 topics TEXT NOT NULL DEFAULT '[]',memory_enabled INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL DEFAULT 1);
INSERT OR IGNORE INTO meta VALUES('memory_schema_version','1');
"""


class Project(Strict):
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(default='',max_length=1000)


class ProjectUpdate(Project,Version):
    pass


class Memory(Strict):
    scope: Literal['global','project','topic'] = 'global'
    project_id: str | None = Field(default=None,max_length=40)
    topic: str = Field(default='',max_length=60)
    kind: Literal['preference','constraint','decision','fact'] = 'preference'
    content: str = Field(min_length=1,max_length=2000)
    source_conversation_id: str | None = Field(default=None,max_length=40)
    active: bool = True
    pinned: bool = False
    semantic_key: str = Field(default='',max_length=80)
    valid_from: int | None = Field(default=None,ge=0,le=253402300799)
    expires_at: int | None = Field(default=None,ge=0,le=253402300799)

    @model_validator(mode='after')
    def valid_scope(self):
        self.semantic_key=normalized(self.semantic_key)
        if self.valid_from is not None and self.expires_at is not None and self.expires_at<=self.valid_from:
            raise ValueError('失效时间必须晚于生效时间')
        if (self.scope=='project') != bool(self.project_id):
            raise ValueError('项目记忆必须选择项目，其他范围不能绑定项目')
        if (self.scope=='topic') != bool(self.topic):
            raise ValueError('专题记忆必须填写专题，其他范围不能填写专题')
        if re.search(r'\b(?:sk|tp|ttp)-[a-zA-Z0-9_-]{16,}|-----BEGIN .*PRIVATE KEY',self.content):
            raise ValueError('记忆不能保存 API 密钥或私钥，请使用本机服务配置')
        return self


class MemoryUpdate(Memory,Version):
    pass


class ResolveMemory(Strict):
    versions: dict[str,int] = Field(min_length=2,max_length=500)


class Context(Strict):
    project_id: str | None = Field(default=None,max_length=40)
    topics: list[str] = Field(default_factory=list,max_length=8)
    memory_enabled: bool = True
    version: int = Field(ge=0)

    @model_validator(mode='after')
    def bounded_topics(self):
        self.topics=list(dict.fromkeys(t.strip() for t in self.topics if t.strip()))
        if any(len(t)>60 for t in self.topics):
            raise ValueError('专题名称不能超过 60 字')
        return self


def own(conn,table,key,uid):
    row=conn.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=?',(key,uid)).fetchone()
    if not row:
        raise HTTPException(404,'记录不存在或无权访问')
    return row


def context_for(conn,cid):
    row=conn.execute('SELECT * FROM conversation_context WHERE conversation_id=?',(cid,)).fetchone()
    if not row:
        return {'project_id':None,'topics':[],'memory_enabled':True,'version':0}
    return {'project_id':row['project_id'],'topics':json.loads(row['topics']),'memory_enabled':bool(row['memory_enabled']),'version':row['version']}


def memory_access(messages):
    from .retrieval_scope import user_request
    allowed=True
    for message in messages:
        if message.get('role')!='user':continue
        for clause in re.split(r'[。；，,;\n]',user_request(message)):
            if re.search(r'(?:不要|不用|禁止|不使用|关闭).{0,8}(?:记忆|以前的偏好)',clause):allowed=False
            elif re.search(r'(?:允许|可以|启用|恢复使用).{0,8}(?:记忆|以前的偏好)',clause):allowed=True
    return allowed


def eligible_versions(conn,uid,cid,allowed):
    own(conn,'conversations',cid,uid)
    context=context_for(conn,cid)
    if not allowed or not context['memory_enabled']:return {}
    versions={}
    items,_=effective(rows_for(conn,uid),context)
    for row in items:versions['memory-'+row['id']]=row['version']
    if context['project_id']:
        project=own(conn,'memory_projects',context['project_id'],uid)
        versions['memory-'+hashlib.sha256(('project:'+project['id']).encode()).hexdigest()[:32]]=project['version']
    return versions


def recall(db,uid,cid,question,access):
    """Only explicitly saved, current, in-scope memory; no cross-user search."""
    allowed=access.get('memory',not re.search(r'(?:不要|不用|禁止|不使用).{0,8}(?:记忆|以前的偏好|历史记忆)',question))
    if not access.get('profile') or not allowed:
        return [],{'enabled':False,'selected':0}
    with db.connect() as conn:
        own(conn,'conversations',cid,uid)
        context=context_for(conn,cid)
        if not context['memory_enabled']:
            return [],{'enabled':False,'selected':0}
        candidates=[]
        query=terms(question)
        items,excluded=effective(rows_for(conn,uid),context)
        for item in items:
            score=len(query & terms(item['content']))
            if item['pinned'] or item['kind'] in ('preference','constraint') or score:
                candidates.append((int(item['pinned'])*100+int(item['kind']=='constraint')*20+score,item))
        selected=[];used=0
        if context['project_id']:
            project=dict(own(conn,'memory_projects',context['project_id'],uid))
            content='你选择的项目名称：'+project['name']+('。项目说明：'+project['description'] if project['description'] else '')
            selected.append({'id':hashlib.sha256(('project:'+project['id']).encode()).hexdigest()[:32],
                'scope':'project','project_id':project['id'],'topic':'','kind':'fact','content':content,
                'version':project['version'],'updated_at':project['updated_at'],'project_context':True})
            used=len(content.encode('utf-8'))+240
        for _,item in sorted(candidates,key=lambda x:x[0],reverse=True):
            cost=len(item['content'].encode('utf-8'))+240
            if len(selected)>=12 or used+cost>8000:
                continue
            selected.append({k:item[k] for k in ('id','scope','project_id','topic','kind','content','version','updated_at')});used+=cost
        count=sum(not item.get('project_context') for item in selected)
        return selected,{'enabled':True,'selected':count,'eligible':len(candidates),'omitted':len(candidates)-count,'project_id':context['project_id'],'topics':context['topics'],'project_context':bool(context['project_id']),
            'excluded':excluded,'policy_version':'memory-policy-v1'}


def install_memory(app,db,user):
    def saved_item(conn,mid,uid):
        return next(item for item in catalog(rows_for(conn,uid)) if item['id']==mid)

    @app.get('/api/memory')
    def list_memory(current=Depends(user)):
        with db.connect() as conn:
            return {'projects':[dict(r) for r in conn.execute('SELECT * FROM memory_projects WHERE user_id=? ORDER BY updated_at DESC,id',(current['id'],))],
                'memories':catalog(rows_for(conn,current['id']))}

    @app.post('/api/memory/projects')
    def create_project(payload:Project,current=Depends(user)):
        with db.connect(write=True) as conn:
            if conn.execute('SELECT count(*) FROM memory_projects WHERE user_id=?',(current['id'],)).fetchone()[0]>=100:
                raise HTTPException(422,'项目数量已达 100，请先整理不再使用的项目')
            key=ident();now=int(time.time())
            conn.execute('INSERT INTO memory_projects VALUES(?,?,?,?,1,?,?)',(key,current['id'],payload.name,payload.description,now,now))
            return dict(own(conn,'memory_projects',key,current['id']))

    @app.put('/api/memory/projects/{pid}')
    def update_project(pid:str,payload:ProjectUpdate,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=own(conn,'memory_projects',pid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'项目已修改，请刷新后核对')
            conn.execute('UPDATE memory_projects SET name=?,description=?,version=version+1,updated_at=? WHERE id=?',(payload.name,payload.description,int(time.time()),pid))
            return dict(own(conn,'memory_projects',pid,current['id']))

    @app.delete('/api/memory/projects/{pid}')
    def delete_project(pid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=own(conn,'memory_projects',pid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'项目已修改，请刷新后核对')
            conn.execute('UPDATE conversation_context SET version=version+1 WHERE project_id=?',(pid,))
            conn.execute('DELETE FROM memory_projects WHERE id=?',(pid,))
            return {'deleted':True}

    def validate_links(conn,payload,uid):
        if payload.project_id:own(conn,'memory_projects',payload.project_id,uid)
        if payload.source_conversation_id:own(conn,'conversations',payload.source_conversation_id,uid)

    @app.post('/api/memory/items')
    def create_memory(payload:Memory,current=Depends(user)):
        with db.connect(write=True) as conn:
            validate_links(conn,payload,current['id'])
            existing=duplicate(rows_for(conn,current['id']),payload)
            if existing:return saved_item(conn,existing['id'],current['id'])
            if conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(current['id'],)).fetchone()[0]>=500:
                raise HTTPException(422,'记忆数量已达 500，请先整理重复或过期内容')
            key=ident();now=int(time.time())
            conn.execute('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)',(key,current['id'],payload.scope,payload.project_id,payload.topic,payload.kind,payload.content,payload.source_conversation_id,int(payload.active),int(payload.pinned),now,now))
            save_policy(conn,key,payload.model_dump())
            return saved_item(conn,key,current['id'])

    @app.put('/api/memory/items/{mid}')
    def update_memory(mid:str,payload:MemoryUpdate,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=own(conn,'personal_memories',mid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'记忆已修改，请刷新后核对')
            validate_links(conn,payload,current['id'])
            if duplicate(rows_for(conn,current['id']),payload,excluding=mid):
                raise HTTPException(409,'已有完全相同的记忆，请保留已有记录并删除重复项')
            conn.execute('UPDATE personal_memories SET scope=?,project_id=?,topic=?,kind=?,content=?,source_conversation_id=?,active=?,pinned=?,version=version+1,updated_at=? WHERE id=?',
                (payload.scope,payload.project_id,payload.topic,payload.kind,payload.content,payload.source_conversation_id,int(payload.active),int(payload.pinned),int(time.time()),mid))
            save_policy(conn,mid,payload.model_dump())
            return saved_item(conn,mid,current['id'])

    @app.post('/api/memory/items/{mid}/resolve')
    def resolve(mid:str,payload:ResolveMemory,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,'personal_memories',mid,current['id'])
            items=rows_for(conn,current['id']);chosen=next(item for item in items if item['id']==mid)
            if not chosen['semantic_key'] or temporal_state(chosen)!='active':
                raise HTTPException(409,'请先启用一条当前有效且具有同类键的记忆')
            peers=[item for item in items if scope_key(item)==scope_key(chosen) and item['semantic_key']==chosen['semantic_key'] and temporal_state(item)=='active']
            if len({normalized(item['content']) for item in peers})<2 or {item['id']:item['version'] for item in peers}!=payload.versions:
                raise HTTPException(409,'冲突内容或版本已变化，请刷新后重新选择')
            now=int(time.time())
            for item in peers:
                if item['id']!=mid:conn.execute('UPDATE personal_memories SET active=0,version=version+1,updated_at=? WHERE id=?',(now,item['id']))
            conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(now,mid))
            return {'kept':saved_item(conn,mid,current['id']),'deactivated':[item['id'] for item in peers if item['id']!=mid]}

    @app.delete('/api/memory/items/{mid}')
    def delete_memory(mid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=own(conn,'personal_memories',mid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'记忆已修改，请刷新后核对')
            conn.execute('DELETE FROM personal_memories WHERE id=?',(mid,))
            return {'deleted':True}

    @app.get('/api/conversations/{cid}/context')
    def get_context(cid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,'conversations',cid,current['id'])
            return context_for(conn,cid)

    @app.get('/api/conversations/{cid}/memory-preview')
    def preview(cid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,'conversations',cid,current['id'])
            context=context_for(conn,cid)
            items,excluded=effective(rows_for(conn,current['id']),context)
            return {'context_version':context['version'],'enabled':context['memory_enabled'],
                'eligible':[{'id':item['id'],'content':item['content'],'scope':item['scope'],'semantic_key':item['semantic_key']} for item in items] if context['memory_enabled'] else [],
                'excluded':excluded if context['memory_enabled'] else [],'note':'当前已保存范围；实际回答会再按问题相关性和长度预算选择。'}

    @app.put('/api/conversations/{cid}/context')
    def set_context(cid:str,payload:Context,current=Depends(user)):
        with db.connect(write=True) as conn:
            chat=own(conn,'conversations',cid,current['id'])
            if chat['processing_token']:raise HTTPException(409,'请等待回复结束或先停止，再调整项目和记忆')
            if payload.project_id:own(conn,'memory_projects',payload.project_id,current['id'])
            saved=context_for(conn,cid)
            if saved['version']!=payload.version:raise HTTPException(409,'对话记忆设置已修改，请刷新后核对')
            conn.execute('INSERT INTO conversation_context VALUES(?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET project_id=excluded.project_id,topics=excluded.topics,memory_enabled=excluded.memory_enabled,version=excluded.version',
                (cid,payload.project_id,dumps(payload.topics),int(payload.memory_enabled),payload.version+1))
            return context_for(conn,cid)
