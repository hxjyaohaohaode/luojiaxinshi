"""Private conversations, user-selected material promotion and source directory."""
from .usage_limits import check_count, check_storage, limits_for
from datetime import datetime,timezone,timedelta
import asyncio
import hashlib
import json
import secrets
import time
from typing import Literal
from urllib.parse import quote

from fastapi import Depends,HTTPException,Request,Response
from pydantic import Field,field_validator
from starlette.concurrency import run_in_threadpool

from . import chat_ai
from .ai import AIError
from .db import ident,dumps,audit
from .documents import file_source,text_source,total_chars,MAX_FILE,MAX_CHARS
from .models import Strict,Version,safe_url
from .security import rate_limit
from .genui_api import load_message,install_genui
from .chat_media import chat_file_source, VIDEO_MIME, video_response
from .material_files import expand_files,MAX_UPLOAD,safe_path
from .conversation_tools import logical_messages,select_reply,model_sources,install_tools
from .genui_state import Interaction, submission_context, checkpoint
from .visual_evidence import display_citations


class NewConversation(Strict):
    title: str = Field(default='新的校园对话',min_length=1,max_length=100)


class RenameConversation(NewConversation,Version):
    pass


class SendMessage(Version):
    content: str = Field(default='',max_length=6000)
    request_id: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    retry_message_id: str | None = Field(default=None,max_length=40)
    regenerate_message_id: str | None = Field(default=None,max_length=40)
    steer_message_id: str | None = Field(default=None,max_length=40)
    allow_external_processing: bool = True
    ui_context: Interaction | None = None
    source_ids: list[str] = Field(default_factory=list,max_length=100)


class Promote(Version):
    title: str = Field(default='',max_length=160)
    source_ids: list[str] = Field(min_length=1,max_length=12)
    source_label: str = Field(default='本人提交',max_length=100)
    source_url: str = Field(default='',max_length=2000)

    @field_validator('source_url')
    @classmethod
    def url(cls,value):
        return safe_url(value)


class CatalogItem(Strict):
    name: str = Field(min_length=1,max_length=100)
    platform: Literal['website','wechat_public','qq_group','wechat_group','campus','other']
    institution: str = Field(default='',max_length=100)
    purpose: str = Field(default='',max_length=300)
    semester: str = Field(default='',max_length=40)
    url: str = Field(default='',max_length=2000)
    followed: bool = False

    @field_validator('url')
    @classmethod
    def url_check(cls,value):
        return safe_url(value)


class CatalogUpdate(CatalogItem,Version):
    pass


def sources_for(conn,cid,include_content=False):
    items=[]
    for row in conn.execute('SELECT * FROM conversation_sources WHERE conversation_id=? ORDER BY created_at,rowid',(cid,)):
        source=dict(row);source['sections']=json.loads(source['sections'])
        library=conn.execute('SELECT path,full_chars FROM material_library WHERE source_id=?',(source['id'],)).fetchone()
        source.update(path=library['path'] if library else source['name'],full_chars=library['full_chars'] if library else total_chars([source]))
        if not include_content:
            source['size']=len(source.pop('content') or b'')
        items.append(source)
    return items


