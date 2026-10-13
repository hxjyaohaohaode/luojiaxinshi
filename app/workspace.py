"""Private conversations, user-selected material promotion and source directory."""
from datetime import datetime,timezone,timedelta
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


class NewConversation(Strict):
    title: str = Field(default='新的校园对话',min_length=1,max_length=100)


class RenameConversation(NewConversation,Version):
    pass


class SendMessage(Version):
    content: str = Field(default='',max_length=6000)
    request_id: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    retry_message_id: str | None = Field(default=None,max_length=40)
    allow_external_processing: bool = False


class Promote(Version):
    title: str = Field(min_length=1,max_length=160)
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
        if not include_content:
            source['size']=len(source.pop('content') or b'')
        items.append(source)
    return items


def conversation_detail(conn,cid,uid,settings):
    row=conn.execute('SELECT * FROM conversations WHERE id=? AND user_id=?',(cid,uid)).fetchone()
    if row is None:
        raise HTTPException(404,'对话不存在或无权访问')
    result=dict(row)
    expired=bool(row['processing_token'] and (row['processing_at'] or 0)<time.time()-settings.ai_timeout-30)
    result['processing']=bool(row['processing_token']) and not expired
    result.pop('processing_token',None)
    result['sources']=sources_for(conn,cid)
    result['messages']=[]
    for message in conn.execute('SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY created_at,rowid',(cid,)):
        item=dict(message);item['citations']=json.loads(item['citations'])
        if expired and item['status']=='processing':
            item.update(status='failed',error='上次回复已中断，消息已保留，可以重试。')
        result['messages'].append(item)
    result['character_count']=total_chars(result['sources'])
    return result


