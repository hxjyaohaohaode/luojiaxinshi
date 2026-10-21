"""Review queues, safe batch changes, independent session edits and quality facts."""
import json
import time
import re
from typing import Literal

from fastapi import Depends,HTTPException,Header,Query
from pydantic import Field

from .db import dumps
from .models import Strict
from .memory import own
from .memory_policy import rows_for
from .memory_store import record_revision,forget_memory
from .memory_lifecycle import event,set_semantics
from .memory_reliability import memory_catalog,overlay_sessions,mutation_lookup,mutation_record


class Selection(Strict):
    id:str=Field(min_length=1,max_length=40)
    version:int=Field(ge=1)


class Batch(Strict):
    action:Literal['archive','activate','lock','unlock','forget']
    items:list[Selection]=Field(min_length=1,max_length=100)


class SessionEdit(Strict):
    version:int=Field(ge=0)
    content:str=Field(min_length=1,max_length=2000)
    lifetime:Literal['turn','session']='session'


class ReflectionRetry(Strict):
    finished_at:int=Field(ge=0)
    allow_external_processing:bool=False


def install(app,db,user):
    @app.get('/api/memory/session-items/{sid}')
    def session_item(sid:str,current=Depends(user)):
        with db.connect() as conn:
            row=own(conn,'memory_session_items',sid,current['id'])
            item=overlay_sessions(conn,[dict(row)])[0]
            item['title']=conn.execute('SELECT title FROM conversations WHERE id=?',(item['conversation_id'],)).fetchone()[0]
            return item

    @app.get('/api/memory/items/{mid}/conflicts')
    def conflicts(mid:str,current=Depends(user)):
        from .memory_policy import scope_key
        with db.connect() as conn:
            own(conn,'personal_memories',mid,current['id'])
            entries=memory_catalog(conn,current['id']);chosen=next(item for item in entries if item['id']==mid)
            peers=[item for item in entries if item['state']=='conflict' and scope_key(item)==scope_key(chosen) and item['semantic_key']==chosen['semantic_key']]
            if chosen['state']!='conflict' or len(peers)<2:raise HTTPException(409,'同类记忆已变化，请重新载入')
            return {'total':len(peers),'versions':{item['id']:item['version'] for item in peers},'items':[{'id':item['id'],'version':item['version'],'content':item['content']} for item in peers[:20]]}

    @app.get('/api/memory/events')
    def events(cursor:str|None=Query(default=None,max_length=80),limit:int=Query(default=50,ge=1,le=100),current=Depends(user)):
        with db.connect() as conn:
            args=[current['id']];restriction=''
            if cursor:
                match=re.fullmatch(r'(\d{1,12}):([a-zA-Z0-9_-]{1,40})',cursor)
                if not match:raise HTTPException(422,'记录游标无效，请重新载入')
                restriction=' AND (created_at<? OR (created_at=? AND id<?))';args.extend((int(match[1]),int(match[1]),match[2]))
            rows=[dict(row) for row in conn.execute('SELECT id,event,reason,memory_id,created_at FROM memory_events WHERE user_id=?'+restriction+' ORDER BY created_at DESC,id DESC LIMIT ?',(*args,limit+1))]
            visible=rows[:limit]
            return {'items':visible,'next_cursor':f"{visible[-1]['created_at']}:{visible[-1]['id']}" if len(rows)>limit else None,
                'note':'保留有界动作记录，不包含被遗忘的正文。'}

    @app.get('/api/memory/health')
    def health(current=Depends(user)):
        with db.connect() as conn:
            entries=memory_catalog(conn,current['id'])
            counts={}
            for item in entries:counts[item['state']]=counts.get(item['state'],0)+1
            attention={'conflict','needs_review','cooling','source_changed','expired'}
            evidence={row['memory_id'] for row in conn.execute('''SELECT e.memory_id FROM memory_evidence e JOIN personal_memories m ON m.id=e.memory_id WHERE m.user_id=?
                UNION SELECT l.child_id FROM memory_links l JOIN personal_memories m ON m.id=l.child_id WHERE m.user_id=? AND l.relation='derived_from' ''',(current['id'],current['id']))}
            jobs={row['state']:row['n'] for row in conn.execute('SELECT state,count(*) n FROM memory_jobs WHERE user_id=? GROUP BY state',(current['id'],))}
            return {'checked_at':int(time.time()),'total':len(entries),'states':counts,
                'attention':sum(counts.get(key,0) for key in attention),
                'automatic_without_evidence':sum(item['origin'] not in ('manual','import') and item['id'] not in evidence for item in entries),
                'with_evidence':len(evidence),'human_locked':sum(bool(item['locked']) for item in entries),
                'session_count':conn.execute('SELECT count(*) FROM memory_session_items WHERE user_id=? AND expires_at>?',(current['id'],int(time.time()))).fetchone()[0],
                'jobs':jobs,'note':'这些是当前状态与来源检查计数，不是模型准确率或本轮采用数量。'}

    @app.get('/api/memory/items/{mid}/impact')
    def impact(mid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,'personal_memories',mid,current['id'])
            descendants=[dict(row) for row in conn.execute('''WITH RECURSIVE children(id) AS (
                SELECT child_id FROM memory_links WHERE parent_id=? AND relation='derived_from'
                UNION SELECT l.child_id FROM memory_links l JOIN children c ON l.parent_id=c.id WHERE l.relation='derived_from')
                SELECT m.id,m.kind,m.version FROM personal_memories m JOIN children c ON c.id=m.id WHERE m.user_id=? ORDER BY m.id''',(mid,current['id']))]
            item=next(item for item in memory_catalog(conn,current['id']) if item['id']==mid)
            answers=conn.execute('SELECT count(*) FROM memory_usage WHERE memory_id=?',(mid,)).fetchone()[0]
            check='changed' if item['state']=='source_changed' else 'current' if item['state']=='active' else 'not_checked'
            return {'id':mid,'version':item['version'],'state':item['state'],'tier':item['tier'],
                'source_check':check,'derived_count':len(descendants),
                'derived_preview':descendants[:20],'answer_count':answers,
                'note':'正文、范围或有效期变化会影响派生内容；置顶、标签和锁定不会改写其事实依据。主动遗忘会撤销相关旧回答的后续记忆用途。'}

    @app.post('/api/memory/bulk')
    def batch(payload:Batch,current=Depends(user),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key',max_length=80)):
        with db.connect(write=True) as conn:
            receipt=mutation_lookup(conn,current['id'],idempotency_key,'batch',payload.model_dump())
            if receipt:return {**receipt,'replayed':True}
            if len({entry.id for entry in payload.items})!=len(payload.items):raise HTTPException(422,'选择中存在重复条目')
            entries=[]
            for entry in payload.items:
                row=own(conn,'personal_memories',entry.id,current['id'])
                if row['version']!=entry.version:raise HTTPException(409,'选择中有记忆已变化，本次没有修改任何条目，请刷新后重试')
                details=conn.execute('SELECT review_status FROM memory_details WHERE memory_id=?',(entry.id,)).fetchone()
                if payload.action=='activate' and details['review_status']!='accepted':raise HTTPException(409,'待核对内容须先逐条核对来源后采用')
                entries.append(dict(row))
            before=conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(current['id'],)).fetchone()[0]
            results=[]
            for row in entries:
                if payload.action=='forget':
                    if conn.execute('SELECT 1 FROM personal_memories WHERE id=?',(row['id'],)).fetchone():forget_memory(conn,current['id'],row)
                    results.append({'id':row['id'],'deleted':True})
                    continue
                if payload.action in ('lock','unlock'):
                    conn.execute('UPDATE memory_details SET locked=? WHERE memory_id=?',(int(payload.action=='lock'),row['id']))
                else:
                    conn.execute('UPDATE memory_semantics SET status=?,version=version+1 WHERE memory_id=?',('active' if payload.action=='activate' else 'archived',row['id']))
                    if payload.action=='activate':
                        life=conn.execute('SELECT tier FROM memory_semantics WHERE memory_id=?',(row['id'],)).fetchone()
                        set_semantics(conn,row['id'],admission='manual',tier=life['tier'])
                        conn.execute('UPDATE personal_memories SET active=1 WHERE id=?',(row['id'],))
                conn.execute('UPDATE personal_memories SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),row['id']))
                record_revision(conn,row['id'],'user-'+payload.action)
                event(conn,current['id'],row['id'],'configured','本人批量'+{'archive':'归档','activate':'重新确认使用','lock':'锁定','unlock':'解锁'}[payload.action])
                results.append({'id':row['id'],'version':row['version']+1})
            if payload.action=='activate':
                current_items={item['id']:item for item in memory_catalog(conn,current['id'])}
                if any(current_items[row['id']]['state']!='active' for row in entries):
                    raise HTTPException(409,'有条目仍存在过期、冲突或来源变化，本次没有启用任何条目，请先修订依据')
            after=conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(current['id'],)).fetchone()[0]
            result={'action':payload.action,'count':len(results),'deleted_count':before-after,'items':results}
            mutation_record(conn,current['id'],idempotency_key,'batch',payload.model_dump(),result)
            return result

    @app.put('/api/memory/session-items/{sid}')
    def edit_session(sid:str,payload:SessionEdit,current=Depends(user)):
        from .memory_learning import SECRET,REJECT_INSTRUCTION
        content=payload.content.strip()
        if not content or SECRET.search(content) or REJECT_INSTRUCTION.search(content):raise HTTPException(422,'内容为空或含不适合保存的凭证、权限指令')
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT * FROM memory_session_items WHERE id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'会话片段不存在或无权访问')
            if row['expires_at']<=int(time.time()):raise HTTPException(409,'片段已过期，请从当前对话重新确认')
            old=conn.execute('SELECT version FROM memory_session_edits WHERE session_id=?',(sid,)).fetchone()
            if payload.version!=(old['version'] if old else 0):raise HTTPException(409,'片段已在其他窗口编辑，请重新打开后核对')
            conn.execute('INSERT INTO memory_session_edits VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET content=excluded.content,version=excluded.version,updated_at=excluded.updated_at',
                (sid,content,payload.version+1,int(time.time())))
            conn.execute('UPDATE memory_session_items SET lifetime=? WHERE id=?',(payload.lifetime,sid))
            from .memory_learning import update_working
            update_working(conn,row['conversation_id'],content,'会话条件已由本人修订')
            event(conn,current['id'],None,'session_edited','本人修订会话条件；原话作为来源保留')
            return overlay_sessions(conn,[dict(row)])[0]|{'lifetime':payload.lifetime}

    @app.post('/api/memory/reflections/{jid}/retry')
    def retry_reflection(jid:str,payload:ReflectionRetry,current=Depends(user)):
        from .memory_reflection import payload_for,fingerprint
        if not payload.allow_external_processing:raise HTTPException(422,'重新请求模型可能计费，需要明确确认')
        with db.connect(write=True) as conn:
            job=conn.execute('SELECT * FROM memory_reflection_jobs WHERE id=? AND user_id=?',(jid,current['id'])).fetchone()
            if not job:raise HTTPException(404,'复盘记录不存在或无权访问')
            if job['state']=='queued':return {'queued':True,'already_queued':True}
            if job['state']!='failed' or job['finished_at']!=payload.finished_at:raise HTTPException(409,'作业状态已变化，请重新查看')
            fresh=payload_for(conn,current['id'],job['conversation_id'])
            if fresh is None or fingerprint(fresh)!=job['fingerprint']:
                raise HTTPException(409,'来源、授权或设置已变化，请执行整理生成当前条件下的新作业')
            if conn.execute("SELECT 1 FROM memory_reflection_jobs WHERE user_id=? AND state IN ('queued','running')",(current['id'],)).fetchone():
                raise HTTPException(409,'已有复盘正在等待或处理，请先等待其结果')
            conn.execute("UPDATE memory_reflection_jobs SET state='queued',snapshot=?,created_at=?,started_at=NULL,finished_at=NULL,error_code='',usage='{}' WHERE id=?",(dumps(fresh),int(time.time()),jid))
            conn.execute("UPDATE memory_reflection_leases SET token='',not_before=0,external_started_at=NULL WHERE job_id=?",(jid,))
            event(conn,current['id'],None,'reflection_retry','本人明确确认重新请求语义复盘；原请求可能已计费')
            return {'queued':True,'already_queued':False}