def conversation_detail(conn,cid,uid,settings):
    from .grounding import load_report
    row=conn.execute('SELECT * FROM conversations WHERE id=? AND user_id=?',(cid,uid)).fetchone()
    if row is None:
        raise HTTPException(404,'对话不存在或无权访问')
    result=dict(row)
    consent=conn.execute('SELECT granted_at FROM conversation_ai_consents WHERE conversation_id=?',(cid,)).fetchone()
    result['model_consent']=bool(consent)
    result['model_consent_at']=consent['granted_at'] if consent else None
    expired=bool(row['processing_token'] and (row['processing_at'] or 0)<time.time()-settings.ai_workflow_timeout-30)
    result['processing']=bool(row['processing_token']) and not expired
    result.pop('processing_token',None)
    result['sources']=sources_for(conn,cid)
    result['messages']=[]
    for message in logical_messages(conn,cid):
        item=dict(message);versions=item.pop('_versions',[]);item.pop('position',None);item['citations']=json.loads(item['citations'])
        item['attachments']=[dict(s) for s in conn.execute('''SELECT s.id,s.name,s.kind,length(s.content) AS size
            FROM message_attachments a JOIN conversation_sources s ON s.id=a.source_id
            WHERE a.message_id=? AND s.conversation_id=? ORDER BY a.position''',(item['id'],cid))]
        if expired and item['status']=='processing':
            item.update(status='failed',error='上次回复已中断，消息已保留，可以重试。')
        item=load_message(conn,item,settings)
        item=load_report(conn,item)
        from .agent_runtime.chat import message_state
        item['agent'] = message_state(conn, uid, cid, item['id'])
        interaction=conn.execute('SELECT context FROM genui_interactions WHERE message_id=?',(item['id'],)).fetchone()
        if interaction:item['interaction']=json.loads(interaction['context'])
        reaction=conn.execute('SELECT value FROM reply_reactions WHERE message_id=?',(item['id'],)).fetchone();item['reaction']=reaction[0] if reaction else 0
        if versions:
            item['versions']=[]
            for version in versions:
                v={k:value for k,value in version.items() if k!='position'};v['citations']=json.loads(v['citations'])
                v['agent'] = item['agent'] if v['id']==item['id'] else message_state(conn,uid,cid,v['id'])
                item['versions'].append(load_report(conn,load_message(conn,v,settings)))
            item['version_index']=next(i for i,v in enumerate(versions) if v['id']==item['id'])
        result['messages'].append(item)
    result['character_count']=total_chars(result['sources'])
    from .memory import context_for
    result['context']=context_for(conn,cid)
    return result


