"""User-owned memory with scoped retrieval and reversible lifecycle controls."""
import json
import hashlib
import re
import time
from typing import Literal

from fastapi import Depends, HTTPException, Query, Header
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
    kind: Literal['preference','constraint','decision','fact','episode','skill','intention','summary'] = 'preference'
    content: str = Field(min_length=1,max_length=2000)
    source_conversation_id: str | None = Field(default=None,max_length=40)
    active: bool = True
    pinned: bool = False
    semantic_key: str = Field(default='',max_length=80)
    valid_from: int | None = Field(default=None,ge=0,le=253402300799)
    expires_at: int | None = Field(default=None,ge=0,le=253402300799)
    locked: bool = True
    labels: list[str] = Field(default_factory=list,max_length=8)

    @model_validator(mode='after')
    def valid_scope(self):
        self.semantic_key=normalized(self.semantic_key)
        self.content=self.content.strip()
        self.topic=self.topic.strip()
        self.labels=list(dict.fromkeys(label.strip() for label in self.labels if label.strip()))
        if not self.content or any(len(label)>40 for label in self.labels):
            raise ValueError('记忆内容不能为空，标签不能超过 40 字')
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
    reactivate: bool = False


class ResolveMemory(Strict):
    versions: dict[str,int] = Field(min_length=2,max_length=10000)


class Context(Strict):
    project_id: str | None = Field(default=None,max_length=40)
    topics: list[str] = Field(default_factory=list,max_length=8)
    memory_enabled: bool = True
    version: int = Field(ge=0)
    selection_mode: Literal['auto','manual'] | None = None

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
    from .memory_autonomy import mode_for
    selection_mode=mode_for(conn,cid)
    row=conn.execute('SELECT * FROM conversation_context WHERE conversation_id=?',(cid,)).fetchone()
    if not row:
        return {'project_id':None,'topics':[],'memory_enabled':True,'version':0,'selection_mode':selection_mode}
    return {'project_id':row['project_id'],'topics':json.loads(row['topics']),'memory_enabled':bool(row['memory_enabled']),'version':row['version'],'selection_mode':selection_mode}


def memory_access(messages):
    from .retrieval_scope import user_request
    allowed=True
    users=[m for m in messages if m.get('role')=='user']
    for index,message in enumerate(users):
        request=user_request(message)
        if index<len(users)-1 and re.search(r'仅本次|只在本次|仅本轮|本轮|这轮|这次',request) and not re.search(r'以后|今后|始终|永久|每次',request):continue
        for clause in re.split(r'[。；，,;\n]',request):
            if re.search(r'(?:不要|不用|禁止|不使用|关闭).{0,8}(?:记忆|以前的偏好)',clause):allowed=False
            elif re.search(r'(?:允许|可以|启用|恢复使用).{0,8}(?:记忆|以前的偏好)',clause):allowed=True
    return allowed


def eligible_versions(conn,uid,cid,allowed,access=None,memory_ids=None):
    from .memory_store import settings_for,usable_derived,decorate
    own(conn,'conversations',cid,uid)
    context=context_for(conn,cid)
    if not allowed or not context['memory_enabled'] or settings_for(conn,uid)['mode']=='off':return {}
    versions={}
    ids={key.removeprefix('memory-') for key in memory_ids} if memory_ids is not None else None
    from .memory_reliability import candidates
    items,_=candidates(conn,uid,cid,access or {},ids=ids)
    for row in items:
        if memory_ids is None or 'memory-'+row['id'] in memory_ids:versions['memory-'+row['id']]=row['version']
    if context['project_id']:
        project=own(conn,'memory_projects',context['project_id'],uid)
        versions['memory-'+hashlib.sha256(('project:'+project['id']).encode()).hexdigest()[:32]]=project['version']
    return versions


