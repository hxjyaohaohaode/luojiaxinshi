"""User-visible memory layers, admission, use feedback and retention controls."""
import json
import time
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import Field,ValidationError

from .db import dumps
from .models import Strict, Version
from .memory import Memory, own, context_for
from .memory_policy import rows_for, catalog
from .memory_store import decorate, insert_memory, record_revision
from .memory_lifecycle import (config, session_state, set_semantics, maintain,
                               feedback, before_forget, event)


class LifecycleSettings(Version):
    version: int = Field(ge=0)
    session_days: int = Field(ge=1,le=90)
    episode_days: int = Field(ge=7,le=365)
    auto_promote: bool = True
    auto_cooldown: bool = True
    cross_session: bool = True
    semantic_reflection: bool = False
    reflection_budget: int = Field(default=2,ge=1,le=8)


class MemoryLifecycle(Version):
    tier: Literal['long_term','episodic']
    shared: bool = True
    status: Literal['active','cooling','archived'] = 'active'
    applies_to: list[str] = Field(default_factory=list,max_length=8)


class Promotion(Strict):
    scope: Literal['current','global','project','topic'] = 'current'
    project_id: str | None = Field(default=None,max_length=40)
    topic: str = Field(default='',max_length=60)
    content: str | None = Field(default=None,max_length=2000)
    session_version: int | None = Field(default=None,ge=0)


class Feedback(Version):
    message_id: str = Field(min_length=1,max_length=40)
    outcome: Literal['helpful','irrelevant','outdated']


