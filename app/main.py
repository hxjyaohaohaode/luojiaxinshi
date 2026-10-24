from datetime import datetime, timedelta, timezone
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import re
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import ai
from .version import VERSION
from .backups import daily_backup
from .calendar_export import build_calendar, eligible
from .config import ROOT, Settings
from .db import Database, audit, dumps, ident
from .documents import MAX_CHARS, MAX_FILE, blockers, file_source, text_source, total_chars
from .models import (CalendarRequest, Confirm, EditCache, Generate, Login, PasswordChange, Profile, ProfilePatch, Register, Recover,
                     TaskData, TaskUpdate, Version, safe_url)
from .security import DUMMY_PASSWORD, hash_password, new_invite, rate_limit, token_hash, verify_password
from .workspace import install_workspace, conversation_detail
from .genui_api import feature_settings
from .integrations import install_integrations
from .speech import install_speech
from .schedule import install_schedule, serialize as serialize_arrangement, own as own_arrangement
from .workflow import install_workflow, enrich_tasks, notice_changes, require_dependency_ready, reconcile_materials
from .execution import notice_processing

MAX_BODY = 26*1024*1024
CST = timezone(timedelta(hours=8))
# Exact, reviewed Codex annotation stylesheets. A desktop update may change the
# sheet; retain the previous signature for previews opened in older clients.
# These hashes authorize CSS only, and only on non-production loopback origins.
LOCAL_ANNOTATION_STYLE_HASHES = (
    'WO55anZ1V8A0G22bY2t72RV4dI79SLI4VnYLgsEeWUc=',
    '62lPaUtpvg47KrxPOXYc0Ki8fkE6PNsbY5I9DpyEwZ4=',  # Codex 26.1021.3705
)


class RequestGuard:
    def __init__(self, app, origin, production):
        self.app, self.origin, self.production = app, origin, production
        # No third-party CSS is copied or executed by this application.
        local_preview = not production and urlparse(origin).hostname in {'localhost','127.0.0.1','::1'}
        style_hash = ''.join(f" 'sha256-{digest}'" for digest in LOCAL_ANNOTATION_STYLE_HASHES) if local_preview else ''
        self.csp = ("default-src 'self'; script-src 'self'; style-src 'self'" + style_hash + "; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'").encode('ascii')

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers=dict(scope['headers'])
        method=scope['method']
        webhook=scope.get('path')=='/api/integrations/qq/webhook' and method=='POST'
        body_limit=256*1024 if webhook or scope.get('path','').endswith('/ui-state') or scope.get('path','').startswith('/api/genui/') else MAX_BODY
        error=None
        try:
            if int(headers.get(b'content-length',b'0'))>body_limit:
                error=(413,'请求超过大小限制，请减少内容')
        except ValueError:
            error=(400,'无效的请求长度')
        if method not in {'GET','HEAD','OPTIONS'} and not webhook:
            if headers.get(b'origin',b'').decode()!=self.origin or headers.get(b'x-requested-with')!=b'campus-notice':
                error=(403,'请求来源校验失败，请从工作台重试')
        if error:
            return await JSONResponse({'detail':error[1]},status_code=error[0])(scope,receive,send)
        received=0
        started=False

        async def limited_receive():
            nonlocal received
            message=await receive()
            if message['type']=='http.request':
                received+=len(message.get('body',b''))
                if received>body_limit:
                    raise HTTPException(413,'请求体超过限制')
            return message

        async def secure_send(message):
            nonlocal started
            if message['type']=='http.response.start':
                started=True
                pdf_preview=scope.get('path','').startswith('/api/conversations/') and scope.get('path','').endswith('/download') and any(k.lower()==b'content-type' and v.startswith(b'application/pdf') for k,v in message.get('headers',[]))
                path=scope.get('path','')
                # 图片等资源按天缓存；脚本与样式每次用 ETag 重新校验（未变化时返回 304），
                # 避免每次打开页面重新下载全部前端代码；接口与首页仍不缓存。
                cache=b'public, max-age=86400' if path.startswith('/static/assets/') else b'no-cache' if path.startswith('/static/') else b'no-store'
                extra=[(b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'SAMEORIGIN' if pdf_preview else b'DENY'),
                       (b'referrer-policy',b'no-referrer'),(b'cache-control',cache),
                       (b'permissions-policy',b'camera=(), microphone=(self), on-device-speech-recognition=(self), geolocation=()'),
                       (b'content-security-policy',self.csp.replace(b"frame-ancestors 'none'",b"frame-ancestors 'self'") if pdf_preview else self.csp)]
                if self.production:
                    extra.append((b'strict-transport-security',b'max-age=31536000'))
                message['headers']=message.get('headers',[])+extra
            await send(message)
        await self.app(scope,limited_receive,secure_send)