def install_workspace(app,db,settings,user,heavy_lock):
    def own(conn,cid,uid,version=None,idle=False):
        row=conn.execute('SELECT * FROM conversations WHERE id=? AND user_id=?',(cid,uid)).fetchone()
        if row is None:
            raise HTTPException(404,'对话不存在或无权访问')
        if version is not None and row['version']!=version:
            raise HTTPException(409,'对话已在其他页面变化，请刷新核对；未覆盖你的新内容')
        if idle and row['processing_token']:
            if (row['processing_at'] or 0)>time.time()-settings.ai_timeout-30:
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
            if conn.execute('SELECT COUNT(*) FROM conversations WHERE user_id=?',(current['id'],)).fetchone()[0]>=100:
                raise HTTPException(413,'已达到 100 个会话，请导出并删除不再需要的对话')
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
            conn.execute('DELETE FROM edit_caches WHERE user_id=? AND cache_key=?',(current['id'],'chat:'+cid))
            conn.execute('DELETE FROM conversations WHERE id=?',(cid,))
        return {'ok':True}

    @app.post('/api/conversations/{cid}/sources')
    async def upload(cid:str,request:Request,current=Depends(user)):
        rate_limit(db,'upload:'+current['id'],40,3600)
        with db.connect() as conn:
            own(conn,cid,current['id'])
        form=await request.form(max_files=5,max_fields=5,max_part_size=120000)
        try:
            if set(form.keys())-{'version','body','label','files'}:
                raise HTTPException(422,'含不支持的上传字段')
            try:
                version=int(form.get('version','0'))
            except (TypeError,ValueError):
                raise HTTPException(422,'请刷新后重新上传') from None
            body=str(form.get('body','')).strip();label=str(form.get('label','')).strip()
            if len(body)>MAX_CHARS or len(label)>160:
                raise HTTPException(422,'正文最多 10000 字，名称最多 160 字；未截断内容')
            materials=[text_source(body,label or '粘贴的材料')] if body else []
            for file in form.getlist('files'):
                if not hasattr(file,'read'):
                    raise HTTPException(422,'附件字段不正确')
                data=await file.read(MAX_FILE+1)
                try:
                    materials.append(await run_in_threadpool(file_source,file.filename or '',data))
                except ValueError as error:
                    raise HTTPException(422,str(error)) from None
            if not materials:
                raise HTTPException(422,'请粘贴文字或选择材料')
        finally:
            await form.close()
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],version,idle=True)
            existing=sources_for(conn,cid,True)
            hashes={s['sha256'] for s in existing};unique=[]
            for source in materials:
                if source['sha256'] not in hashes:
                    unique.append(source);hashes.add(source['sha256'])
            combined=existing+unique
            if len(combined)>12 or total_chars(combined)>MAX_CHARS or sum(s['kind'] in chat_ai.IMAGE_MIME for s in combined)>4:
                raise HTTPException(413,'每个对话最多 12 份材料、4 张图片和 10000 字提取文本，请按事项拆分对话')
            stored=conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?',(current['id'],)).fetchone()[0]
            stored+=conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?',(current['id'],)).fetchone()[0]
            if stored+sum(len(s['content'] or b'') for s in unique)>200*1024*1024:
                raise HTTPException(413,'材料存储超过每账号 200 MB 上限，请先导出并清理旧材料')
            for s in unique:
                conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(s['id'],cid,s['name'],s['kind'],s['content'],s['sha256'],s['status'],dumps(s['sections']),s['warning'],int(time.time())))
            if unique:
                changed(conn,cid)
            result=conversation_detail(conn,cid,current['id'],settings)
            result['added_count']=len(unique);result['duplicate_count']=len(materials)-len(unique)
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
    def download(cid:str,sid:str,preview:bool=False,current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            source=conn.execute('SELECT * FROM conversation_sources WHERE conversation_id=? AND id=?',(cid,sid)).fetchone()
            if not source:
                raise HTTPException(404,'材料不存在')
        content=source['content'] or '\n'.join(s['text'] for s in json.loads(source['sections'])).encode()
        mime=chat_ai.IMAGE_MIME.get(source['kind'],'application/octet-stream')
        disposition='inline' if preview and source['kind'] in chat_ai.IMAGE_MIME and source['status']!='failed' else 'attachment'
        return Response(content,media_type=mime,headers={'Content-Disposition':disposition+"; filename*=UTF-8''"+quote(source['name'])})

    @app.post('/api/conversations/{cid}/messages')
    async def send(cid:str,payload:SendMessage,current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            if conn.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? AND request_id=?',(cid,payload.request_id)).fetchone():
                return conversation_detail(conn,cid,current['id'],settings)
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
                if payload.retry_message_id:
                    previous=conn.execute("SELECT * FROM conversation_messages WHERE id=? AND conversation_id=? AND role='assistant'",(payload.retry_message_id,cid)).fetchone()
                    if not previous or previous['status'] not in {'failed','cancelled'}:
                        raise HTTPException(409,'只能重试未完成的回复')
                    latest=conn.execute("SELECT id FROM conversation_messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",(cid,)).fetchone()
                    if latest['id']!=previous['id']:
                        raise HTTPException(409,'后面已有新对话，请重新提问，避免旧问题覆盖上下文')
                    parent=previous['parent_id']
                else:
                    if not payload.content:
                        raise HTTPException(422,'请写下你希望助手帮忙的内容')
                    parent=ident()
                    conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",(parent,cid,payload.content,now))
                    if conversation['title']=='新的校园对话':
                        conn.execute('UPDATE conversations SET title=? WHERE id=?',(payload.content[:40],cid))
                messages=[dict(m) for m in conn.execute("SELECT * FROM conversation_messages WHERE conversation_id=? AND status='complete' ORDER BY created_at,rowid",(cid,))]
                if len(messages)>80 or sum(len(m['content']) for m in messages)>80000:
                    raise HTTPException(413,'本会话内容已较长，请新建对话继续；历史和材料仍保留在这里')
                sources=sources_for(conn,cid,True)
                # Exclude assistant text tied to materials the user removed from current context.
                current_ids={s['id'] for s in sources}
                messages=[m for m in messages if m['role']=='user' or all(e['source_id'] in current_ids for e in json.loads(m['citations']))]
                conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,request_id,parent_id,model,created_at) VALUES(?,?,'assistant','processing',?,?,?,?)",(mid,cid,payload.request_id,parent,settings.ai_model,now))
                conn.execute('UPDATE conversations SET processing_token=?,processing_at=? WHERE id=?',(token,now,cid));changed(conn,cid)
            try:
                result,usage=await run_in_threadpool(chat_ai.reply,settings,sources,messages,json.loads(current['profile']))
                status='complete';error=''
            except AIError as exc:
                result={'answer':'','citations':[],'image_sources':[]};usage={};status='failed';error=str(exc)
            with db.connect(write=True) as conn:
                live=conn.execute('SELECT processing_token FROM conversations WHERE id=? AND user_id=?',(cid,current['id'])).fetchone()
                if not live:
                    raise HTTPException(404,'对话已删除，回复未写入')
                if live['processing_token']!=token:
                    return conversation_detail(conn,cid,current['id'],settings)
                citations=result['citations']+[{'source_id':sid,'locator':'图片','quote':'视觉理解结果，请对照图片核实'} for sid in result['image_sources']]
                conn.execute('UPDATE conversation_messages SET content=?,status=?,error=?,citations=?,input_tokens=?,output_tokens=? WHERE id=?',
                             (result['answer'],status,error,dumps(citations),usage.get('input_tokens'),usage.get('output_tokens'),mid))
                conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
                return conversation_detail(conn,cid,current['id'],settings)
        finally:
            heavy_lock.release()

    @app.post('/api/conversations/{cid}/cancel')
    def cancel(cid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version)
            conn.execute("UPDATE conversation_messages SET status='cancelled',error='已停止采纳本次回复；模型服务可能仍在处理并计费。' WHERE conversation_id=? AND status='processing'",(cid,))
            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
            return conversation_detail(conn,cid,current['id'],settings)

    @app.post('/api/conversations/{cid}/promote')
    def promote(cid:str,payload:Promote,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version,idle=True)
            wanted=set(payload.source_ids)
            selected=[s for s in sources_for(conn,cid,True) if s['id'] in wanted]
            if len(selected)!=len(wanted):
                raise HTTPException(404,'所选材料不存在或不属于此对话')
            fingerprint=hashlib.sha256(dumps(sorted(s['sha256'] for s in selected)).encode()).hexdigest()
            prior=conn.execute('SELECT notice_id FROM conversation_promotions WHERE conversation_id=? AND fingerprint=?',(cid,fingerprint)).fetchone()
            if prior:
                return {'notice_id':prior['notice_id'],'already_created':True}
            count=conn.execute('SELECT COUNT(*) FROM notices WHERE user_id=?',(current['id'],)).fetchone()[0]
            if count>=200:
                raise HTTPException(413,'已达到 200 则通知上限，请先导出并清理旧通知')
            size=conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?',(current['id'],)).fetchone()[0]
            size+=conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?',(current['id'],)).fetchone()[0]
            if size+sum(len(s['content'] or b'') for s in selected)>200*1024*1024:
                raise HTTPException(413,'复制原件将超过每账号 200 MB 存储上限')
            nid=ident();now=int(time.time())
            conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?,?)',
                         (nid,current['id'],payload.title,payload.source_label,payload.source_url,fingerprint,now,now))
            for s in selected:
                conn.execute('INSERT INTO sources(id,notice_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (ident(),nid,s['name'],s['kind'],s['content'],s['sha256'],s['status'],dumps(s['sections']),s['warning'],now))
            conn.execute('INSERT INTO conversation_promotions VALUES(?,?,?)',(cid,fingerprint,nid))
            audit(conn,current['id'],nid,'create_notice',after={'from_conversation':cid,'sources':[s['name'] for s in selected]})
        return {'notice_id':nid,'already_created':False}

    @app.get('/api/source-catalog')
    def catalog(current=Depends(user)):
        with db.connect() as conn:
            return [{**dict(r),'data':json.loads(r['data'])} for r in conn.execute('SELECT * FROM source_catalog WHERE user_id=? ORDER BY updated_at DESC,rowid DESC',(current['id'],))]

    @app.post('/api/source-catalog')
    def add_source(payload:CatalogItem,current=Depends(user)):
        with db.connect(write=True) as conn:
            if conn.execute('SELECT COUNT(*) FROM source_catalog WHERE user_id=?',(current['id'],)).fetchone()[0]>=100:
                raise HTTPException(413,'最多登记 100 个来源，请先清理不再使用的条目')
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