def install(app,db,user):
    @app.get('/api/memory/lifecycle')
    def overview(current=Depends(user)):
        uid=current['id']
        with db.connect() as conn:
            counts={r['tier']:r['n'] for r in conn.execute('''SELECT s.tier,count(*) n FROM memory_semantics s
                JOIN personal_memories m ON m.id=s.memory_id WHERE m.user_id=? GROUP BY s.tier''',(uid,))}
            counts['session']=conn.execute('SELECT count(*) FROM memory_session_items WHERE user_id=? AND expires_at>?',(uid,int(time.time()))).fetchone()[0]
            counts['needs_review']=conn.execute('''SELECT count(*) FROM memory_semantics s JOIN personal_memories m ON m.id=s.memory_id
                WHERE m.user_id=? AND s.status IN ('needs_review','cooling')''',(uid,)).fetchone()[0]
            run=conn.execute('SELECT * FROM memory_lifecycle_runs WHERE user_id=?',(uid,)).fetchone()
            return {'settings':config(conn,uid),'counts':counts,
                'reflection_jobs':[dict(r) for r in conn.execute('SELECT j.id,j.state,j.error_code,j.proposal_count,j.created_at,j.finished_at,coalesce(l.not_before,0) not_before,coalesce(l.attempts,0) attempts FROM memory_reflection_jobs j LEFT JOIN memory_reflection_leases l ON l.job_id=j.id WHERE j.user_id=? ORDER BY j.created_at DESC,j.id LIMIT 12',(uid,))],
                'last_maintenance':{'at':run['ran_at'],'report':json.loads(run['report'])} if run else None,
                'events':[dict(r) for r in conn.execute('SELECT memory_id,event,reason,created_at FROM memory_events WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 40',(uid,))]}

    @app.put('/api/memory/lifecycle/settings')
    def settings(payload:LifecycleSettings,current=Depends(user)):
        uid=current['id']
        with db.connect(write=True) as conn:
            previous=config(conn,uid)
            if previous['version']!=payload.version:
                raise HTTPException(409,'生命周期设置已变化，请刷新后重试')
            conn.execute('''INSERT INTO memory_lifecycle_settings VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id)
                DO UPDATE SET session_days=excluded.session_days,episode_days=excluded.episode_days,
                auto_promote=excluded.auto_promote,auto_cooldown=excluded.auto_cooldown,
                cross_session=excluded.cross_session,semantic_reflection=excluded.semantic_reflection,
                reflection_budget=excluded.reflection_budget,version=excluded.version''',
                (uid,payload.session_days,payload.episode_days,int(payload.auto_promote),int(payload.auto_cooldown),int(payload.cross_session),int(payload.semantic_reflection),payload.reflection_budget,payload.version+1))
            conn.execute('DELETE FROM memory_session_items WHERE user_id=? AND expires_at<=?',(uid,int(time.time())))
            conn.execute('UPDATE memory_session_items SET expires_at=expires_at+? WHERE user_id=?',((payload.session_days-previous['session_days'])*86400,uid))
            conn.execute('DELETE FROM memory_lifecycle_runs WHERE user_id=?',(uid,))
            return config(conn,uid)

    @app.post('/api/memory/lifecycle/maintain')
    def maintain_now(current=Depends(user)):
        with db.connect(write=True) as conn:
            return maintain(conn,current['id'])

    @app.put('/api/memory/items/{mid}/lifecycle')
    def configure_memory(mid:str,payload:MemoryLifecycle,current=Depends(user)):
        with db.connect(write=True) as conn:
            item=own(conn,'personal_memories',mid,current['id'])
            if item['version']!=payload.version:
                raise HTTPException(409,'记忆已变化，请刷新后设置')
            if any(len(cue)>80 for cue in payload.applies_to):
                raise HTTPException(422,'适用场景每项最多 80 字')
            if not payload.shared and not item['source_conversation_id']:
                raise HTTPException(422,'仅原会话使用需要先关联来源对话')
            set_semantics(conn,mid,admission='manual',tier=payload.tier,shared=payload.shared,applies_to=payload.applies_to)
            conn.execute('UPDATE memory_semantics SET status=? WHERE memory_id=?',(payload.status,mid))
            conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),mid))
            record_revision(conn,mid,'user-lifecycle')
            event(conn,current['id'],mid,'configured','本人调整层级、共享或使用状态')
            from .memory_api import item_for
            return item_for(conn,current['id'],mid)

    @app.get('/api/memory/session-items')
    def short_term(conversation_id:str|None=None,limit:int=Query(default=100,ge=1,le=200),offset:int=Query(default=0,ge=0),q:str=Query(default='',max_length=1000),current=Depends(user)):
        with db.connect() as conn:
            if conversation_id:own(conn,'conversations',conversation_id,current['id'])
            from .memory_reliability import overlay_sessions
            where=''' FROM memory_session_items s JOIN conversations c ON c.id=s.conversation_id
                LEFT JOIN memory_session_edits e ON e.session_id=s.id WHERE s.user_id=? AND s.expires_at>?
                AND (? IS NULL OR s.conversation_id=?) AND (?='' OR instr(lower(coalesce(e.content,s.content)||' '||c.title),lower(?))>0)'''
            args=(current['id'],int(time.time()),conversation_id,conversation_id,q,q)
            items=[dict(r) for r in conn.execute('SELECT s.*,c.title'+where+' ORDER BY s.created_at DESC,s.rowid DESC LIMIT ? OFFSET ?',(*args,limit,offset))]
            total=conn.execute('SELECT count(*)'+where,args).fetchone()[0]
            return {'items':overlay_sessions(conn,items),'matched':total,'offset':offset,'limit':limit}

    @app.get('/api/conversations/{cid}/memory-state')
    def state(cid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,'conversations',cid,current['id'])
            from .memory_lifecycle import current_key
            return {'state':session_state(conn,current['id'],cid),
                    'checkpoints':[{'version':r['version'],'created_at':r['created_at'],'data':json.loads(r['data'])}
                        for r in conn.execute("SELECT * FROM memory_checkpoints WHERE conversation_id=? AND json_extract(data,'$._context_key')=? ORDER BY version DESC LIMIT 10",(cid,current_key(conn,cid)))]}

    @app.post('/api/memory/session-items/{sid}/promote')
    def promote(sid:str,payload:Promotion,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT * FROM memory_session_items WHERE id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'会话记忆不存在或无权访问')
            if row['expires_at']<=int(time.time()):raise HTTPException(409,'会话片段已过期，请从原对话重新确认')
            edited=conn.execute('SELECT content,version FROM memory_session_edits WHERE session_id=?',(sid,)).fetchone()
            if payload.session_version is not None and payload.session_version!=(edited['version'] if edited else 0):
                raise HTTPException(409,'会话条件已被修订，请重新打开并确认长期保存内容')
            if row['promoted_id'] and conn.execute('SELECT 1 FROM personal_memories WHERE id=?',(row['promoted_id'],)).fetchone():
                existing=conn.execute('SELECT content FROM personal_memories WHERE id=?',(row['promoted_id'],)).fetchone()
                if payload.content is not None and payload.content.strip()!=existing['content']:
                    raise HTTPException(409,'这段内容已经晋升，修改请进入已保存的长期记忆')
                return {'id':row['promoted_id'],'already_promoted':True}
            if not row['context_key'] and payload.scope=='current':raise HTTPException(422,'旧片段缺少原始范围，请明确选择长期使用的项目、专题或通用范围')
            source_context=json.loads(row['context_key']) if row['context_key'] else ['',[]]
            context={'project_id':source_context[0] or None,'topics':source_context[1]}
            scope=payload.scope
            project_id=payload.project_id
            if scope=='current':
                project_id=context['project_id']
                if not project_id and len(context['topics'])>1:raise HTTPException(422,'原片段关联多个专题，请明确选择长期使用范围')
                scope='project' if project_id else 'topic' if context['topics'] else 'global'
            topic=context['topics'][0] if payload.scope=='current' and scope=='topic' else payload.topic
            if scope=='project':
                if not project_id:raise HTTPException(422,'请选择项目')
                own(conn,'memory_projects',project_id,current['id'])
            if scope=='topic' and not topic.strip():raise HTTPException(422,'请选择专题')
            from .memory_learning import classify,semantic_key
            content=payload.content if payload.content is not None else edited['content'] if edited else row['content']
            try:
                value=Memory.model_validate({'scope':scope,'project_id':project_id if scope=='project' else None,
                    'topic':topic if scope=='topic' else '', 'kind':classify(content),
                    'content':content,'source_conversation_id':row['conversation_id'],
                    'semantic_key':semantic_key(content)})
            except ValidationError as error:raise HTTPException(422,'记忆内容或使用范围无效') from error
            mid=insert_memory(conn,current['id'],value.model_dump(),origin='manual',locked=True,
                evidence=[{'source_kind':'message','source_id':row['source_message_id'],'quote':row['content']}])
            conn.execute('UPDATE memory_session_items SET promoted_id=? WHERE id=?',(mid,sid))
            event(conn,current['id'],mid,'promoted','本人确认从会话片段晋升为长期记忆')
            return {'id':mid,'already_promoted':False}

    @app.delete('/api/memory/session-items/{sid}')
    def forget_short(sid:str,current=Depends(user)):
        from .memory_store import digest,forget_memory
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT * FROM memory_session_items WHERE id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'会话片段不存在或无权访问')
            edited=conn.execute('SELECT content FROM memory_session_edits WHERE session_id=?',(sid,)).fetchone()
            source=conn.execute('SELECT content FROM conversation_messages WHERE id=?',(row['source_message_id'],)).fetchone()
            if source and row['content'] in source['content']:
                start=source['content'].find(row['content'])
                conn.execute('INSERT OR IGNORE INTO memory_forgotten_spans VALUES(?,?,?,?,?,?,?)',
                    (current['id'],row['source_message_id'],digest(source['content']),digest(row['content']),start,start+len(row['content']),int(time.time())))
            derived=[dict(r) for r in conn.execute('''SELECT m.* FROM personal_memories m JOIN memory_evidence e ON e.memory_id=m.id
                WHERE m.user_id=? AND e.source_kind='message' AND e.source_id=? AND e.quote=?''',
                (current['id'],row['source_message_id'],row['content']))]
            for memory in derived:forget_memory(conn,current['id'],memory)
            conn.execute('DELETE FROM memory_session_items WHERE source_message_id=? AND instr(content,?)>0',(row['source_message_id'],row['content']))
            conn.execute('DELETE FROM memory_checkpoints WHERE conversation_id=?',(row['conversation_id'],))
            working=conn.execute('SELECT content FROM memory_working WHERE conversation_id=?',(row['conversation_id'],)).fetchone()
            if working:
                cleaned=working['content'].replace(row['content'],'[已遗忘的会话片段]')
                if edited:cleaned=cleaned.replace(edited['content'],'[已遗忘的会话修订]')
                conn.execute('UPDATE memory_working SET content=?,version=version+1 WHERE conversation_id=?',
                    (cleaned,row['conversation_id']))
            conn.execute("UPDATE memory_working_frames SET content=replace(content,?,'[已遗忘的会话片段]'),version=version+1 WHERE conversation_id=? AND instr(content,?)>0",(row['content'],row['conversation_id'],row['content']))
            if edited:conn.execute("UPDATE memory_working_frames SET content=replace(content,?,'[已遗忘的会话修订]'),version=version+1 WHERE conversation_id=? AND instr(content,?)>0",(edited['content'],row['conversation_id'],edited['content']))
            event(conn,current['id'],None,'forgotten_session','本人撤销短期片段及其派生记忆')
            return {'forgotten':True,'derived_deleted':len(derived)}

    @app.post('/api/memory/items/{mid}/feedback')
    def rate(mid:str,payload:Feedback,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,'personal_memories',mid,current['id'])
            chat=conn.execute('SELECT conversation_id FROM conversation_messages WHERE id=?',(payload.message_id,)).fetchone()
            if not chat:raise HTTPException(404,'回答不存在')
            own(conn,'conversations',chat['conversation_id'],current['id'])
            try:return feedback(conn,current['id'],payload.message_id,mid,payload.outcome,payload.version)
            except ValueError as error:raise HTTPException(409,str(error))

    @app.get('/api/conversations/{cid}/messages/{aid}/memory-trace')
    def trace(cid:str,aid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,'conversations',cid,current['id'])
            message=conn.execute("SELECT * FROM conversation_messages WHERE id=? AND conversation_id=? AND role='assistant' AND status='complete'",(aid,cid)).fetchone()
            if not message:raise HTTPException(404,'完整回答不存在')
            report=conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(aid,)).fetchone()
            data=json.loads(report['report']) if report else {}
            items=[dict(r) for r in conn.execute('''SELECT u.*,m.content,m.scope,m.kind,m.version,f.outcome feedback
                FROM memory_usage u JOIN personal_memories m ON m.id=u.memory_id
                LEFT JOIN memory_feedback f ON f.message_id=u.message_id AND f.memory_id=u.memory_id
                WHERE u.message_id=? AND m.user_id=? ORDER BY u.memory_id''',(aid,current['id']))]
            for item in items:
                item['can_feedback']=item['memory_version']==item['version']
                if not item['can_feedback']:
                    revision=conn.execute('SELECT snapshot FROM memory_revisions WHERE memory_id=? AND version=?',(item['memory_id'],item['memory_version'])).fetchone()
                    item['content']=json.loads(revision['snapshot'])['content'] if revision else '[当时的记忆版本已不可用]'
            return {'items':items,'retrieval':data.get('memory',{}),
                'operations':data.get('memory_operations',[]),'note':'提供给回答不等于实际采用；Agent 报告的使用情况与本人反馈分别记录。'}
