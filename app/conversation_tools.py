"""Reply revisions, owner feedback, bounded retrieval and explicit share snapshots."""
import hashlib
import json
import re
import secrets
import time
import io
import zipfile
from .usage_limits import check_count, check_storage, limits_for
from fastapi import Depends,HTTPException,Request,Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from .db import ident,dumps
from .models import Strict,Version
from .security import rate_limit
from .material_files import library_file
from . import chat_ai
from .ai import AIError

def logical_messages(conn,cid):
    rows=[dict(r) for r in conn.execute('SELECT rowid AS position,* FROM conversation_messages WHERE conversation_id=? ORDER BY rowid',(cid,))]
    choices={r['parent_id']:r['message_id'] for r in conn.execute('SELECT s.* FROM reply_selection s JOIN conversation_messages m ON m.id=s.parent_id WHERE m.conversation_id=?',(cid,))}
    groups={}
    for r in rows:
        if r['role']=='assistant':groups.setdefault(r['parent_id'],[]).append(r)
    result=[];seen=set()
    for r in rows:
        if r['role']=='user':result.append(r);continue
        parent=r['parent_id']
        if parent in seen:continue
        seen.add(parent);versions=groups[parent]
        active=next((v for v in reversed(versions) if v['status']=='processing'),None)
        selected=next((v for v in versions if v['id']==choices.get(parent)),None)
        chosen=active or selected or versions[-1]
        result.append({**chosen,'_versions':versions})
    return result

def select_reply(conn,mid):
    row=conn.execute("SELECT parent_id,status FROM conversation_messages WHERE id=? AND role='assistant'",(mid,)).fetchone()
    if row and row['status']=='complete' and row['parent_id']:
        conn.execute('INSERT INTO reply_selection VALUES(?,?) ON CONFLICT(parent_id) DO UPDATE SET message_id=excluded.message_id',(row['parent_id'],mid))

def model_sources(conn,sources,question):
    """Bound text excerpts; retain every media item for explicit input budgeting."""
    terms=keywords(question);candidates=[]
    for source in sources:
        full=conn.execute('SELECT full_sections FROM material_library WHERE source_id=?',(source['id'],)).fetchone()
        sections=json.loads(full[0]) if full else source['sections']
        for i,section in enumerate(sections):
            score=sum(section['text'].lower().count(t) for t in terms)
            candidates.append((score,source['id'],i,section))
    candidates.sort(key=lambda x:-x[0]);selected={};remaining=10000
    for _,sid,index,section in candidates:
        if remaining<=0:break
        item={**section,'text':section['text'][:remaining]}
        selected.setdefault(sid,[]).append((index,item));remaining-=len(item['text'])
    result=[]
    for source in sources:
        item={**source,'sections':[s for _,s in sorted(selected.get(source['id'],[]))]}
        # Duration is transport metadata needed for the media budget, not a
        # relevance-ranked text excerpt. Long documents must not evict it.
        metadata=next((s for s in source['sections'] if s['locator']=='媒体信息'),None)
        if metadata and not any(s['locator']=='媒体信息' for s in item['sections']):
            item['sections'].append(metadata)
        # Keep the inventory even for unsupported/failed files; a missing text
        # excerpt must never disappear and masquerade as full coverage.
        result.append(item)
    return result

def keywords(text):
    tokens=re.findall(r'[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}',text.lower())
    result=[]
    for token in tokens[:30]:
        result.append(token)
        if re.fullmatch(r'[\u4e00-\u9fff]+',token) and len(token)>3:result.extend(token[i:i+2] for i in range(len(token)-1))
    return list(dict.fromkeys(result))[:80]

class Reaction(Strict):value:int=Field(ge=-1,le=1)
class Share(Strict):body:str=Field(default='',max_length=80000)