def recall(db,uid,cid,question,access,queries=None):
    """Current accepted memories only; retrieval never widens the trusted scope."""
    from .memory_store import settings_for,decorate,usable_derived
    from .memory_search import ranked
    allowed=access.get('memory',not re.search(r'(?:不要|不用|禁止|不使用).{0,8}(?:记忆|以前的偏好|历史记忆)',question))
    if not access.get('profile') or not allowed:
        return [],{'enabled':False,'selected':0}
    with db.connect() as conn:
        own(conn,'conversations',cid,uid)
        context=context_for(conn,cid)
        if not context['memory_enabled'] or settings_for(conn,uid)['mode']=='off':
            return [],{'enabled':False,'selected':0}
        if len(question)<45 and re.search(r'继续|然后呢|按刚才|接着|下一步|那怎么办',question):
            from .memory_lifecycle import session_state
            session=session_state(conn,uid,cid)
            queries=[*(queries or []),session['goal'],*(r['text'] for r in session['recent_requests'][:-1])][-4:]
        from .memory_reliability import candidates
        items,excluded=candidates(conn,uid,cid,access,question+' '+' '.join(queries or []))
        names={row['id']:row['name'] for row in conn.execute('SELECT id,name FROM memory_projects WHERE user_id=?',(uid,))}
        for item in items:item['scope_name']=names.get(item['project_id'],'') if item['scope']=='project' else item['topic'] if item['scope']=='topic' else '通用'
        selected=[];used=0
        if context['project_id']:
            project=dict(own(conn,'memory_projects',context['project_id'],uid))
            content='你选择的项目名称：'+project['name']+('。项目说明：'+project['description'] if project['description'] else '')
            selected.append({'id':hashlib.sha256(('project:'+project['id']).encode()).hexdigest()[:32],
                'scope':'project','project_id':project['id'],'topic':'','kind':'fact','content':content,
                'version':project['version'],'updated_at':project['updated_at'],'project_context':True})
            used=len(dumps(selected[0]).encode('utf-8'))+1
        ranked_items,ranking=ranked(conn,uid,items,question,queries,limit=12-len(selected),byte_budget=8000-used,prompt_only=True)
        for item in ranked_items:
            selected.append({k:item[k] for k in ('id','scope','project_id','topic','kind','content','version','updated_at',
                'origin','locked','labels','recall_score','recall_reasons','tier','facet','admission','last_confirmed_at','scope_name')})
        count=sum(not item.get('project_context') for item in selected)
        return selected,{'enabled':True,'selected':count,'eligible':ranking['matched'],'omitted':ranking['matched']-count,'project_id':context['project_id'],'topics':context['topics'],'project_context':bool(context['project_id']),
            'excluded':excluded,'automatic_selection':context['selection_mode']=='auto','selected_project_ids':sorted({item['project_id'] for item in selected if item.get('project_id')}),'policy_version':'memory-autonomy-v5',**ranking,'context_bytes':used+ranking['context_bytes']}