def install_workspace(app,db,settings,user,heavy_lock):
    def own(conn,cid,uid,version=None,idle=False):
        row=conn.execute('SELECT * FROM conversations WHERE id=? AND user_id=?',(cid,uid)).fetchone()
        if row is None:
            raise HTTPException(404,'对话不存在或无权访问')
        if version is not None and row['version']!=version:
            raise HTTPException(409,'对话已在其他页面变化，请刷新核对；未覆盖你的新内容')
        if idle and row['processing_token']:
            if (row['processing_at'] or 0)>time.time()-settings.ai_workflow_timeout-30:
                raise HTTPException(409,'正在处理上一条消息，请稍候或先停止回复')
            conn.execute("UPDATE conversation_messages SET status='failed',error='上次处理已中断，可重试' WHERE conversation_id=? AND status='processing'",(cid,))
            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,))
        return dict(row)

    def changed(conn,cid):
        conn.execute('UPDATE conversations SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),cid))

    @app.get('/api/conversations')
    def conversations(current=Depends(user)):
        with db.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT c.id,c.title,c.version,c.updated_at,(SELECT COUNT(*) FROM conversation_sources s WHERE s.conversation_id=c.id) AS source_count FROM conversations c WHERE user_id=? ORDER BY updated_at DESC,rowid DESC',(current['id'],))]

    @app.post('/api/conversations')
    def create(payload:NewConversation,current=Depends(user)):
        rate_limit(db,'conversation:'+current['id'],50,3600)
        cid=ident();now=int(time.time())
        with db.connect(write=True) as conn:
            check_count(conn,current['id'],'conversations','conversations','会话')
            conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,current['id'],payload.title,now,now))
            return conversation_detail(conn,cid,current['id'],settings)

    @app.get('/api/conversations/{cid}')
    def read(cid:str,current=Depends(user)):
        with db.connect() as conn:
            return conversation_detail(conn,cid,current['id'],settings)

    @app.put('/api/conversations/{cid}')
    def rename(cid:str,payload:RenameConversation,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version,idle=True)
            conn.execute('UPDATE conversations SET title=? WHERE id=?',(payload.title,cid));changed(conn,cid)
            return conversation_detail(conn,cid,current['id'],settings)

    @app.delete('/api/conversations/{cid}')
    def delete(cid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version)
            conn.execute('DELETE FROM edit_caches WHERE user_id=? AND (cache_key=? OR cache_key LIKE ?)',(current['id'],'chat:'+cid,'branch:'+cid+':%'))
            conn.execute('DELETE FROM conversations WHERE id=?',(cid,))
        return {'ok':True}

    @app.post('/api/conversations/{cid}/sources')
    async def upload(cid:str,request:Request,current=Depends(user)):
        rate_limit(db,'upload:'+current['id'],180,3600)
        with db.connect() as conn:
            own(conn,cid,current['id'])
        form=await request.form(max_files=5,max_fields=8,max_part_size=120000)
        try:
            if set(form.keys())-{'version','body','label','files','paths','append_only'}:
                raise HTTPException(422,'含不支持的上传字段')
            try:
                version=int(form.get('version','0'))
            except (TypeError,ValueError):
                raise HTTPException(422,'请刷新后重新上传') from None
            body=str(form.get('body','')).strip();label=str(form.get('label','')).strip()
            append_only=form.get('append_only')=='true'
            if len(body)>MAX_CHARS or len(label)>160:
                raise HTTPException(422,'正文最多 10000 字，名称最多 160 字；未截断内容')
            materials=[text_source(body,label or '粘贴的材料')] if body else []
            try:paths=json.loads(str(form.get('paths','[]')))
            except ValueError:raise HTTPException(422,'文件夹路径无法读取，请重新选择') from None
            if not isinstance(paths,list) or (paths and len(paths)!=len(form.getlist('files'))):raise HTTPException(422,'文件路径与附件数量不一致')
            for index,file in enumerate(form.getlist('files')):
                if not hasattr(file,'read'):
                    raise HTTPException(422,'附件字段不正确')
                data=await file.read(MAX_UPLOAD+1)
                try:
                    materials.extend(await run_in_threadpool(expand_files,file.filename or '',data,paths[index] if paths else None))
                except ValueError as error:
                    raise HTTPException(422,str(error)) from None
            if not materials:
                raise HTTPException(422,'请粘贴文字或选择材料')
        finally:
            await form.close()
        with db.connect(write=True) as conn:
            # Parallel uploads only append. The transaction rechecks ownership,
            # idle state, deduplication and quotas against all committed batches.
            own(conn,cid,current['id'],None if append_only else version,idle=True)
            existing=sources_for(conn,cid,True)
            hashes={(s['sha256'],s['path']) for s in existing};unique=[]
            for source in materials:
                fingerprint=(source['sha256'],source.get('path',source['name']))
                if fingerprint not in hashes:
                    unique.append(source);hashes.add(fingerprint)
            combined=existing+unique
            if len(combined)>100 or sum(s.get('full_chars',sum(len(p['text']) for p in s.get('full_sections',s['sections']))) for s in combined)>5000000:
                raise HTTPException(413,'每个对话最多 100 份材料、500 万字全文。请按事项拆分对话')
            check_storage(conn,current['id'],sum(len(s['content'] or b'') for s in unique))
            for s in unique:
                conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(s['id'],cid,s['name'],s['kind'],s['content'],s['sha256'],s['status'],dumps(s['sections']),s['warning'],int(time.time())))
                full=s.get('full_sections',s['sections'])
                conn.execute('INSERT INTO material_library VALUES(?,?,?,?)',(s['id'],s.get('path',s['name']),dumps(full),sum(len(p['text']) for p in full)))
            if unique:
                changed(conn,cid)
            result=conversation_detail(conn,cid,current['id'],settings)
            result['added_count']=len(unique);result['duplicate_count']=len(materials)-len(unique)
            source_ids={(s['sha256'],s.get('path',s['name'])):s['id'] for s in combined}
            result['uploaded_source_ids']=list(dict.fromkeys(source_ids[(s['sha256'],s.get('path',s['name']))] for s in materials))
            return result

    @app.delete('/api/conversations/{cid}/sources/{sid}')
    def remove(cid:str,sid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version,idle=True)
            if not conn.execute('DELETE FROM conversation_sources WHERE id=? AND conversation_id=?',(sid,cid)).rowcount:
                raise HTTPException(404,'材料不存在')
            changed(conn,cid)
            return conversation_detail(conn,cid,current['id'],settings)

    @app.get('/api/conversations/{cid}/sources/{sid}/download')
    def download(cid:str,sid:str,request:Request,preview:bool=False,frame:int=0,current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            source=conn.execute('SELECT * FROM conversation_sources WHERE conversation_id=? AND id=?',(cid,sid)).fetchone()
            if not source:
                raise HTTPException(404,'材料不存在')
        content=source['content'] or '\n'.join(s['text'] for s in json.loads(source['sections'])).encode()
        if preview and source['kind'] in {'tif','tiff'}:
            import io
            from PIL import Image
            try:
                Image.MAX_IMAGE_PIXELS=20000000
                with Image.open(io.BytesIO(content)) as picture:
                    if frame<0 or frame>999:raise ValueError('图片页码超限')
                    picture.seek(frame)
                    out=io.BytesIO();picture.convert('RGBA').save(out,format='PNG');return Response(out.getvalue(),media_type='image/png')
            except (ValueError,OSError,EOFError):raise HTTPException(422,'这页图片暂时无法预览，请下载原件查看') from None
        if source['kind'] in VIDEO_MIME:
            return video_response(content,source['kind'],source['name'],request.headers.get('range'),preview)
        mime=chat_ai.IMAGE_MIME.get(source['kind'],{'pdf':'application/pdf','gif':'image/gif','bmp':'image/bmp','tif':'image/tiff','tiff':'image/tiff','mp3':'audio/mpeg','wav':'audio/wav','m4a':'audio/mp4','ogg':'audio/ogg','flac':'audio/flac'}.get(source['kind'],'application/octet-stream'))
        native_pdf=source['kind']=='pdf' and content.startswith(b'%PDF-')
        disposition='inline' if preview and mime!='application/octet-stream' and (source['status']!='failed' or native_pdf) else 'attachment'
        return Response(content,media_type=mime,headers={'Content-Disposition':disposition+"; filename*=UTF-8''"+quote(source['name'])})

    def preflight_steer(cid,payload,current):
        # A replacement that cannot be submitted must not stop a valid live job.
        rate_limit(db,'chat-submit:'+current['id'],40,3600,check_only=True)
        if settings.ai_api_key:
            day=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            rate_limit(db,'ai:'+current['id']+':'+day,settings.ai_daily_limit,86400,check_only=True)
        with db.connect() as conn:
            history=[m for m in logical_messages(conn,cid) if m['status']=='complete']
            if len(history)+1>2000 or sum(len(m['content']) for m in history)+len(payload.content)>4000000:
                raise HTTPException(413,'本会话内容已较长，请新建对话继续；原回复未中断，你的补充草稿仍保留。')

    def prepare_send(cid,payload,current):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            if conn.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? AND request_id=?',(cid,payload.request_id)).fetchone():
                return None,conversation_detail(conn,cid,current['id'],settings)
        if settings.ai_api_key and not payload.allow_external_processing:
            raise HTTPException(422,'请确认本会话材料可发送到所配置的模型服务')
        if not heavy_lock.acquire(blocking=False):
            raise HTTPException(429,'助手正在处理其他请求，请稍后重试')
        token=secrets.token_urlsafe(24);mid=ident();now=int(time.time())
        try:
            rate_limit(db,'chat-submit:'+current['id'],40,3600)
            if settings.ai_api_key:
                day=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                rate_limit(db,'ai:'+current['id']+':'+day,settings.ai_daily_limit,86400)
            with db.connect(write=True) as conn:
                conversation=own(conn,cid,current['id'],payload.version,idle=True)
                if payload.retry_message_id and payload.regenerate_message_id:raise HTTPException(422,'重试与重生成不能同时提交')
                previous_id=payload.regenerate_message_id or payload.retry_message_id
                if previous_id:
                    previous=conn.execute("SELECT * FROM conversation_messages WHERE id=? AND conversation_id=? AND role='assistant'",(previous_id,cid)).fetchone()
                    allowed={'complete'} if payload.regenerate_message_id else {'failed','cancelled'}
                    if not previous or previous['status'] not in allowed:raise HTTPException(409,'请对完整回答使用重生成，对未完成回答使用重试')
                    latest=conn.execute("SELECT id FROM conversation_messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",(cid,)).fetchone()
                    if payload.retry_message_id and latest['id']!=previous['id']:
                        raise HTTPException(409,'后面已有新对话，请重新提问，避免旧问题覆盖上下文')
                    parent=previous['parent_id']
                else:
                    if not payload.content:
                        raise HTTPException(422,'请写下你希望助手帮忙的内容')
                    parent=ident()
                    interaction=None
                    if payload.ui_context:
                        try:interaction=submission_context(conn,cid,payload.ui_context)
                        except (ValueError,TypeError,KeyError):raise HTTPException(422,'当前界面选择未通过检查，消息尚未发送；请核对选择或重新打开这条回复') from None
                    conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",(parent,cid,payload.content,now))
                    for position,sid in enumerate(dict.fromkeys(payload.source_ids)):
                        if not conn.execute('SELECT 1 FROM conversation_sources WHERE id=? AND conversation_id=?',(sid,cid)).fetchone():
                            raise HTTPException(422,'附件已移除或不属于本次对话，请重新选择')
                        conn.execute('INSERT INTO message_attachments VALUES(?,?,?)',(parent,sid,position))
                    if interaction:
                        interaction['checkpoint']=checkpoint(conn,payload.ui_context)
                        conn.execute('INSERT INTO genui_interactions VALUES(?,?,?)',(parent,payload.ui_context.message_id,dumps(interaction)))
                    if conversation['title']=='新的校园对话':
                        conn.execute('UPDATE conversations SET title=? WHERE id=?',(payload.content[:40],cid))
                messages=[]
                for m in logical_messages(conn,cid):
                    if m['status']=='complete':
                        item={k:v for k,v in m.items() if k!='_versions'}
                        interaction=conn.execute('SELECT context FROM genui_interactions WHERE message_id=?',(m['id'],)).fetchone()
                        if interaction:item['interaction']=json.loads(interaction['context'])
                        messages.append(item)
                    if m['id']==parent:break
                if len(messages)>2000 or sum(len(m['content']) for m in messages)>4000000:
                    raise HTTPException(413,'本会话内容已较长，请新建对话继续；历史和材料仍保留在这里')
                from .retrieval_scope import account_access
                from .memory_learning import ingest_message
                ingest_message(conn,current['id'],cid,parent,messages)
                access=account_access(messages)
                sources=model_sources(conn,sources_for(conn,cid,True),messages[-1]['content'] if messages else payload.content) if access['attachments'] else []
                # Exclude assistant text tied to materials the user removed from current context.
                current_ids={s['id'] for s in sources}
                accessible=set(current_ids)
                if access['library']:
                    accessible.update(r['id'] for r in conn.execute('SELECT s.id FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?',(current['id'],)))
                    accessible.update(r['id'] for r in conn.execute('SELECT s.id FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=? AND s.active=1',(current['id'],)))
                from .memory import eligible_versions,memory_access
                from .grounding import message_scope_start
                memory_versions=eligible_versions(conn,current['id'],cid,access['profile'] and memory_access(messages) and message_scope_start(messages) is None,access)
                reports={r['message_id']:json.loads(r['sources']) for r in conn.execute('''SELECT g.message_id,g.sources
                    FROM reply_grounding g JOIN conversation_messages m ON m.id=g.message_id WHERE m.conversation_id=?''',(cid,))}
                passage_ids={s['id'] for values in reports.values() for s in values if s.get('evidence_kind')=='memory' and s.get('id','').startswith('memory-unit-')}
                if passage_ids:
                    memory_versions.update(eligible_versions(conn,current['id'],cid,access['profile'] and memory_access(messages) and message_scope_start(messages) is None,access,passage_ids))
                contextual=[]
                for m in messages:
                    if m['role']=='user':contextual.append(m);continue
                    report_sources=reports.get(m['id'],[])
                    memory_sources=[s for s in report_sources if s.get('evidence_kind')=='memory']
                    # Preferences can affect prose without an inline citation. Revoke
                    # that whole old answer when any injected memory is no longer current.
                    from .memory_reliability import supplied_version_current
                    if any(not supplied_version_current(conn,current['id'],s,memory_versions) for s in memory_sources):continue
                    allowed={'web_page','web_summary','user_input'}
                    if access['profile']:allowed.add('profile')
                    if access['schedule']:allowed.update(('task','arrangement'))
                    web_ids={s['id'] for s in report_sources if s.get('evidence_kind') in allowed}
                    web_ids.update(s['id'] for s in memory_sources)
                    if all(e['source_id'] in accessible|web_ids for e in json.loads(m['citations'])):contextual.append(m)
                messages=contextual
                from .memory_lifecycle import filter_history
                messages=filter_history(conn,current['id'],messages)
                if settings.ai_api_key and payload.allow_external_processing:
                    conn.execute('INSERT OR IGNORE INTO conversation_ai_consents VALUES(?,?)',(cid,now))
                conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,request_id,parent_id,model,created_at) VALUES(?,?,'assistant','processing',?,?,?,?)",(mid,cid,payload.request_id,parent,settings.ai_model,now))
                conn.execute('UPDATE conversations SET processing_token=?,processing_at=? WHERE id=?',(token,now,cid));changed(conn,cid)
                app.state.execution.start(conn,mid,current['id'],'conversation',cid,token)
            return {'token':token,'mid':mid,'sources':sources,'messages':messages},None
        except BaseException:
            heavy_lock.release()
            raise

    @app.post('/api/conversations/{cid}/messages')
    async def send(cid:str,payload:SendMessage,current=Depends(user)):
        prepared,existing=prepare_send(cid,payload,current)
        if existing is not None:
            return existing
        token,mid,sources,messages=(prepared[k] for k in ('token','mid','sources','messages'))
        try:
            try:
                if settings.ai_grounding:
                    from .grounding import events
                    from .work_summary import stream as work_stream
                    from contextlib import aclosing
                    result=None;usage={}
                    pipeline=work_stream(settings,db,mid,events(settings,db,current['id'],cid,mid,sources,messages,json.loads(current['profile']),3))
                    async with asyncio.timeout(settings.ai_workflow_timeout), aclosing(pipeline):
                        async for event in pipeline:
                            if event['type']=='phase':
                                from .execution import stage
                                with db.connect(write=True) as conn:stage(conn,mid,event['phase'])
                            if event['type']=='complete':result=event['result'];usage=event.get('usage',{})
                    if result is None:raise AIError('核验未完成，未发布回答。')
                else:
                    from .memory_context import basic_profile
                    profile=basic_profile(db,current['id'],cid,mid,messages,json.loads(current['profile']),sources)
                    result,usage=await run_in_threadpool(chat_ai.reply,settings,sources,messages,profile)
                status='complete';error=''
            except (AIError,TimeoutError) as exc:
                result={'answer':'','citations':[],'image_sources':[]};usage={};status='failed';error=str(exc)
            with db.connect(write=True) as conn:
                live=conn.execute('SELECT processing_token FROM conversations WHERE id=? AND user_id=?',(cid,current['id'])).fetchone()
                if not live:
                    raise HTTPException(404,'对话已删除，回复未写入')
                if live['processing_token']!=token:
                    app.state.execution.finish(conn,mid,'discarded','superseded')
                    return conversation_detail(conn,cid,current['id'],settings)
                from .context_snapshot import publication_current,STALE_MESSAGE
                if status=='complete' and not publication_current(conn,mid,current['id'],cid):
                    status='failed';error=STALE_MESSAGE;result={'answer':'','citations':[],'image_sources':[]}
                citations=display_citations(result)
                conn.execute('UPDATE conversation_messages SET content=?,status=?,error=?,citations=?,input_tokens=?,output_tokens=? WHERE id=?',
                             (result['answer'],status,error,dumps(citations),usage.get('input_tokens'),usage.get('output_tokens'),mid))
                select_reply(conn,mid)
                conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
                app.state.execution.finish(conn,mid,'succeeded' if status=='complete' else 'failed','verified' if status=='complete' and settings.ai_grounding else 'complete' if status=='complete' else 'request_failed')
                from .memory_learning import completed_turn
                completed_turn(conn,current['id'],cid,mid,result,status)
                return conversation_detail(conn,cid,current['id'],settings)
        finally:
            try:
                with db.connect(write=True) as conn:
                    changed_rows=conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL,version=version+1 WHERE id=? AND processing_token=?',(cid,token)).rowcount
                    if changed_rows:
                        conn.execute("UPDATE conversation_messages SET status='failed',error='处理已中断，问题已保存，请重试。' WHERE id=? AND status='processing'",(mid,))
                        app.state.execution.finish(conn,mid,'failed','interrupted_request')
            finally:heavy_lock.release()

    cancel_genui=install_genui(app,db,settings,user,heavy_lock,prepare_send,own,changed,conversation_detail,SendMessage,preflight_steer)
    install_tools(app,db,settings,user,own,changed,conversation_detail,sources_for,heavy_lock)

    @app.delete('/api/conversations/{cid}/model-consent')
    def revoke_model_consent(cid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version)
            conn.execute('DELETE FROM conversation_ai_consents WHERE conversation_id=?',(cid,))
            conn.execute("UPDATE conversation_messages SET status='cancelled',error='已撤回本对话的模型处理授权，已停止采纳本次回复。' WHERE conversation_id=? AND status='processing'",(cid,))
            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
            result=conversation_detail(conn,cid,current['id'],settings)
        cancel_genui(cid)
        return result

    @app.post('/api/conversations/{cid}/cancel')
    def cancel(cid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version)
            conn.execute("UPDATE conversation_messages SET status='cancelled',error='已停止采纳本次回复；模型服务可能仍在处理并计费。' WHERE conversation_id=? AND status='processing'",(cid,))
            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
            result=conversation_detail(conn,cid,current['id'],settings)
        cancel_genui(cid)
        return result

    @app.post('/api/conversations/{cid}/promote')
    def promote(cid:str,payload:Promote,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version,idle=True)
            wanted=set(payload.source_ids)
            selected=[s for s in sources_for(conn,cid,True) if s['id'] in wanted]
            if any(s['kind'] in VIDEO_MIME for s in selected):
                raise HTTPException(422,'视频可留在对话中播放；转为通知时请选择可核对的原文、文档或截图')
            if len(selected)!=len(wanted):
                raise HTTPException(404,'所选材料不存在或不属于此对话')
            if sum(s['full_chars'] for s in selected)>10000:
                raise HTTPException(413,'所选通知正文合计超过 1 万字，不能仅用截取片段建立通知。请按独立通知拆分原文，再选择相关材料。')
            if any(s['kind'] in {'doc','xls','ppt','mp3','wav','m4a','ogg','flac'} for s in selected):
                raise HTTPException(422,'请先将音频转为可核对的文字，或将旧版 Office 转为新版文档，再转为通知。原件仍保留在对话中。')
            from .notice_ingest import fingerprint as intake_fingerprint, ingest_notice
            fingerprint=intake_fingerprint(selected)
            prior=conn.execute('SELECT notice_id FROM conversation_promotions WHERE conversation_id=? AND fingerprint=?',(cid,fingerprint)).fetchone()
            if prior:
                return {'notice_id':prior['notice_id'],'already_created':True}
            ingestion=ingest_notice(conn,current['id'],sources=selected,title=payload.title,source_label=payload.source_label,
                source_url=payload.source_url,external_key='conversation:'+cid+':'+fingerprint)
            nid=ingestion['notice_id']
            conn.execute('INSERT INTO conversation_promotions VALUES(?,?,?)',(cid,fingerprint,nid))
        return {'notice_id':nid,'already_created':not ingestion['created'],'source_retained':True}

    @app.get('/api/source-catalog')
    def catalog(current=Depends(user)):
        with db.connect() as conn:
            return [{**dict(r),'data':json.loads(r['data'])} for r in conn.execute('SELECT * FROM source_catalog WHERE user_id=? ORDER BY updated_at DESC,rowid DESC',(current['id'],))]

    @app.post('/api/source-catalog')
    def add_source(payload:CatalogItem,current=Depends(user)):
        with db.connect(write=True) as conn:
            check_count(conn,current['id'],'source_catalog','sources','来源')
            sid=ident();now=int(time.time())
            conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,?,?)',(sid,current['id'],payload.model_dump_json(),now,now))
        return {'id':sid}

    @app.put('/api/source-catalog/{sid}')
    def edit_source(sid:str,payload:CatalogUpdate,current=Depends(user)):
        with db.connect(write=True) as conn:
            record=conn.execute('SELECT * FROM source_catalog WHERE id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not record:
                raise HTTPException(404,'来源不存在')
            if record['version']!=payload.version:
                raise HTTPException(409,'来源已更新，请刷新后重新编辑')
            conn.execute('UPDATE source_catalog SET data=?,version=version+1,updated_at=? WHERE id=?',(dumps(payload.model_dump(exclude={'version'})),int(time.time()),sid))
        return {'ok':True}

    @app.delete('/api/source-catalog/{sid}')
    def delete_source(sid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            r=conn.execute('SELECT version FROM source_catalog WHERE id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not r:
                raise HTTPException(404,'来源不存在')
            if r['version']!=payload.version:
                raise HTTPException(409,'来源已变化，请刷新后重试')
            conn.execute('DELETE FROM source_catalog WHERE id=?',(sid,))
        return {'ok':True}