class BranchRequest(Version):
    request_id: str | None = Field(default=None,min_length=16,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')


def install_tools(app,db,settings,user,own,changed,detail,sources_for,heavy_lock):
    def message(conn,cid,mid,uid):
        own(conn,cid,uid)
        row=conn.execute("SELECT * FROM conversation_messages WHERE id=? AND conversation_id=? AND role='assistant'",(mid,cid)).fetchone()
        if not row:raise HTTPException(404,'回复不存在或无权访问')
        return dict(row)

    @app.post('/api/conversations/{cid}/messages/{mid}/reaction')
    def reaction(cid:str,mid:str,payload:Reaction,current=Depends(user)):
        with db.connect(write=True) as conn:
            message(conn,cid,mid,current['id'])
            conn.execute('INSERT INTO reply_reactions VALUES(?,?) ON CONFLICT(message_id) DO UPDATE SET value=excluded.value',(mid,payload.value))
        return {'value':payload.value}

    @app.post('/api/conversations/{cid}/messages/{mid}/select')
    def select(cid:str,mid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'],payload.version,idle=True);r=message(conn,cid,mid,current['id'])
            if r['status']!='complete':raise HTTPException(409,'仅能选用完整回复；未完成的版本仍可回看')
            select_reply(conn,mid);changed(conn,cid)
            return detail(conn,cid,current['id'],settings)

    @app.post('/api/conversations/{cid}/messages/{mid}/branch')
    def branch(cid:str,mid:str,payload:BranchRequest,current=Depends(user)):
        with db.connect(write=True) as conn:
            # A lost acknowledgement must not clone the conversation twice.
            new=hashlib.sha256((current['id']+'\0'+cid+'\0'+mid+'\0'+payload.request_id).encode()).hexdigest()[:32] if payload.request_id else ident()
            existing=conn.execute('SELECT user_id FROM conversations WHERE id=?',(new,)).fetchone()
            if existing:
                if existing['user_id']!=current['id']:raise HTTPException(409,'分支标识冲突，请重新打开后再试')
                return detail(conn,new,current['id'],settings)
            origin=own(conn,cid,current['id'],payload.version,idle=True);message(conn,cid,mid,current['id'])
            check_count(conn,current['id'],'conversations','conversations','会话')
            selected=detail(conn,cid,current['id'],settings)['messages'];index=next((i for i,m in enumerate(selected) if m['id']==mid),None)
            if index is None:raise HTTPException(409,'请先切换到要分支的回答版本')
            sources=sources_for(conn,cid,True)
            check_storage(conn,current['id'],sum(len(s['content'] or b'') for s in sources))
            now=int(time.time());mapping={s['id']:ident() for s in sources};mapping.update({m['id']:ident() for m in selected[:index+1]})
            def remap(value,key='',original=False):
                if isinstance(value,str):
                    # Quotes and original evidence remain byte-for-byte source
                    # text. Rebase references, never arbitrary UUID substrings.
                    if key=='quote' or original and key in {'text','locator'}:return value
                    literal=key in {'text','content','answer','label','title','name','description','summary','code','locator'}
                    if not literal:
                        if value in mapping:return mapping[value]
                        prefix,sep,suffix=value.partition('#')
                        if sep and prefix in mapping:return mapping[prefix]+sep+suffix
                    pattern=r'/conversations/'+re.escape(cid)+r'/(sources|messages)/([A-Za-z0-9_-]+)'
                    return re.sub(pattern,lambda match:'/conversations/'+new+'/'+match[1]+'/'+mapping[match[2]] if match[2] in mapping else match[0],value)
                if isinstance(value,list):return [remap(v,key,original) for v in value]
                if isinstance(value,dict):return {k:remap(v,k,original) for k,v in value.items()}
                return value
            def remap_raw(raw):
                output=[];inside=False
                for line in raw.splitlines(keepends=True):
                    if re.fullmatch(r'\s*```genui\s*',line):inside=True;output.append(line);continue
                    if inside and re.fullmatch(r'\s*```\s*',line):inside=False;output.append(line);continue
                    if inside and line.strip():
                        try:output.append(dumps(remap(json.loads(line)))+('\n' if line.endswith('\n') else ''));continue
                        except ValueError:pass  # An incomplete, stopped draft remains incomplete.
                    output.append(remap(line,'content'))
                return ''.join(output)
            conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(new,current['id'],(origin['title'][:90]+' · 分支'),now,now))
            saved_context=conn.execute('SELECT * FROM conversation_context WHERE conversation_id=?',(cid,)).fetchone()
            if saved_context:
                conn.execute('INSERT INTO conversation_context VALUES(?,?,?,?,1)',(new,saved_context['project_id'],saved_context['topics'],saved_context['memory_enabled']))
            from .memory_autonomy import mode_for
            conn.execute('INSERT INTO memory_selection_modes VALUES(?,?)',(new,mode_for(conn,cid)))
            for s in sources:
                conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(mapping[s['id']],new,s['name'],s['kind'],s['content'],s['sha256'],s['status'],dumps(s['sections']),s['warning'],now))
                full=conn.execute('SELECT * FROM material_library WHERE source_id=?',(s['id'],)).fetchone()
                if full:conn.execute('INSERT INTO material_library VALUES(?,?,?,?)',(mapping[s['id']],full['path'],full['full_sections'],full['full_chars']))
            for m in selected[:index+1]:
                conn.execute('INSERT INTO conversation_messages(id,conversation_id,role,content,status,error,parent_id,citations,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(mapping[m['id']],new,m['role'],remap(m['content'],'content'),m['status'],m['error'],mapping.get(m['parent_id']),dumps(remap(m['citations'])),m['created_at']))
                for attachment in m.get('attachments',[]):
                    conn.execute('INSERT INTO message_attachments VALUES(?,?,?)',(mapping[m['id']],mapping[attachment['id']],m['attachments'].index(attachment)))
                evidence=conn.execute('SELECT sources,report FROM reply_grounding WHERE message_id=?',(m['id'],)).fetchone()
                if evidence:conn.execute('INSERT INTO reply_grounding VALUES(?,?,?)',(mapping[m['id']],dumps(remap(json.loads(evidence['sources']),original=True)),dumps(remap(json.loads(evidence['report'])))))
                g=conn.execute('SELECT * FROM genui_messages WHERE message_id=?',(m['id'],)).fetchone()
                if g:
                    fields=dict(g);fields['message_id']=mapping[m['id']]
                    fields['raw']=remap_raw(fields['raw'])
                    for k in ('parts','trusted_data','snapshots'):fields[k]=dumps(remap(json.loads(fields[k])))
                    cols=','.join(fields);conn.execute(f'INSERT INTO genui_messages({cols}) VALUES({",".join("?" for _ in fields)})',tuple(fields.values()))
                interaction=conn.execute('SELECT * FROM genui_interactions WHERE message_id=?',(m['id'],)).fetchone()
                if interaction and interaction['origin_message_id'] in mapping:
                    conn.execute('INSERT INTO genui_interactions VALUES(?,?,?)',(mapping[m['id']],mapping[interaction['origin_message_id']],dumps(remap(json.loads(interaction['context'])))))
            return detail(conn,new,current['id'],settings)

    @app.post('/api/conversations/{cid}/messages/{mid}/share')
    def share(cid:str,mid:str,payload:Share,current=Depends(user)):
        rate_limit(db,'share:'+current['id'],30,3600)
        with db.connect(write=True) as conn:
            r=message(conn,cid,mid,current['id'])
            if r['status']!='complete':raise HTTPException(409,'回复结束后再分享')
            token=secrets.token_urlsafe(32);now=int(time.time())
            conn.execute('DELETE FROM reply_shares WHERE expires_at<?',(now,))
            conn.execute('INSERT INTO reply_shares VALUES(?,?,?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),cid,mid,'小信使的回复',payload.body or r['content'],now+7*86400,now))
        return {'url':'/static/share.html#'+token,'expires_at':now+7*86400,'token':token}

    @app.get('/api/shared-replies/{token}')
    def shared(token:str):
        if len(token)>100:raise HTTPException(404,'分享不存在或已失效')
        with db.connect() as conn:
            r=conn.execute('SELECT title,body,expires_at FROM reply_shares WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
            if not r:raise HTTPException(404,'分享已撤回或超过 7 天有效期')
            return dict(r)

    @app.delete('/api/conversations/{cid}/shares/{token}')
    def revoke(cid:str,token:str,current=Depends(user)):
        with db.connect(write=True) as conn:
            own(conn,cid,current['id']);conn.execute('DELETE FROM reply_shares WHERE conversation_id=? AND token_hash=?',(cid,hashlib.sha256(token.encode()).hexdigest()))
        return {'ok':True}

    @app.get('/api/conversations/{cid}/sources/{sid}/preview')
    def preview(cid:str,sid:str,page:int=1,q:str='',current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id']);r=conn.execute('SELECT s.sections,s.name,l.full_sections FROM conversation_sources s LEFT JOIN material_library l ON l.source_id=s.id WHERE s.conversation_id=? AND s.id=?',(cid,sid)).fetchone()
            if not r:raise HTTPException(404,'材料不存在')
            sections=json.loads(r['full_sections'] or r['sections']);total=len(sections)
            if q:sections=[s for s in sections if q[:200].lower() in s['text'].lower()]
            original=conn.execute('SELECT kind,content FROM conversation_sources WHERE id=?',(sid,)).fetchone();resources=[];frames=1
            if original['kind'] in {'tif','tiff'}:
                try:
                    from PIL import Image
                    with Image.open(io.BytesIO(original['content'])) as picture:frames=min(1000,picture.n_frames)
                except (ValueError,OSError):pass
            if original['kind'] in {'docx','pptx','xlsx','odt','ods','odp'}:
                try:
                    with zipfile.ZipFile(io.BytesIO(original['content'])) as archive:
                        names=[n for n in archive.namelist() if n.startswith(('word/media/','ppt/media/','xl/media/','Pictures/')) and n.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp'))]
                        resources=[{'name':name.split('/')[-1],'url':f'/api/conversations/{cid}/sources/{sid}/media/{index}'} for index,name in enumerate(names)]
                except (ValueError,zipfile.BadZipFile):pass
            resource_count=len(resources)
            pages=max(1,(len(sections)+49)//50,0 if q else (resource_count+19)//20);page=max(1,min(page,pages))
            return {'name':r['name'],'sections':sections[(page-1)*50:page*50],'total':total,'matched':len(sections),'page':page,'pages':pages,'resources':[] if q else resources[(page-1)*20:page*20],'resource_count':resource_count,'frames':frames}

    @app.get('/api/conversations/{cid}/sources/{sid}/media/{index}')
    def embedded(cid:str,sid:str,index:int,current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id']);row=conn.execute('SELECT kind,content FROM conversation_sources WHERE id=? AND conversation_id=?',(sid,cid)).fetchone()
            if not row or row['kind'] not in {'docx','pptx','xlsx','odt','ods','odp'}:raise HTTPException(404,'内嵌图片不存在')
        try:
            with zipfile.ZipFile(io.BytesIO(row['content'])) as archive:
                names=[n for n in archive.namelist() if n.startswith(('word/media/','ppt/media/','xl/media/','Pictures/')) and n.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp'))]
                if index<0 or index>=len(names) or archive.getinfo(names[index]).file_size>20*1024*1024:raise ValueError()
                data=archive.read(names[index])
            from PIL import Image
            Image.MAX_IMAGE_PIXELS=20000000
            with Image.open(io.BytesIO(data)) as picture:picture.verify();mime=Image.MIME[picture.format]
            return Response(data,media_type=mime)
        except (ValueError,KeyError,OSError,zipfile.BadZipFile):raise HTTPException(404,'图片无法读取，请下载原件核对') from None

    @app.post('/api/workspace-search')
    async def search(request:Request,current=Depends(user)):
        rate_limit(db,'retrieval:'+current['id'],60,60)
        form=await request.form(max_files=1,max_fields=12,max_part_size=10000)
        try:
            query=str(form.get('query',''))[:200];cid=str(form.get('conversation_id',''));scope=str(form.get('scope','materials'));kind=str(form.get('kind',''));status=str(form.get('status',''));period=str(form.get('period','all'));method='文字检索'
            if scope not in {'materials','history','sources'}:raise HTTPException(422,'请选择材料、历史对话或来源检索')
            if scope=='materials':
                with db.connect() as conn:own(conn,cid,current['id'])
            file=form.get('file')
            if file and hasattr(file,'read'):
                data=await file.read(5*1024*1024+1)
                if len(data)>5*1024*1024:raise HTTPException(413,'检索文件最多 5 MB，请换一份更小的文件')
                source=await run_in_threadpool(library_file,file.filename or 'query.txt',data)
                if source['status']=='failed':raise HTTPException(422,source['warning'])
                if source['kind'] in {'gif','bmp','tif','tiff'}:
                    from PIL import Image
                    with Image.open(io.BytesIO(data)) as picture:
                        if getattr(picture,'n_frames',1)>1:raise HTTPException(422,'检索图片含多页或多帧，请选取要查找的那一页另存为 PNG 或 JPG')
                        out=io.BytesIO();picture.convert('RGB').save(out,format='PNG');source.update(kind='png',content=out.getvalue())
                if source['kind'] in chat_ai.IMAGE_MIME:
                    if not settings.ai_api_key:raise HTTPException(409,'图片检索需要视觉模型。请在设置中配置模型，或改用文字关键词。')
                    if not heavy_lock.acquire(blocking=False):raise HTTPException(429,'模型正在处理其他请求，请稍后重新检索')
                    try:
                        day=time.strftime('%Y-%m-%d',time.gmtime(time.time()+8*3600));rate_limit(db,'ai:'+current['id']+':'+day,settings.ai_daily_limit,86400)
                        answer,_=await run_in_threadpool(chat_ai.reply,settings,[source],[{'role':'user','content':'只返回图片中适合搜索历史资料的 3 至 8 个关键词，用空格分隔，不要解释。'}],{})
                    except AIError as error:raise HTTPException(422,str(error)) from None
                    finally:heavy_lock.release()
                    query=(query+' '+answer['answer'])[:300];method='视觉关键词检索，请核对识别词'
                else:
                    text=' '.join(s['text'] for s in source['full_sections'])
                    if not text.strip():raise HTTPException(422,'查询文件没有可读取文字，请换成文字文档或图片')
                    query=(query+' '+' '.join(keywords(text)[:20]))[:300];method='文件文字相似检索'
            terms=keywords(query);cutoff=int(time.time())-({'week':7,'month':30}.get(period,99999)*86400)
            def find_matches():
                with db.connect() as conn:
                    if scope=='materials':
                        own(conn,cid,current['id']);rows=[dict(r) for r in conn.execute('SELECT s.id,s.name,s.kind,s.status,s.created_at,s.sections,l.path,l.full_sections FROM conversation_sources s LEFT JOIN material_library l ON l.source_id=s.id WHERE s.conversation_id=?',(cid,))]
                        for r in rows:r['text']=r['name']+' '+(r['path'] or '')+' '+' '.join(s['text'] for s in json.loads(r['full_sections'] or r['sections']))
                    elif scope=='sources':
                        rows=[]
                        for c in conn.execute('SELECT * FROM source_catalog WHERE user_id=? ORDER BY updated_at DESC',(current['id'],)):
                            d=json.loads(c['data']);rows.append({'id':c['id'],'name':d['name'],'kind':d['platform'],'created_at':c['updated_at'],'text':' '.join(str(v) for v in d.values())})
                    else:
                        rows=[]
                        for c in conn.execute('SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC',(current['id'],)):
                            messages=[m['content'] for m in conn.execute('SELECT content FROM conversation_messages WHERE conversation_id=?',(c['id'],))]
                            source_rows=[dict(s) for s in conn.execute('SELECT s.id,s.name,s.sections,l.full_sections FROM conversation_sources s LEFT JOIN material_library l ON l.source_id=s.id WHERE s.conversation_id=?',(c['id'],))]
                            if kind=='with-materials' and not source_rows:continue
                            if status and not conn.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? AND role=?',(c['id'],status)).fetchone():continue
                            text=c['title']+' '+' '.join(messages)+' '+' '.join(s['name']+' '+' '.join(p['text'] for p in json.loads(s['full_sections'] or s['sections'])) for s in source_rows)
                            rows.append({'id':c['id'],'name':c['title'],'title':c['title'],'created_at':c['updated_at'],'updated_at':c['updated_at'],'source_count':len(source_rows),'text':text})
                    result=[]
                    for r in rows:
                        if r['created_at']<cutoff or (scope in {'materials','sources'} and ((kind and r['kind']!=kind) or (status and r.get('status')!=status))):continue
                        text=r.pop('text').lower();score=sum(min(20,text.count(t)) for t in terms)
                        if terms and not score:continue
                        pos=next((text.find(t) for t in terms if t in text),0);r['snippet']=text[max(0,pos-25):pos+115];r['score']=score
                        for k in ('sections','full_sections'):r.pop(k,None)
                        result.append(r)
                    result.sort(key=lambda r:(-r['score'],-r['created_at']))
                    return {'items':result,'query':query,'method':method,'total':len(result)}
            return await run_in_threadpool(find_matches)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        finally:await form.close()