def install_memory(app,db,user):
    from .memory_store import decorate,insert_memory,record_revision,invalidate_dependents,settings_for,MAX_MEMORIES
    def saved_item(conn,mid,uid):
        return next(item for item in catalog(decorate(conn,rows_for(conn,uid,[mid]))) if item['id']==mid)

    @app.get('/api/memory')
    def list_memory(q:str=Query(default='',max_length=1000),scope:str=Query(default='all',pattern='^(all|global|project|topic)$'),
                    status:str=Query(default='all',pattern='^(all|active|pending|attention|archived|cooling|needs_review|source_changed|expired|inactive|conflict|scheduled)$'),
                    kind:str=Query(default='all',pattern='^(all|preference|constraint|decision|fact|episode|skill|intention|summary)$'),
                    tier:str=Query(default='all',pattern='^(all|long_term|episodic)$'),project_id:str|None=Query(default=None,max_length=40),
                    limit:int=Query(default=200,ge=1,le=500),offset:int=Query(default=0,ge=0),current=Depends(user)):
        with db.connect() as conn:
            from .memory_reliability import memory_catalog
            if project_id:own(conn,'memory_projects',project_id,current['id'])
            items=memory_catalog(conn,current['id'])
            state_counts={}
            for item in items:state_counts[item['state']]=state_counts.get(item['state'],0)+1
            counts={key:sum(item['scope']==key for item in items) for key in ('global','project','topic')}
            projects=[dict(r) for r in conn.execute('SELECT * FROM memory_projects WHERE user_id=? ORDER BY updated_at DESC,id',(current['id'],))]
            names={p['id']:p['name'] for p in projects}
            filtered=[item for item in items if (scope=='all' or item['scope']==scope) and
                      (kind=='all' or item['kind']==kind) and (tier=='all' or item['tier']==tier) and (not project_id or item['project_id']==project_id) and
                      (status=='all' or item['state']==status or status=='attention' and item['state'] in ('conflict','source_changed','needs_review','cooling','expired')) and
                      (not q or normalized(q) in normalized(item['content']+' '+item['topic']+' '+names.get(item['project_id'],'')+' '+' '.join(item['labels'])))]
            return {'projects':projects,'memories':filtered[offset:offset+limit],'total':len(items),
                'matched':len(filtered),'offset':offset,'limit':limit,'counts':counts,
                'state_counts':state_counts,
                'pending':sum(item['review_status']=='pending' for item in items),'settings':settings_for(conn,current['id']),
                'topics':sorted({item['topic'] for item in items if item['topic']}),
                'lifecycle_counts':{key:sum(item.get('tier')==key for item in items) for key in ('long_term','episodic')},
                'session_count':conn.execute('SELECT count(*) FROM memory_session_items WHERE user_id=? AND expires_at>?',(current['id'],int(time.time()))).fetchone()[0]}

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
    def create_memory(payload:Memory,current=Depends(user),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            from .memory_reliability import mutation_lookup,mutation_record,mutation_item
            receipt=mutation_lookup(conn,current['id'],idempotency_key,'create',payload.model_dump())
            if receipt:return mutation_item(conn,current['id'],receipt,saved_item)
            validate_links(conn,payload,current['id'])
            existing=duplicate(rows_for(conn,current['id']),payload)
            if existing:
                mutation_record(conn,current['id'],idempotency_key,'create',payload.model_dump(),{'id':existing['id'],'version':existing['version']})
                return saved_item(conn,existing['id'],current['id'])
            if conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(current['id'],)).fetchone()[0]>=MAX_MEMORIES:
                raise HTTPException(422,'记忆数量已达上限，请先整理或导出')
            key=insert_memory(conn,current['id'],payload.model_dump(),locked=payload.locked,labels=payload.labels)
            mutation_record(conn,current['id'],idempotency_key,'create',payload.model_dump(),{'id':key,'version':1})
            return saved_item(conn,key,current['id'])

    @app.put('/api/memory/items/{mid}')
    def update_memory(mid:str,payload:MemoryUpdate,current=Depends(user),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            from .memory_reliability import mutation_lookup,mutation_record,mutation_item
            receipt=mutation_lookup(conn,current['id'],idempotency_key,'update:'+mid,payload.model_dump())
            if receipt:return mutation_item(conn,current['id'],receipt,saved_item)
            row=own(conn,'personal_memories',mid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'记忆已修改，请刷新后核对')
            validate_links(conn,payload,current['id'])
            if duplicate(rows_for(conn,current['id']),payload,excluding=mid):
                raise HTTPException(409,'已有完全相同的记忆，请保留已有记录并删除重复项')
            old_life=conn.execute('SELECT tier,status FROM memory_semantics WHERE memory_id=?',(mid,)).fetchone()
            from .memory_reliability import SOURCE_FIELDS
            old_policy=conn.execute('SELECT semantic_key,valid_from,expires_at FROM memory_policies WHERE memory_id=?',(mid,)).fetchone()
            original={**dict(row),**(dict(old_policy) if old_policy else {})}
            if any(original.get(field)!=payload.model_dump().get(field) for field in SOURCE_FIELDS):invalidate_dependents(conn,mid)
            conn.execute('UPDATE personal_memories SET scope=?,project_id=?,topic=?,kind=?,content=?,source_conversation_id=?,active=?,pinned=?,version=version+1,updated_at=? WHERE id=?',
                (payload.scope,payload.project_id,payload.topic,payload.kind,payload.content,payload.source_conversation_id,int(payload.active),int(payload.pinned),int(time.time()),mid))
            save_policy(conn,mid,payload.model_dump())
            conn.execute("UPDATE memory_details SET locked=?,labels=?,review_status='accepted' WHERE memory_id=?",
                (int(payload.locked),dumps(payload.labels),mid))
            from .memory_lifecycle import set_semantics
            set_semantics(conn,mid,admission='manual',tier=old_life['tier'] if old_life and row['kind']==payload.kind else None)
            if old_life and not payload.reactivate:
                conn.execute('UPDATE memory_semantics SET status=? WHERE memory_id=?',(old_life['status'],mid))
            record_revision(conn,mid,'user')
            mutation_record(conn,current['id'],idempotency_key,'update:'+mid,payload.model_dump(),{'id':mid,'version':row['version']+1})
            return saved_item(conn,mid,current['id'])

    @app.post('/api/memory/items/{mid}/resolve')
    def resolve(mid:str,payload:ResolveMemory,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,'personal_memories',mid,current['id'])
            from .memory_reliability import memory_catalog
            items=memory_catalog(conn,current['id']);chosen=next(item for item in items if item['id']==mid)
            if not chosen['semantic_key'] or chosen['state']!='conflict':
                raise HTTPException(409,'请先启用一条当前有效且具有同类键的记忆')
            peers=[item for item in items if scope_key(item)==scope_key(chosen) and item['semantic_key']==chosen['semantic_key'] and item['state']=='conflict']
            if len({normalized(item['content']) for item in peers})<2 or {item['id']:item['version'] for item in peers}!=payload.versions:
                raise HTTPException(409,'冲突内容或版本已变化，请刷新后重新选择')
            now=int(time.time())
            for item in peers:
                if item['id']!=mid:
                    conn.execute('UPDATE personal_memories SET active=0,version=version+1,updated_at=? WHERE id=?',(now,item['id']))
                    record_revision(conn,item['id'],'user-resolved')
            conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(now,mid))
            record_revision(conn,mid,'user-resolved')
            return {'kept':saved_item(conn,mid,current['id']),'deactivated':[item['id'] for item in peers if item['id']!=mid]}

    @app.delete('/api/memory/items/{mid}')
    def delete_memory(mid:str,payload:Version,current=Depends(user),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            from .memory_reliability import mutation_lookup,mutation_record
            receipt=mutation_lookup(conn,current['id'],idempotency_key,'forget:'+mid,payload.model_dump())
            if receipt:return {**receipt,'replayed':True}
            row=own(conn,'personal_memories',mid,current['id'])
            if row['version']!=payload.version:raise HTTPException(409,'记忆已修改，请刷新后核对')
            from .memory_store import forget_memory
            forget_memory(conn,current['id'],dict(row))
            mutation_record(conn,current['id'],idempotency_key,'forget:'+mid,payload.model_dump(),{'deleted':True})
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
            from .memory_reliability import candidates
            from .retrieval_scope import account_access
            history=[dict(r) for r in conn.execute('SELECT role,content FROM conversation_messages WHERE conversation_id=? ORDER BY rowid',(cid,))]
            items,excluded=candidates(conn,current['id'],cid,account_access(history))
            enabled=context['memory_enabled'] and settings_for(conn,current['id'])['mode']!='off'
            return {'context_version':context['version'],'enabled':bool(enabled),
                'eligible':[{'id':item['id'],'content':item['content'],'scope':item['scope'],'semantic_key':item['semantic_key']} for item in items] if enabled else [],
                'excluded':excluded if enabled else [],'note':'当前已保存范围；实际回答会再按问题相关性和长度预算选择。'}

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
            mode='manual' if payload.project_id or payload.topics else payload.selection_mode or 'manual'
            conn.execute('INSERT INTO memory_selection_modes VALUES(?,?) ON CONFLICT(conversation_id) DO UPDATE SET mode=excluded.mode',(cid,mode))
            return context_for(conn,cid)

    from .memory_api import install
    install(app,db,user)