def create_app(settings=None):
    settings=settings or Settings.from_env()
    db=Database(settings.data_dir/'campus.sqlite3')
    from .execution import Runtime,HEARTBEAT_SECONDS
    runtime=Runtime(db)

    @asynccontextmanager
    async def lifespan(application):
        await run_in_threadpool(runtime.tick)
        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                try:await run_in_threadpool(runtime.tick)
                except Exception:logging.getLogger('campus').error('execution_heartbeat_failed: check storage and permissions')
        async def maintain():
            while True:
                try:
                    await run_in_threadpool(daily_backup,db,settings)
                except Exception:
                    # No source content, credentials, profile, or filesystem paths in normal logs.
                    logging.getLogger('campus').error('daily_backup_failed: check storage and permissions')
                await asyncio.sleep(3600)
        worker=asyncio.create_task(maintain())
        lease_worker=asyncio.create_task(heartbeat())
        async def memory_maintenance():
            from .memory_learning import drain_jobs
            while True:
                await asyncio.sleep(10)
                # 学习与复盘分开兜底：一边出错不会让另一边永远停住；日志只记异常类型，不含内容。
                try:
                    await run_in_threadpool(drain_jobs,db)
                except Exception as error:logging.getLogger('campus').error('memory_learning_failed error=%s',type(error).__name__)
                try:
                    from .memory_reflection import run_one
                    await run_in_threadpool(run_one,db,settings)
                except Exception as error:logging.getLogger('campus').error('memory_reflection_failed error=%s',type(error).__name__)
        memory_worker=asyncio.create_task(memory_maintenance())
        try:
            yield
        finally:
            await application.state.agent_service.close()
            pending=list(getattr(application.state,'genui_workers',()))
            for task in pending:task.cancel()
            if pending:await asyncio.gather(*pending,return_exceptions=True)
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            lease_worker.cancel()
            memory_worker.cancel()
            await asyncio.gather(lease_worker,memory_worker,return_exceptions=True)
            await run_in_threadpool(runtime.close)

    app=FastAPI(title='校园通知智能转办助手',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.db, app.state.settings = db, settings
    app.state.execution=runtime
    app.add_middleware(RequestGuard,origin=settings.origin,production=settings.production)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlparse(settings.origin).hostname])
    heavy_lock=threading.BoundedSemaphore(2)
    # 通知整理单独限流：聊天一轮可能持续很久，不能因此让通知整理返回“繁忙”。
    notice_lock=threading.BoundedSemaphore(2)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        fields=', '.join('.'.join(str(x) for x in e['loc'][1:]) for e in exc.errors()[:5])
        return JSONResponse({'detail':'字段不符合要求，请检查：'+fields},status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse({'detail':'存储暂时不可用，操作未确认成功，请稍后重试'},status_code=503)

    def user(request: Request):
        raw=request.cookies.get('campus_session','')
        with db.connect() as conn:
            row=conn.execute('SELECT u.*, s.csrf, s.token_hash AS session_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',
                             (token_hash(raw),int(time.time()))).fetchone()
        if row is None:
            raise HTTPException(401,'请先登录，或登录已过期')
        if request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),row['csrf']):
            raise HTTPException(403,'页面令牌已过期，请刷新后重试')
        return dict(row)

    def admin(current=Depends(user)):
        if current['role']!='admin':
            raise HTTPException(403,'仅管理员可使用')
        return current

    from .execution import install as install_execution
    install_execution(app,db,user)
    from .account import install as install_account, record_consent, consent_state
    install_account(app,db,settings,user)
    from .agent_runtime.api import install as install_agent_runtime
    install_agent_runtime(app,db,settings,user,runtime.owner)

    def own_notice(conn, notice_id, uid):
        row=conn.execute('SELECT * FROM notices WHERE id=? AND user_id=?',(notice_id,uid)).fetchone()
        if row is None:
            raise HTTPException(404,'通知不存在或无权访问')
        return dict(row)

    def own_task(conn, task_id, uid):
        row=conn.execute('SELECT * FROM tasks WHERE id=? AND user_id=?',(task_id,uid)).fetchone()
        if row is None:
            raise HTTPException(404,'待办不存在或无权访问')
        return dict(row)

    def expect_version(record, version):
        if record['version']!=version:
            raise HTTPException(409,'内容已在其他页面更新，请刷新后核对；本次修改未覆盖新版本')

    def get_sources(conn, nid, active_only=False, include_content=False):
        records=[]
        origins={r['source_id']:json.loads(r['data']) for r in conn.execute('SELECT o.* FROM notice_source_origins o JOIN sources s ON s.id=o.source_id WHERE s.notice_id=?',(nid,))}
        columns='id,name,kind,sha256,status,sections,warning,active,created_at'+(',content' if include_content else '')
        for row in conn.execute('SELECT '+columns+' FROM sources WHERE notice_id=? ORDER BY created_at,rowid',(nid,)):
            source=dict(row)
            source['sections']=json.loads(source['sections'])
            if source['id'] in origins:source['origin']=origins[source['id']]
            if not active_only or source['active']:
                records.append(source)
        return records

    def store_source(conn,nid,source):
        conn.execute('INSERT INTO sources(id,notice_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (source['id'],nid,source['name'],source['kind'],source['content'],source['sha256'],source['status'],dumps(source['sections']),source['warning'],int(time.time())))
        from .notice_intake import save_origin
        save_origin(conn,source['id'],source)

    def invalidate(conn,nid):
        from .notice_intake import reopen
        reopen(conn,nid)
        conn.execute("UPDATE notices SET version=version+1,draft=NULL,draft_version=NULL,status='received',error=NULL,processing_token=NULL,processing_at=NULL,updated_at=? WHERE id=?",(int(time.time()),nid))

    def serialize_task(row):
        task=dict(row)
        task['data']=json.loads(task['data'])
        task['needs_calendar_sync']=task['exported_version'] is not None and task['exported_version']!=task['version']
        data=task['data']
        now=datetime.now(CST)
        task['overdue']=False
        task['due_soon']=False
        if task['status']=='pending' and data.get('due_date') and data.get('deadline_confirmed'):
            if data.get('due_time'):
                deadline=datetime.fromisoformat(data['due_date']+'T'+data['due_time']).replace(tzinfo=CST)
                task['overdue']=deadline<now
                task['due_soon']=now<=deadline<=now+timedelta(days=7)
            else:
                day=datetime.fromisoformat(data['due_date']).date()
                task['overdue']=day<now.date()
                task['due_soon']=now.date()<=day<=now.date()+timedelta(days=7)
        return task

    def detailed_notice(conn,nid,uid):
        record=own_notice(conn,nid,uid)
        from .notice_intake import disposition
        record['handling']=disposition(conn,nid)
        active=notice_processing(conn,record,settings.ai_timeout)
        record.pop('processing_token',None)
        if record['status']=='processing' and not active:
            record['status']='failed'
            record['error']='上次处理已中断，可以重试'
        record['draft']=json.loads(record['draft']) if record['draft'] else None
        record['sources']=get_sources(conn,nid)
        record['blockers']=blockers(record,[s for s in record['sources'] if s['active']])
        record['character_count']=total_chars([s for s in record['sources'] if s['active']])
        record['tasks']=[serialize_task(t) for t in conn.execute('SELECT * FROM tasks WHERE notice_id=? ORDER BY created_at,rowid',(nid,))]
        enrich_tasks(conn, record['tasks'])
        record['changes'] = notice_changes(conn, nid, uid)
        from .notice_progress import decode
        record['calls']=[]
        for call in conn.execute('''SELECT a.model,a.status,a.input_tokens,a.output_tokens,a.created_at,m.metrics
            FROM ai_calls a LEFT JOIN execution_metrics m ON m.execution_id=a.id
            WHERE a.notice_id=? ORDER BY a.created_at DESC,a.rowid DESC LIMIT 10''',(nid,)):
            value=dict(call);value['metrics']=decode(value['metrics']);record['calls'].append(value)
        run=conn.execute('''SELECT status,stage,started_at FROM executions WHERE notice_id=?
            ORDER BY started_at DESC,rowid DESC LIMIT 1''',(nid,)).fetchone()
        record['execution']=dict(run) if run else None
        from .notice_resolution import receipt
        record['quality_resolution_contract']=1
        record['review_observation_contract']=1
        record['quality_receipt']=receipt(conn,nid) if record['status']=='confirmed' else None
        return record

    def session_response(uid, extra=None):
        token=secrets.token_urlsafe(32)
        csrf=secrets.token_urlsafe(32)
        now=int(time.time())
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM sessions WHERE expires_at<?',(now,))
            conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(token),uid,csrf,now+7*86400))
        response=JSONResponse({'ok':True,**(extra or {})})
        response.set_cookie('campus_session',token,max_age=7*86400,httponly=True,secure=settings.production,samesite='strict',path='/')
        return response

    @app.get('/api/health')
    def health():
        with db.connect() as conn:
            conn.execute('SELECT 1').fetchone()
        return {'status':'ok','version':VERSION}

    @app.get('/api/session')
    def session(current=Depends(user)):
        from .model_catalog import public_configuration
        with db.connect() as conn:
            genui=feature_settings(conn,current['id'],settings)
            consent=consent_state(conn,current['id'])
        return {'user':{'id':current['id'],'username':current['username'],'display_name':current['display_name'],
                        'role':current['role'],'profile':json.loads(current['profile'])},'csrf':current['csrf'],
                'ai':public_configuration(settings),'genui':genui,'consent':consent,
                'environment':'production' if settings.production else 'local','task_board_contract':1}

    @app.post('/api/auth/login')
    def login(payload: Login, request: Request):
        ip=request.client.host if request.client else 'unknown'
        rate_limit(db,'login-ip:'+ip,30,900)
        rate_limit(db,'login-user:'+payload.username.lower(),10,900)
        with db.connect() as conn:
            record=conn.execute('SELECT * FROM users WHERE username=?',(payload.username.lower(),)).fetchone()
        valid=verify_password(payload.password,record['password'] if record else DUMMY_PASSWORD)
        if not valid or record is None:
            raise HTTPException(401,'用户名或密码错误')
        return session_response(record['id'])

    @app.get('/api/auth/policy')
    def registration_policy():
        return {'registration_mode': settings.registration_mode}

    @app.post('/api/auth/register')
    def register(payload: Register, request: Request):
        if settings.registration_mode == 'invite' and not payload.invite:
            raise HTTPException(403,'当前仅开放受邀试点，请使用维护者提供的一次性邀请链接')
        rate_limit(db,'register:'+(request.client.host if request.client else 'unknown'),15,900)
        password=hash_password(payload.password)
        uid=ident()
        now=int(time.time())
        recovery=secrets.token_urlsafe(24)
        if not payload.accepted_terms:
            raise HTTPException(422,'请先阅读并同意《隐私政策》和《用户协议》')
        if payload.account_kind=='phone' and not re.fullmatch(r'\+?[0-9]{7,15}',payload.username):
            raise HTTPException(422,'手机号账号应为 7—15 位数字，可带国际区号 +')
        with db.connect(write=True) as conn:
            invite=conn.execute('SELECT * FROM invites WHERE token_hash=? AND used_at IS NULL AND expires_at>?',(token_hash(payload.invite),now)).fetchone() if payload.invite else None
            if payload.invite and invite is None:
                raise HTTPException(400,'邀请链接无效、已使用或已过期，请向管理员获取新链接')
            if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]>=5000:
                raise HTTPException(503,'本站账号容量已满，请联系管理员')
            if conn.execute('SELECT 1 FROM users WHERE username=?',(payload.username.lower(),)).fetchone():
                raise HTTPException(409,'该用户名已被使用')
            profile=Profile(campus_role=payload.campus_role).model_dump()
            if payload.account_kind!='username':
                profile[payload.account_kind]=payload.username
            conn.execute('INSERT INTO users(id,username,password,display_name,role,profile,created_at) VALUES(?,?,?,?,?,?,?)',
                         (uid,payload.username.lower(),password,payload.display_name,invite['role'] if invite else 'user',dumps(profile),now))
            conn.execute('INSERT INTO account_recovery VALUES(?,?)',(uid,token_hash(recovery)))
            record_consent(conn,uid,now)
            if invite:
                conn.execute('UPDATE invites SET used_at=? WHERE token_hash=?',(now,token_hash(payload.invite)))
        return session_response(uid,{'recovery_code':recovery})

    @app.post('/api/auth/recover')
    def recover(payload:Recover,request:Request):
        rate_limit(db,'recover:'+(request.client.host if request.client else 'unknown'),5,900)
        rate_limit(db,'recover-user:'+payload.username.lower(),5,900)
        new_code=secrets.token_urlsafe(24)
        with db.connect(write=True) as conn:
            record=conn.execute('SELECT u.id,r.code_hash FROM users u JOIN account_recovery r ON r.user_id=u.id WHERE u.username=?',(payload.username.lower(),)).fetchone()
            if not record or not secrets.compare_digest(record['code_hash'],token_hash(payload.recovery_code)):
                raise HTTPException(400,'账号或恢复码不正确，密码未修改')
            conn.execute('UPDATE users SET password=? WHERE id=?',(hash_password(payload.password),record['id']))
            conn.execute('UPDATE account_recovery SET code_hash=? WHERE user_id=?',(token_hash(new_code),record['id']))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(record['id'],))
        return session_response(record['id'],{'recovery_code':new_code})

    @app.post('/api/auth/logout')
    def logout(current=Depends(user)):
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(current['session_hash'],))
        result=JSONResponse({'ok':True})
        result.delete_cookie('campus_session',path='/',secure=settings.production,samesite='strict')
        return result

    @app.post('/api/auth/password')
    def change_password(payload:PasswordChange,current=Depends(user)):
        rate_limit(db,'password:'+current['id'],5,900)
        if not verify_password(payload.old_password,current['password']):
            raise HTTPException(400,'原密码不正确')
        with db.connect(write=True) as conn:
            conn.execute('UPDATE users SET password=? WHERE id=?',(hash_password(payload.new_password),current['id']))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(current['id'],))
        return session_response(current['id'])

    @app.put('/api/profile')
    def profile(payload:Profile,current=Depends(user)):
        with db.connect(write=True) as conn:
            conn.execute('UPDATE users SET profile=? WHERE id=?',(payload.model_dump_json(),current['id']))
        return {'ok':True}

    @app.patch('/api/profile')
    def patch_profile(payload:ProfilePatch,current=Depends(user)):
        changes=payload.changes.model_dump(exclude_unset=True)
        expected=payload.expected.model_dump(exclude_unset=True)
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()
            if row is None:
                raise HTTPException(401,'请重新登录')
            saved=Profile.model_validate_json(row['profile']).model_dump()
            conflicts=[key for key,value in changes.items() if saved[key]!=expected[key] and saved[key]!=value]
            if conflicts:
                raise HTTPException(409,{'code':'profile_conflict','message':'这些资料已在另一处修改。本次填写已保留，请先核对最新值。',
                                         'fields':conflicts,'profile':saved})
            updated=Profile.model_validate({**saved,**changes})
            conn.execute('UPDATE users SET profile=? WHERE id=?',(updated.model_dump_json(),current['id']))
        return {'profile':updated.model_dump()}

    @app.post('/api/admin/invites')
    def invite(current=Depends(admin)):
        rate_limit(db,'invite:'+current['id'],30,86400)
        raw=new_invite(db)
        return {'url':settings.origin+'/#invite='+raw,'expires_in_days':7}

    def check_cache_key(conn,key,uid,check_version=True):
        if key in {'new-notice','intake-batch','chat-new','arrangement-new'}:
            return None
        if re.fullmatch(r'chat:[a-f0-9]{32}',key):
            if not conn.execute('SELECT 1 FROM conversations WHERE id=? AND user_id=?',(key[5:],uid)).fetchone():
                raise HTTPException(404,'对话不存在或无权访问')
            return None
        branch_key=re.fullmatch(r'branch:([a-f0-9]{32}):([a-f0-9]{32})',key)
        if branch_key:
            cid,mid=branch_key.groups()
            if not conn.execute("SELECT 1 FROM conversations c JOIN conversation_messages m ON m.conversation_id=c.id WHERE c.id=? AND c.user_id=? AND m.id=? AND m.role='assistant' AND m.status='complete'",(cid,uid,mid)).fetchone():
                raise HTTPException(404,'原回答不存在或无权访问')
            return None
        workflow_key = re.fullmatch(r'(workflow|review):([a-f0-9]{32}):([1-9][0-9]{0,8}):([0-9]{1,9})',key)
        if workflow_key:
            kind,tid, task_version, workflow_version = workflow_key.groups()
            record = own_task(conn, tid, uid)
            if check_version:
                expect_version(record, int(task_version))
                saved = conn.execute('SELECT version FROM '+('task_reviews' if kind=='review' else 'task_workflows')+' WHERE task_id=?', (tid,)).fetchone()
                expect_version({'version': saved['version'] if saved else 0}, int(workflow_version))
            return record['notice_id']
        matched=re.fullmatch(r'(notice|change|task|arrangement):([a-f0-9]{32}):([1-9][0-9]{0,8})',key)
        if matched is None:
            raise HTTPException(422,'编辑草稿标识不合法')
        kind,rid,version=matched.groups()
        if kind=='arrangement':
            own_arrangement(conn,rid,uid,int(version) if check_version else None)
            return None
        record=own_notice(conn,rid,uid) if kind in {'notice','change'} else own_task(conn,rid,uid)
        if check_version:
            expect_version(record,int(version))
        return rid if kind in {'notice','change'} else record['notice_id']

    @app.get('/api/edit-cache/{key}')
    def read_cache(key:str,current=Depends(user)):
        with db.connect() as conn:
            check_cache_key(conn,key,current['id'])
            row=conn.execute('SELECT payload,revision FROM edit_caches WHERE user_id=? AND cache_key=?',(current['id'],key)).fetchone()
        return {'payload':json.loads(row['payload']) if row and row['payload'] else None,'revision':row['revision'] if row else 0}

    @app.put('/api/edit-cache/{key}')
    def write_cache(key:str,payload:EditCache,current=Depends(user)):
        serialized=dumps(payload.payload) if payload.payload is not None else None
        if serialized and len(serialized)>180000:
            raise HTTPException(413,'编辑草稿过大，请缩短内容后保存')
        with db.connect(write=True) as conn:
            nid=check_cache_key(conn,key,current['id'],check_version=payload.payload is not None)
            row=conn.execute('SELECT revision FROM edit_caches WHERE user_id=? AND cache_key=?',(current['id'],key)).fetchone()
            revision=row['revision'] if row else 0
            if revision!=payload.revision:
                raise HTTPException(409,'编辑草稿已被其他页面更新，本页内容未覆盖新草稿')
            conn.execute('INSERT INTO edit_caches(user_id,cache_key,payload,revision,notice_id,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,cache_key) DO UPDATE SET payload=excluded.payload,revision=excluded.revision,updated_at=excluded.updated_at',
                         (current['id'],key,serialized,revision+1,nid,int(time.time())))
        return {'revision':revision+1,'payload':payload.payload}

    @app.get('/api/notices')
    def notices(current=Depends(user)):
        with db.connect() as conn:
            # applicability 来自整理结果：是否与本人已知条件相符，供列表按“与我相关”筛选。
            return [dict(r) for r in conn.execute("SELECT n.id,n.title,n.source_label,n.status,n.version,n.created_at,n.updated_at,n.error,COALESCE(d.disposition,'inbox') AS disposition,(SELECT COUNT(*) FROM tasks t WHERE t.notice_id=n.id) AS task_count,CASE WHEN n.draft IS NOT NULL AND json_valid(n.draft) THEN json_extract(n.draft,'$.applicability') END AS applicability FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id WHERE user_id=? ORDER BY n.updated_at DESC",(current['id'],))]

    async def parse_form(request,uid):
        form=await request.form(max_files=5,max_fields=16,max_part_size=120000)
        allowed={'title','body','source_label','source_url','published_at','materials_complete','allow_duplicate','files','version','label','link_preview','request_id'}
        if set(form.keys())-allowed:
            raise HTTPException(422,'含不支持的提交字段')
        values={key:str(form.get(key,'')) for key in allowed-{'files'}}
        body=values['body'].strip()
        if len(body)>MAX_CHARS:
            raise HTTPException(422,'通知正文超过 10000 字，未截断')
        files=form.getlist('files')
        sources=[text_source(body,values['label'][:80] or '通知正文')] if body else []
        try:
            for upload in files:
                if not hasattr(upload,'read'):
                    raise ValueError('附件字段不正确')
                data=await upload.read(MAX_FILE+1)
                sources.append(await run_in_threadpool(file_source,upload.filename or '',data))
                await upload.close()
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        finally:
            await form.close()
        if values['link_preview']:
            from .notice_intake import preview_source
            with db.connect() as conn:sources.append(preview_source(conn,uid,values['link_preview']))
        if sum(s['kind']!='text' for s in sources)>5:
            raise HTTPException(422,'链接文件与上传附件合计最多 5 份')
        if not sources:
            raise HTTPException(422,'请粘贴正文、上传附件，或先读取原文链接')
        return values,sources

    def check_quota(conn,uid,sources,new_notice=False):
        count=conn.execute('SELECT COUNT(*) FROM notices WHERE user_id=?',(uid,)).fetchone()[0]
        size=conn.execute('SELECT COALESCE(SUM(length(content)),0) FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?',(uid,)).fetchone()[0]
        size+=conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?',(uid,)).fetchone()[0]
        if (new_notice and count>=200) or size+sum(len(s['content'] or b'') for s in sources)>200*1024*1024:
            raise HTTPException(413,'当前账号已达到 200 则通知或 200 MB 原件上限，请导出并清理不再需要的通知')

    @app.post('/api/notices')
    async def create_notice(request:Request,current=Depends(user)):
        rate_limit(db,'upload:'+current['id'],40,3600)
        values,sources=await parse_form(request,current['id'])
        title=values['title'].strip()
        if not title or len(title)>160 or len(values['source_label'])>100:
            raise HTTPException(422,'请填写 1—160 字标题，来源名称不超过 100 字')
        try:
            source_url=safe_url(values['source_url'])
            published=None
            if values['published_at']:
                dt=datetime.fromisoformat(values['published_at'])
                if dt.tzinfo is None:
                    raise ValueError('原发布时间须包含时区')
                published=dt.astimezone(CST).isoformat()
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        if total_chars(sources)>MAX_CHARS:
            raise HTTPException(422,'正文与附件合计超过 10000 字，请拆分通知；未静默截断')
        fingerprint=hashlib.sha256('|'.join(sorted(s['sha256'] for s in sources)).encode()).hexdigest()
        nid=ident()
        now=int(time.time())
        with db.connect(write=True) as conn:
            from .notice_intake import prior_submission,submission_digest
            digest=submission_digest(values,fingerprint)
            previous=prior_submission(conn,current['id'],values['request_id'],digest)
            if previous:return detailed_notice(conn,previous,current['id'])
            check_quota(conn,current['id'],sources,True)
            duplicate=conn.execute('SELECT id,title FROM notices WHERE user_id=? AND fingerprint=?',(current['id'],fingerprint)).fetchone()
            if duplicate and values['allow_duplicate']!='true':
                raise HTTPException(409,{'message':'发现内容相同的通知，可打开原通知；不同批次可明确另建','duplicate_id':duplicate['id']})
            conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,published_at,materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (nid,current['id'],title,values['source_label'],source_url,published,values['materials_complete']=='true',fingerprint,now,now))
            for source in sources:
                store_source(conn,nid,source)
            if values['request_id']:
                conn.execute('INSERT INTO notice_submissions VALUES(?,?,?,?)',(current['id'],values['request_id'],nid,digest))
            audit(conn,current['id'],nid,'create_notice',after={'title':title,'sources':[s['name'] for s in sources]})
            result=detailed_notice(conn,nid,current['id'])
        return result

    @app.get('/api/notices/{nid}')
    def notice(nid:str,current=Depends(user)):
        with db.connect() as conn:
            return detailed_notice(conn,nid,current['id'])

    @app.post('/api/notices/{nid}/supplement')
    async def supplement(nid:str,request:Request,current=Depends(user)):
        with db.connect() as conn:
            own_notice(conn,nid,current['id'])
        values,sources=await parse_form(request,current['id'])
        try:
            version=int(values['version'])
        except ValueError:
            raise HTTPException(422,'缺少通知版本') from None
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            from .notice_intake import prior_submission,submission_digest
            fingerprint=hashlib.sha256('|'.join(sorted(s['sha256'] for s in sources)).encode()).hexdigest()
            digest=submission_digest({**values,'title':'supplement:'+nid},fingerprint)
            previous=prior_submission(conn,current['id'],values['request_id'],digest)
            if previous:return detailed_notice(conn,previous,current['id'])
            expect_version(record,version)
            check_quota(conn,current['id'],sources)
            existing=get_sources(conn,nid,True)
            if sum(s['kind']!='text' for s in existing+sources)>5:
                raise HTTPException(422,'有效附件合计最多 5 份，请先将旧附件移出当前材料')
            if total_chars(existing+sources)>MAX_CHARS:
                raise HTTPException(422,'合计超过 10000 字，请先整理当前材料')
            if any(s['sha256'] in {x['sha256'] for x in existing} for s in sources):
                raise HTTPException(409,'当前通知已经包含相同材料，请直接复用')
            for source in sources:
                store_source(conn,nid,source)
            invalidate(conn,nid)
            if values['materials_complete'] in {'true','false'}:
                conn.execute('UPDATE notices SET materials_complete=? WHERE id=?',(values['materials_complete']=='true',nid))
            if values['request_id']:
                conn.execute('INSERT INTO notice_submissions VALUES(?,?,?,?)',(current['id'],values['request_id'],nid,digest))
            audit(conn,current['id'],nid,'supplement',after={'sources':[s['name'] for s in sources]})
            return detailed_notice(conn,nid,current['id'])

    @app.post('/api/notices/{nid}/materials')
    async def materials(nid:str,request:Request,current=Depends(user)):
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={'version','complete'} or type(payload['complete']) is not bool:
            raise HTTPException(422,'请明确材料是否齐全')
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            expect_version(record,payload['version'])
            conn.execute('UPDATE notices SET materials_complete=? WHERE id=?',(payload['complete'],nid))
            invalidate(conn,nid)
            audit(conn,current['id'],nid,'materials_review',before=record['materials_complete'],after=payload['complete'])
            return detailed_notice(conn,nid,current['id'])

    @app.post('/api/notices/{nid}/sources/{sid}/review')
    async def source_review(nid:str,sid:str,request:Request,current=Depends(user)):
        payload=await request.json()
        if not isinstance(payload,dict) or set(payload)!={'version','action','reason'} or payload['action'] not in {'resolve','archive'} or not isinstance(payload['reason'],str) or not 2<=len(payload['reason'])<=500:
            raise HTTPException(422,'请填写核实结果或移除原因（2—500 字）')
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            expect_version(record,payload['version'])
            source=conn.execute('SELECT * FROM sources WHERE id=? AND notice_id=?',(sid,nid)).fetchone()
            if source is None:
                raise HTTPException(404,'材料不存在')
            if payload['action']=='resolve':
                if source['status']=='failed':
                    raise HTTPException(422,'解析失败不能直接确认为已解析，请补充文字后将失败文件移出当前材料')
                conn.execute("UPDATE sources SET status='ok' WHERE id=?",(sid,))
            else:
                conn.execute('UPDATE sources SET active=0 WHERE id=?',(sid,))
            invalidate(conn,nid)
            audit(conn,current['id'],nid,'source_'+payload['action'],after={'source_id':sid,'reason':payload['reason']})
            return detailed_notice(conn,nid,current['id'])

    @app.get('/api/notices/{nid}/sources/{sid}/download')
    def download(nid:str,sid:str,request:Request,preview:bool=False,current=Depends(user)):
        with db.connect() as conn:
            own_notice(conn,nid,current['id'])
            source=conn.execute('SELECT * FROM sources WHERE id=? AND notice_id=?',(sid,nid)).fetchone()
            if source is None or source['content'] is None:
                raise HTTPException(404,'附件不存在')
            from .chat_media import VIDEO_MIME,video_response
            if source['kind'] in VIDEO_MIME and source['status']!='failed':return video_response(source['content'],source['kind'],source['name'],request.headers.get('range') if preview else None,preview)
            from .chat_ai import IMAGE_MIME
            inline=preview and source['kind'] in IMAGE_MIME and source['status']!='failed'
            return Response(source['content'],media_type=IMAGE_MIME[source['kind']] if inline else 'application/octet-stream',headers={'Content-Disposition':("inline" if inline else "attachment")+"; filename*=UTF-8''"+quote(source['name'],safe='')})

    @app.post('/api/notices/{nid}/conversation')
    def notice_conversation(nid:str,payload:Version,current=Depends(user)):
        rate_limit(db,'notice-chat:'+current['id'],60,3600)
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id']);expect_version(record,payload.version)
            receipt='notice-chat:'+current['id']+':'+nid+':'+str(record['version'])
            existing=conn.execute('SELECT conversation_id FROM integration_receipts WHERE receipt_key=?',(receipt,)).fetchone()
            if existing and existing['conversation_id'] and conn.execute('SELECT 1 FROM conversations WHERE id=? AND user_id=?',(existing['conversation_id'],current['id'])).fetchone():return {'conversation_id':existing['conversation_id']}
            rows=conn.execute('SELECT * FROM sources WHERE notice_id=? AND active=1 ORDER BY created_at,rowid',(nid,)).fetchall()
            if len(rows)>12:raise HTTPException(400,'本通知附件超过单次对话上限，请选取相关材料另建对话')
            cid=ident();now=int(time.time())
            conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,current['id'],record['title'][:100],now,now))
            for row in rows:
                conn.execute('INSERT INTO conversation_sources(id,conversation_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(ident(),cid,row['name'],row['kind'],row['content'],row['sha256'],row['status'],row['sections'],row['warning'],now))
            conn.execute('INSERT OR REPLACE INTO integration_receipts(receipt_key,user_id,conversation_id,created_at) VALUES(?,?,?,?)',(receipt,current['id'],cid,now))
            return {'conversation_id':cid}

    @app.post('/api/notices/{nid}/manual')
    def manual(nid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            expect_version(record,payload.version)
            from .notice_intake import require_open
            require_open(conn,nid)
            draft={'title':record['title'],'summary':'手工整理，请对照左侧原文填写本人事项。',
                   'applicability':'needs_review','applicability_reason':'手工确认本人适用条件','facts':{},'tasks':[],
                   'warnings':['手工填写结果不计作 AI 提取成功']}
            conn.execute("UPDATE notices SET draft=?,version=version+1,draft_version=version+1,status='draft',error=NULL,processing_token=NULL,updated_at=? WHERE id=?",(dumps(draft),int(time.time()),nid))
            return detailed_notice(conn,nid,current['id'])

    @app.get('/api/notices/{nid}/processing')
    def notice_status(nid:str,current=Depends(user)):
        with db.connect() as conn:
            record=own_notice(conn,nid,current['id'])
            active=notice_processing(conn,record,settings.ai_timeout)
            run=conn.execute('''SELECT status,stage,started_at FROM executions WHERE notice_id=?
                ORDER BY started_at DESC,rowid DESC LIMIT 1''',(nid,)).fetchone()
            return {'status':'failed' if record['status']=='processing' and not active else record['status'],
                'execution':dict(run) if run else None,
                'elapsed_seconds':max(0,int(time.time())-run['started_at']) if run and active else None}

    @app.post('/api/notices/{nid}/generate')
    def generate(nid:str,payload:Generate,current=Depends(user)):
        if not settings.ai_api_key:
            raise HTTPException(503,'尚未配置 AI API Key。可先使用手工整理，配置完成后重试')
        from .model_catalog import notice_settings
        try:run_settings=notice_settings(settings,payload.processing_mode)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        if not notice_lock.acquire(blocking=False):
            raise HTTPException(429,'正在整理的通知有点多，请稍等一会儿再试')
        call_id=ident()
        job=ident()
        try:
            with db.connect() as conn:
                record=own_notice(conn,nid,current['id'])
                expect_version(record,payload.version)
                from .notice_intake import require_open
                require_open(conn,nid)
                if notice_processing(conn,record,settings.ai_timeout):
                    raise HTTPException(409,'该通知正在生成，请等待当前请求完成')
                sources=get_sources(conn,nid,True,include_content=True)
                images=[s for s in sources if s['kind'] in {'png','jpg','jpeg','webp'} and s['status']!='failed']
                if len(images)>4:
                    raise HTTPException(422,'一次最多识别 4 张图片，请先整理当前材料；未静默忽略图片')
                if not sources or (total_chars(sources)==0 and not images) or total_chars(sources)>MAX_CHARS:
                    raise HTTPException(422,'当前材料没有可处理文字或合计超过 10000 字')
                try:
                    ai.prepare_notice_input(run_settings,record,sources,json.loads(current['profile']))
                except ai.AIError as exc:
                    raise HTTPException(422,str(exc)) from None
            # Local rejection must not consume a model attempt or erase a valid draft.
            rate_limit(db,'ai:'+current['id']+':'+datetime.now(CST).date().isoformat(),settings.ai_daily_limit,86400)
            with db.connect(write=True) as conn:
                latest=own_notice(conn,nid,current['id'])
                expect_version(latest,payload.version)
                if notice_processing(conn,latest,settings.ai_timeout):
                    raise HTTPException(409,'该通知正在生成，请等待当前请求完成')
                conn.execute("UPDATE notices SET status='processing',processing_token=?,processing_at=?,error=NULL WHERE id=?",(job,int(time.time()),nid))
                conn.execute('INSERT INTO ai_calls(id,user_id,notice_id,model,status,created_at) VALUES(?,?,?,?,?,?)',(call_id,current['id'],nid,run_settings.ai_model,'processing',int(time.time())))
                runtime.start(conn,call_id,current['id'],'notice',nid,job)
                from .execution import stage
                stage(conn,call_id,'extracting')
                audit(conn,current['id'],nid,'ai_processing_consent',after={'model':run_settings.ai_model,
                    'review_model':run_settings.notice_review_model if run_settings.notice_semantic_review else None,
                    'processing_mode':payload.processing_mode,'maximum_requests':2 if run_settings.notice_semantic_review else 1,
                    'source_ids':[s['id'] for s in sources],'profile':json.loads(current['profile'])})
            try:
                from .notice_progress import CURRENT,Trace,save
                def progress(name):
                    with db.connect(write=True) as conn:
                        live=conn.execute('SELECT n.version,n.processing_token,u.profile FROM notices n JOIN users u ON u.id=n.user_id WHERE n.id=? AND n.user_id=?',(nid,current['id'])).fetchone()
                        if (not live or live['version']!=payload.version or live['processing_token']!=job
                            or json.loads(live['profile'])!=json.loads(current['profile'])
                            or not notice_processing(conn,{'id':nid,'processing_token':job},settings.ai_timeout)):
                            raise ai.AIContextChanged('材料、个人条件或本次执行状态已变化，已停止旧结果处理；请核对当前内容后重新整理。')
                        stage(conn,call_id,name)
                        save(conn,call_id,trace)
                trace=Trace(progress);trace_token=CURRENT.set(trace)
                try:
                    draft,usage=ai.generate(run_settings,record,sources,json.loads(current['profile']))
                finally:
                    CURRENT.reset(trace_token)
                    with db.connect(write=True) as conn:save(conn,call_id,trace)
            except ai.AIError as exc:
                changed=isinstance(exc,ai.AIContextChanged)
                with db.connect(write=True) as conn:
                    returned_usage=exc.usage or {}
                    conn.execute("UPDATE ai_calls SET status=CASE WHEN status='processing' THEN ? ELSE status END,input_tokens=?,output_tokens=? WHERE id=?",('discarded' if changed else 'failed',returned_usage.get('input_tokens'),returned_usage.get('output_tokens'),call_id))
                    conn.execute("UPDATE notices SET status='failed',error=?,processing_token=NULL WHERE id=? AND processing_token=?",(str(exc),nid,job))
                    runtime.finish(conn,call_id,'discarded' if changed else 'failed','context_changed' if changed else 'provider_or_validation')
                raise HTTPException(409 if changed else 502,str(exc)) from None
            with db.connect(write=True) as conn:
                conn.execute("UPDATE ai_calls SET status='succeeded',input_tokens=?,output_tokens=? WHERE id=?",(usage['input_tokens'],usage['output_tokens'],call_id))
                profile_row=conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()
                if profile_row and json.loads(profile_row['profile'])!=json.loads(current['profile']):
                    conn.execute("UPDATE notices SET version=version+1,status='failed',error='生成期间个人条件已变化，请核对后重新整理。',processing_token=NULL WHERE id=? AND processing_token=?",(nid,job))
                cursor=conn.execute("UPDATE notices SET draft=?,draft_version=version+1,version=version+1,status='draft',processing_token=NULL,updated_at=? WHERE id=? AND user_id=? AND version=? AND processing_token=?",
                                    (dumps(draft),int(time.time()),nid,current['id'],payload.version,job))
                if cursor.rowcount!=1:
                    conn.execute("UPDATE ai_calls SET status='discarded' WHERE id=?",(call_id,))
                    result=None
                    runtime.finish(conn,call_id,'discarded','context_changed')
                else:
                    runtime.finish(conn,call_id,'succeeded','draft_ready')
                    result=detailed_notice(conn,nid,current['id'])
            if result is None:
                raise HTTPException(409,'生成期间材料已改变，本次旧草稿已丢弃，请刷新后重新生成')
            return result
        finally:
            try:
                with db.connect(write=True) as conn:
                    abandoned=conn.execute("UPDATE notices SET status='failed',error='处理已中断，请核对后重新整理。',processing_token=NULL,processing_at=NULL WHERE id=? AND processing_token=?",(nid,job)).rowcount
                    if abandoned:
                        conn.execute("UPDATE ai_calls SET status='failed' WHERE id=? AND status='processing'",(call_id,))
                        runtime.finish(conn,call_id,'failed','interrupted_request')
            finally:notice_lock.release()

    def validate_task(data,sources,global_blockers,enforce_future=True):
        ai.check_evidence(data.evidence+data.deadline_evidence+(data.scheduled.evidence if data.scheduled else []),sources)
        value=data.model_dump()
        if data.reminder_at:
            eligible(value)
            if global_blockers and not data.resolution_note:
                raise ValueError('当前材料尚有缺项，请先核对补齐，或填写本步骤不受影响的核实依据')
            if enforce_future and datetime.fromisoformat(data.reminder_at)<=datetime.now(timezone.utc):
                raise ValueError('提醒时间必须晚于现在')
        if data.deadline_confirmed and not data.due_date:
            raise ValueError('尚未填写正式期限日期')
        if data.deadline_confirmed and (data.uncertainties or global_blockers) and not data.resolution_note:
            raise ValueError('确认期限前，请填写相关待核实问题的核实结果')
        if data.scheduled and data.scheduled.confirmed and (data.uncertainties or global_blockers) and not data.resolution_note:
            raise ValueError('确认活动或办理时段前，请填写相关待核实问题的核实结果')
        return value

    @app.post('/api/notices/{nid}/confirm')
    def confirm(nid:str,payload:Confirm,current=Depends(user)):
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            # Replaying the SAME confirmed draft returns the original task IDs.
            prior=conn.execute('SELECT result FROM confirmations WHERE notice_id=? AND draft_version=?',(nid,payload.version)).fetchone()
            if prior:
                return {'task_ids':json.loads(prior['result']),'replayed':True}
            expect_version(record,payload.version)
            if record['draft_version']!=payload.version or not record['draft']:
                raise HTTPException(409,'请先生成或手工建立当前版本的草稿')
            from .notice_intake import require_open
            require_open(conn,nid)
            from .notice_resolution import require_confirmation
            quality_result=require_confirmation(json.loads(record['draft']),payload)
            sources=get_sources(conn,nid)
            problems=blockers(record,[s for s in sources if s['active']])
            if len(set(payload.replacements.values()))!=len(payload.replacements):
                raise HTTPException(422,'同一待办不可被多个草稿步骤同时替换')
            if any(i<0 or i>=len(payload.tasks) for i in payload.replacements):
                raise HTTPException(422,'更新映射不正确')
            ids=[]
            for i,task in enumerate(payload.tasks):
                try:
                    value=validate_task(task,sources,problems)
                except ValueError as exc:
                    raise HTTPException(422,str(exc)) from None
                now=int(time.time())
                if i in payload.replacements:
                    tid=payload.replacements[i]
                    old=own_task(conn,tid,current['id'])
                    if old['notice_id']!=nid:
                        raise HTTPException(422,'只可更新同一通知下的待办')
                    expect_version(old,payload.target_versions.get(tid))
                    previous_data=json.loads(old['data'])
                    for personal_field in ('notes','planned_at','reminder_at'):
                        value[personal_field]=previous_data.get(personal_field)
                    conn.execute('UPDATE tasks SET data=?,version=version+1,updated_at=? WHERE id=?',(dumps(value),now,tid))
                    reconcile_materials(conn, tid, value['materials'])
                    from .action_review import record_change
                    record_change(conn,current['id'],tid,previous_data,value,old['status'],old['status'])
                    audit(conn,current['id'],nid,'confirm_revision',before=json.loads(old['data']),after=value,task_id=tid)
                else:
                    tid=ident()
                    conn.execute('INSERT INTO tasks(id,user_id,notice_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',(tid,current['id'],nid,dumps(value),now,now))
                    audit(conn,current['id'],nid,'confirm_task',after=value,task_id=tid)
                ids.append(tid)
            if payload.plans:
                from .action_plans import apply_confirmed_plans
                apply_confirmed_plans(conn,current['id'],nid,ids,payload.plans,payload.replacements,int(time.time()))
            conn.execute('INSERT INTO confirmations VALUES(?,?,?)',(nid,payload.version,dumps(ids)))
            conn.execute("UPDATE notices SET status='confirmed',updated_at=? WHERE id=?",(int(time.time()),nid))
            audit(conn,current['id'],nid,'confirm_draft',before=json.loads(record['draft']),after={'task_ids':ids,'replacements':payload.replacements,'quality_resolution':payload.quality_resolution,'source_indices':payload.source_indices,'quality_result':quality_result})
        return {'task_ids':ids,'replayed':False}

    def list_tasks(conn,uid):
        items=[serialize_task(r) for r in conn.execute('SELECT t.*,n.title AS notice_title FROM tasks t JOIN notices n ON n.id=t.notice_id WHERE t.user_id=? ORDER BY t.updated_at DESC',(uid,))]
        attachments={}
        for row in conn.execute("SELECT s.id,s.notice_id,s.name,s.kind,s.status,length(s.content) AS size FROM sources s JOIN notices n ON s.notice_id=n.id WHERE n.user_id=? AND s.active=1 AND s.content IS NOT NULL ORDER BY s.created_at",(uid,)):
            attachments.setdefault(row['notice_id'],[]).append(dict(row))
        for item in items:item['attachments']=attachments.get(item['notice_id'],[])
        return enrich_tasks(conn, items)

    @app.get('/api/tasks')
    def tasks(current=Depends(user)):
        with db.connect() as conn:
            return list_tasks(conn,current['id'])

    from .insights import install as install_insights
    install_insights(app,db,user,admin,list_tasks)

    def update_task_record(conn,uid,tid,payload):
        old=own_task(conn,tid,uid)
        expect_version(old,payload.version)
        if payload.status == 'done' and old['status'] != 'done':
            from .action_review import require_reviewed
            require_reviewed(conn,tid)
            require_dependency_ready(conn, tid, uid)
        record=own_notice(conn,old['notice_id'],uid)
        sources=get_sources(conn,record['id'])
        try:
            previous=json.loads(old['data'])
            value=payload.data.model_dump()
            ai.check_evidence(payload.data.evidence+payload.data.deadline_evidence+(payload.data.scheduled.evidence if payload.data.scheduled else []),sources)
            critical=('scope','due_date','due_time','deadline_confirmed','planned_at','reminder_at','uncertainties','resolution_note','deadline_evidence','scheduled')
            if any(value[k]!=previous.get(k) for k in critical):
                value=validate_task(payload.data,sources,blockers(record,[s for s in sources if s['active']]),
                                    enforce_future=payload.data.reminder_at!=previous.get('reminder_at'))
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        conn.execute('UPDATE tasks SET data=?,status=?,version=version+1,updated_at=? WHERE id=?',(dumps(value),payload.status,int(time.time()),tid))
        reconcile_materials(conn, tid, value['materials'])
        from .action_review import record_change
        record_change(conn,uid,tid,previous,value,old['status'],payload.status)
        audit(conn,uid,old['notice_id'],'update_task',before={'data':json.loads(old['data']),'status':old['status']},
              after={'data':value,'status':payload.status,'reason':payload.reason},task_id=tid)
        return enrich_tasks(conn, [serialize_task(own_task(conn,tid,uid))])[0]


    db.agent_update_task = update_task_record
    db.agent_validate_task = validate_task

    @app.put('/api/tasks/{tid}')
    def update_task(tid:str,payload:TaskUpdate,current=Depends(user)):
        with db.connect(write=True) as conn:
            return update_task_record(conn,current['id'],tid,payload)

    from .task_board import install as install_task_board
    install_task_board(app,db,user,list_tasks,update_task_record)

    @app.get('/api/notices/{nid}/history')
    def history(nid:str,current=Depends(user)):
        with db.connect() as conn:
            own_notice(conn,nid,current['id'])
            return [dict(r) for r in conn.execute('SELECT * FROM audit WHERE notice_id=? ORDER BY id DESC LIMIT 300',(nid,))]

    @app.post('/api/calendar/export')
    def export_calendar(payload:CalendarRequest,current=Depends(user)):
        with db.connect(write=True) as conn:
            selected=[]
            for tid in dict.fromkeys(payload.task_ids):
                row=own_task(conn,tid,current['id'])
                expect_version(row,payload.versions.get(tid))
                task=serialize_task(row)
                if task['status']=='pending':
                    from .action_review import require_reviewed
                    require_reviewed(conn,tid)
                if task['status']!='cancelled':
                    from .action_plans import require_task_gates
                    require_task_gates(conn,tid)
                record=own_notice(conn,row['notice_id'],current['id'])
                problems=blockers(record,get_sources(conn,row['notice_id'],True))
                if problems and not task['data']['resolution_note']:
                    raise HTTPException(422,'通知材料尚未核对完整，请先核实本步骤的依据')
                selected.append(task)
            try:
                content=build_calendar(selected)
            except (ValueError,OverflowError) as exc:
                raise HTTPException(422,str(exc)) from None
            for task in selected:
                conn.execute('UPDATE tasks SET exported_version=version WHERE id=?',(task['id'],))
                audit(conn,current['id'],task['notice_id'],'calendar_export',after={'version':task['version'],'reminder_at':task['data']['reminder_at']},task_id=task['id'])
        return Response(content,media_type='text/calendar',headers={'Content-Disposition':'attachment; filename="campus-tasks.ics"'})

    @app.get('/api/export')
    def export_data(current=Depends(user)):
        with db.connect() as conn:
            records=[detailed_notice(conn,r['id'],current['id']) for r in conn.execute('SELECT id FROM notices WHERE user_id=?',(current['id'],)).fetchall()]
            history=[dict(r) for r in conn.execute('SELECT * FROM audit WHERE user_id=?',(current['id'],))]
            chats=[conversation_detail(conn,r['id'],current['id'],settings) for r in conn.execute('SELECT id FROM conversations WHERE user_id=?',(current['id'],)).fetchall()]
            catalog=[json.loads(r['data']) for r in conn.execute('SELECT data FROM source_catalog WHERE user_id=?',(current['id'],))]
            arrangements=[serialize_arrangement(r) for r in conn.execute('SELECT * FROM arrangements WHERE user_id=?',(current['id'],))]
            memory_projects=[dict(r) for r in conn.execute('SELECT * FROM memory_projects WHERE user_id=?',(current['id'],))]
            from .memory_store import export_archive
            memory_archive=export_archive(conn,current['id'])
            memories=memory_archive['memories']
        result={'format_version':1,'exported_at':datetime.now(CST).isoformat(),'profile':json.loads(current['profile']),
                'notices':records,'history':history,'conversations':chats,'source_catalog':catalog,'arrangements':arrangements,'memory_projects':memory_projects,'memories':memories,'memory_archive':memory_archive,'note':'含记忆来源与历史、原文提取文本、对话、待办和个人安排；二进制原件请从各通知或对话下载。日历副本需自行清理。'}
        return Response(dumps(result),media_type='application/json',headers={'Content-Disposition':'attachment; filename="campus-data.json"'})

    @app.delete('/api/notices/{nid}')
    def delete_notice(nid:str,payload:Version,current=Depends(user)):
        with db.connect(write=True) as conn:
            record=own_notice(conn,nid,current['id'])
            expect_version(record,payload.version)
            from .action_review import record_deletion
            record_deletion(conn,current['id'],nid)
            conn.execute('DELETE FROM notices WHERE id=?',(nid,))
        with db.connect() as conn:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return {'ok':True,'message':'通知、原件、草稿、待办及历史已删除；请自行删除外部日历副本。备份按保留期限清理。'}

    from .data_transfer import install_data_transfer
    install_data_transfer(app,db,user)
    from .notice_intake import install as install_intake
    install_intake(app,db,user,own_notice,expect_version,detailed_notice)
    install_workspace(app,db,settings,user,heavy_lock)
    from .memory import install_memory
    install_memory(app,db,user)
    install_integrations(app,db,settings,user,admin)
    install_speech(app,db,settings,user,heavy_lock)
    install_schedule(app,db,user)
    install_workflow(app, db, user, own_notice, own_task, expect_version, serialize_task,
                     get_sources, store_source, invalidate, validate_task, update_task_record)
    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT/'static'/'index.html')

    return app
