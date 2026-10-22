"""Additive storage and authenticated stream endpoints for declarative conversation UI."""
import asyncio
import json
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from typing import Literal

from . import genui_ai
from .ai import AIError
from .db import dumps
from .genui import CATALOG, LIMITS, parse_message, safe_value, matches
from .models import Strict
from .security import rate_limit
from .genui_state import validate_snapshots, submission_context
from .visual_evidence import display_citations


class Preferences(Strict):
    version: int = Field(ge=0)
    enabled: bool
    theme: Literal['light','dark','auto'] = 'light'


class Snapshots(Strict):
    version: int = Field(ge=0)
    snapshots: dict = Field(default_factory=dict)


def feature_settings(conn, uid, settings):
    preference=conn.execute('SELECT * FROM genui_preferences WHERE user_id=?',(uid,)).fetchone()
    return {'available':settings.genui_enabled,'enabled':settings.genui_enabled and (bool(preference['enabled']) if preference else True),
            'theme':preference['theme'] if preference else 'light','version':preference['version'] if preference else 0,
            'ai_label':settings.genui_ai_label,'debug':settings.genui_debug and not settings.production,
            'tier':genui_ai.choose_tier(settings),'capabilities':genui_ai.capabilities(settings),
            'limits':{**LIMITS,**settings.genui_limits}}


def readable(parts):
    """Rollback-friendly text, without running expressions on the server."""
    lines=[]
    def text(value):
        if value is None:return ''
        if isinstance(value,dict):
            if '$expr' in value:return '计算式：'+value['$expr']
            if '$bind' in value:return '可调参数：'+value['$bind']
            if '$ref' in value:return '数据引用：'+value['$ref']
            return json.dumps(value,ensure_ascii=False)
        return str(value)
    for part in parts:
        if part['kind']=='text':lines.append(part['text']);continue
        spec=part['spec'];seen=set()
        def visit(node_id):
            if node_id in seen:return
            seen.add(node_id);node=spec['nodes'].get(node_id)
            if not node:return
            p=node.get('props',{})
            for key in ('title','label','text','description','caption'):
                if p.get(key):lines.append(text(p[key]))
            if 'value' in p:lines.append(text(p['value'])+(' '+text(p['unit']) if p.get('unit') else ''))
            for key in ('items','rows','data','fields','options'):
                if isinstance(p.get(key),list):
                    lines.extend('- '+text(item) for item in p[key])
            for child in node.get('children',[]):visit(child)
        for node_id in spec['roots']:visit(node_id)
        if not spec['complete']:lines.append('（互动内容未完整接收，以上为已收到的部分。）')
    return '\n\n'.join(lines)


def message_parts(raw,tier,validated,limits,data):
    if tier==3 or tier==2 and not validated:
        return [{'kind':'text','text':raw}]
    try:
        return parse_message(raw,limits,data)
    except (ValueError,TypeError,KeyError,RecursionError):
        # A tightened deployment limit must never strand a processing message.
        return [{'kind':'text','text':raw or '互动内容未通过校验，请重新提问。'}]


def load_message(conn, item, settings):
    row=conn.execute('SELECT * FROM genui_messages WHERE message_id=?',(item['id'],)).fetchone()
    if not row or row['protocol_version']!=1:
        item['parts']=[{'kind':'text','text':item['content']}]
        return item
    try:
        data=safe_value(json.loads(row['trusted_data']),{**LIMITS,**settings.genui_limits})
        parts=message_parts(row['raw'],row['tier'],row['validated'],settings.genui_limits,data)
        if not row['validated']:
            for part in parts:
                if part['kind']=='ui':part['spec']['complete']=False
        snapshots=safe_value(json.loads(row['snapshots']),{**LIMITS,'depth':12})
    except (ValueError,TypeError,KeyError,RecursionError):
        parts=[{'kind':'text','text':item['content'] or '这条消息暂时无法恢复，请重试。'}];snapshots={};data={}
    item.update(parts=parts,genui={'v':1,'tier':row['tier'],'validated':bool(row['validated']),'snapshots':snapshots,'snapshot_version':row['snapshot_version'],'ai_label':row['ai_label'],'data':data})
    # Raw is owned conversation data, needed for exact stream/history equivalence, never sent in logs.
    item['genui']['raw']=row['raw']
    return item


def install_genui(app, db, settings, user, heavy_lock, prepare_send, own, changed, detail, send_type, preflight_steer=None):
    active={}
    workers=app.state.genui_workers=set()

    def cancel_active(cid):
        record=active.get(cid)
        if record:
            loop,task=record
            loop.call_soon_threadsafe(task.cancel)

    @app.get('/api/genui/preferences')
    def preferences(current=Depends(user)):
        with db.connect() as conn:return feature_settings(conn,current['id'],settings)

    @app.put('/api/genui/preferences')
    def update_preferences(payload:Preferences,current=Depends(user)):
        with db.connect(write=True) as conn:
            old=conn.execute('SELECT version FROM genui_preferences WHERE user_id=?',(current['id'],)).fetchone()
            if (old['version'] if old else 0)!=payload.version:raise HTTPException(409,'设置已在其他页面更新，请刷新后重试')
            conn.execute('INSERT INTO genui_preferences(user_id,enabled,theme,version) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,theme=excluded.theme,version=excluded.version',
                         (current['id'],int(payload.enabled),payload.theme,payload.version+1))
            return feature_settings(conn,current['id'],settings)

    @app.put('/api/conversations/{cid}/messages/{mid}/ui-state')
    def save_state(cid:str,mid:str,payload:Snapshots,current=Depends(user)):
        rate_limit(db,'genui-state:'+current['id'],60,60)
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'])
            row=conn.execute('SELECT g.*,m.status FROM genui_messages g JOIN conversation_messages m ON m.id=g.message_id WHERE m.id=? AND m.conversation_id=?',(mid,cid)).fetchone()
            if not row:raise HTTPException(404,'互动消息不存在')
            if row['snapshot_version']!=payload.version:raise HTTPException(409,'互动进度已在其他页面保存，请先刷新核对')
            if row['status']=='processing':raise HTTPException(409,'请等待本次回复结束后保存互动进度')
            try:
                parts=parse_message(row['raw'],settings.genui_limits,json.loads(row['trusted_data']))
                snapshots=validate_snapshots(payload.snapshots,parts)
            except (ValueError,TypeError,KeyError,RecursionError):raise HTTPException(422,'互动状态未通过校验，未覆盖已保存的进度') from None
            conn.execute('UPDATE genui_messages SET snapshots=?,snapshot_version=snapshot_version+1,updated_at=? WHERE message_id=?',(dumps(snapshots),int(time.time()),mid))
            return {'snapshot_version':payload.version+1,'snapshots':snapshots}

    async def stream(cid:str, payload:send_type, request:Request, current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            feature=feature_settings(conn,current['id'],settings)
            if payload.ui_context:
                try:submission_context(conn,cid,payload.ui_context)
                except (ValueError,TypeError,KeyError):raise HTTPException(422,'当前界面选择未通过检查，未中断原回复；请核对选择后重试') from None
        if payload.steer_message_id:
            if settings.ai_api_key and not payload.allow_external_processing:
                raise HTTPException(422,'补充消息需要允许发送至所配置的模型服务')
            if payload.retry_message_id or payload.regenerate_message_id or not payload.content.strip():
                raise HTTPException(422,'补充消息需要新的内容，不能同时重试或重新生成')
            interrupted=None
            with db.connect(write=True) as conn:
                live=own(conn,cid,current['id'])
                replay=conn.execute('SELECT 1 FROM conversation_messages WHERE conversation_id=? AND request_id=?',(cid,payload.request_id)).fetchone()
                if not replay:
                    latest=conn.execute("SELECT id,status FROM conversation_messages WHERE conversation_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",(cid,)).fetchone()
                    if not latest or latest['id']!=payload.steer_message_id:
                        raise HTTPException(409,'对话已经收到其他新消息，请刷新后再发送补充；你的草稿已保留')
                    if latest['status'] not in {'processing','complete'}:
                        raise HTTPException(409,'上一轮已停止或未完成，请刷新后核对状态与授权，再发送新消息；你的草稿已保留')
                    if preflight_steer:preflight_steer(cid,payload,current)
                    if latest['status']=='processing':
                        interrupted=active.get(cid)
                        conn.execute("UPDATE conversation_messages SET status='cancelled',error='已收到补充，按更新后的问题继续。' WHERE id=?",(latest['id'],))
                        conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,))
                        changed(conn,cid)
                    version=conn.execute('SELECT version FROM conversations WHERE id=?',(cid,)).fetchone()['version']
                    payload=payload.model_copy(update={'version':version})
            if interrupted:
                cancel_active(cid)
                # Release this request's model/summary work before starting its replacement.
                for _ in range(300):
                    if active.get(cid) is not interrupted:break
                    await asyncio.sleep(.01)
                else:raise HTTPException(409,'上一轮正在停止，请再次发送补充；草稿已保留')
        prepared,existing=prepare_send(cid,payload,current)
        def packet(kind,value,seq):return 'id: '+str(seq)+'\nevent: '+kind+'\ndata: '+dumps(value)+'\n\n'
        if existing is not None:
            async def replay():yield packet('done',{'conversation':existing,'replayed':True},1)
            return StreamingResponse(replay(),media_type='text/event-stream')
        token,mid,sources,messages=(prepared[k] for k in ('token','mid','sources','messages'))
        released=False
        def release_slot():
            nonlocal released
            if not released:
                released=True;heavy_lock.release()
        tier=feature['tier'] if feature['enabled'] else 3
        from .chat_media import resource_index
        trusted={'materials':[{'id':s['id'],'name':s['name'],'status':s['status']} for s in sources],'resources':resource_index(sources)}
        try:
            with db.connect(write=True) as conn:
                conn.execute('INSERT INTO genui_messages(message_id,trusted_data,tier,ai_label,updated_at) VALUES(?,?,?,?,?)',(mid,dumps(trusted),tier,settings.genui_ai_label,int(time.time())))
                initial=detail(conn,cid,current['id'],settings)
        except BaseException:
            try:
                with db.connect(write=True) as conn:
                    conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL,version=version+1 WHERE id=? AND processing_token=?',(cid,token))
                    conn.execute("UPDATE conversation_messages SET status='failed',error='本次处理未能启动，问题已保存，请重试。' WHERE id=? AND status='processing'",(mid,))
                    app.state.execution.finish(conn,mid,'failed','initialization_failed')
            finally:release_slot()
            raise

        async def generate():
            raw='';status='failed';error='回复已中断，已收到的内容已保留。';result=None;usage={};seq=0
            task=asyncio.current_task();active[cid]=(asyncio.get_running_loop(),task)
            try:
                seq+=1;yield packet('start',{'message_id':mid,'conversation':initial,'tier':tier,'data':trusted,'limits':feature['limits']},seq)
                from .grounding import events as grounded_events
                from .work_summary import stream as work_stream
                profile=json.loads(current['profile'])
                if not settings.ai_grounding:
                    from .memory_context import basic_profile
                    profile=basic_profile(db,current['id'],cid,mid,messages,profile,sources)
                stream_events=(work_stream(settings,db,mid,grounded_events(settings,db,current['id'],cid,mid,sources,messages,json.loads(current['profile']),tier))
                               if settings.ai_grounding else genui_ai.stream_reply(settings,sources,messages,profile,tier))
                from contextlib import aclosing
                async with asyncio.timeout(settings.ai_workflow_timeout), aclosing(stream_events):
                    async for event in stream_events:
                        if event['type']=='agent':
                            seq+=1;yield packet('agent',{'message_id':mid,'kind':event['kind'],'data':event['data'],'state':event['state']},seq)
                            continue
                        if event['type']=='phase':
                            from .execution import stage
                            with db.connect(write=True) as conn:stage(conn,mid,event['phase'])
                            if event.get('data'):
                                trusted.update(event['data'])
                                with db.connect(write=True) as conn:conn.execute('UPDATE genui_messages SET trusted_data=? WHERE message_id=?',(dumps(trusted),mid))
                            seq+=1;yield packet('phase',{'message_id':mid,'phase':event['phase'],'label':event['label'],'data':event.get('data'),'steps':event.get('steps',[])},seq)
                            continue
                        if event['type']=='work':
                            seq+=1;yield packet('work',{'message_id':mid,'steps':event['steps']},seq)
                            continue
                        if event['type']=='preview':
                            # This is transient text, never a saved, validated UI graph.
                            # Transport it as it arrives, not as a timed replay.
                            seq+=1;yield packet('preview',{'message_id':mid,'text':event['text'],'reset':bool(event.get('reset'))},seq)
                            continue
                        if event['type']=='delta':
                            if len((raw+event['text']).encode())>feature['limits']['messageBytes']:raise AIError('回复已达大小上限，已保留收到的部分。')
                            raw+=event['text']
                            # Persist before delivery, so cancellation cannot lose a chunk the user has seen.
                            with db.connect(write=True) as conn:
                                live=conn.execute('SELECT processing_token FROM conversations WHERE id=?',(cid,)).fetchone()
                                if not live or live['processing_token']!=token:raise asyncio.CancelledError()
                                conn.execute('UPDATE genui_messages SET raw=?,updated_at=? WHERE message_id=?',(raw,int(time.time()),mid))
                            seq+=1;yield packet('delta',{'message_id':mid,'text':event['text'],'expanded_template':event.get('expanded_template',False)},seq)
                        elif event['type']=='complete':
                            result=event['result'];usage=event.get('usage',{})
                            if event.get('sources'):
                                trusted['materials']=[{'id':s['id'],'name':s['name'],'status':s['status']} for s in event['sources']]
                if result is None:raise AIError('模型没有完整结束，已保留收到的部分。')
                if result['answer']!=raw:raise AIError('完整回复与已接收内容不一致，保留接收到的部分。')
                status='complete';error=''
            except asyncio.CancelledError:
                status='cancelled';error='已停止生成。已收到的内容保留，模型服务可能已计费。'
            except (AIError,TimeoutError) as exc:
                error=str(exc) or '模型连接超时，已保留收到的内容。'
            except Exception:
                # Never log provider content, message bodies or user profiles.
                error='回复处理出现异常，已收到的内容保留，请稍后重试。'
            finally:
                try:
                    with db.connect(write=True) as conn:
                        live=conn.execute('SELECT processing_token FROM conversations WHERE id=?',(cid,)).fetchone()
                        if live and live['processing_token']==token:
                            from .context_snapshot import publication_current,STALE_MESSAGE
                            if status=='complete' and not publication_current(conn,mid,current['id'],cid):
                                status='failed';error=STALE_MESSAGE;raw='';result=None
                            parts=message_parts(raw,tier,status=='complete',settings.genui_limits,trusted)
                            if status!='complete':
                                for part in parts:
                                    if part['kind']=='ui':part['spec']['complete']=False
                            citations=display_citations(result) if result and status=='complete' else []
                            conn.execute('UPDATE genui_messages SET raw=?,parts=?,validated=?,trusted_data=?,updated_at=? WHERE message_id=?',(raw,dumps(parts),int(status=='complete'),dumps(trusted),int(time.time()),mid))
                            conn.execute('UPDATE conversation_messages SET content=?,status=?,error=?,citations=?,input_tokens=?,output_tokens=? WHERE id=?',
                                         (readable(parts),status,error,dumps(citations),usage.get('input_tokens'),usage.get('output_tokens'),mid))
                            from .conversation_tools import select_reply
                            select_reply(conn,mid)
                            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
                            report_row=conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(mid,)).fetchone()
                            report=json.loads(report_row['report']) if report_row else {}
                            reason=(report.get('harness') or {}).get('stop_reason') or ('complete' if status=='complete' else 'request_failed')
                            app.state.execution.finish(conn,mid,'succeeded' if status=='complete' else status,reason)
                            from .memory_learning import completed_turn
                            completed_turn(conn,current['id'],cid,mid,result,status)
                        elif live:
                            # An explicit cancel wins. Recover the last delivered checkpoint only.
                            stored=conn.execute('SELECT raw FROM genui_messages WHERE message_id=?',(mid,)).fetchone()
                            message=conn.execute('SELECT status FROM conversation_messages WHERE id=?',(mid,)).fetchone()
                            if stored and message and message['status']=='cancelled':
                                parts=message_parts(stored['raw'],tier,False,settings.genui_limits,trusted)
                                conn.execute('UPDATE conversation_messages SET content=? WHERE id=?',(readable(parts),mid))
                            app.state.execution.finish(conn,mid,'cancelled' if message and message['status']=='cancelled' else 'discarded','superseded')
                finally:
                    if active.get(cid,(None,None))[1] is task:active.pop(cid,None)
                    release_slot()
            with db.connect() as conn:
                if conn.execute('SELECT 1 FROM conversations WHERE id=? AND user_id=?',(cid,current['id'])).fetchone():
                    final=detail(conn,cid,current['id'],settings)
                    seq+=1;yield packet('done',{'conversation':final},seq)
        from .stream_job import StreamJob
        def finalize_task(task):
            try:
                with db.connect(write=True) as conn:
                    abandoned=conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL,version=version+1 WHERE id=? AND processing_token=?',(cid,token)).rowcount
                    if abandoned:
                        conn.execute("UPDATE conversation_messages SET status='failed',error='本次处理已中断，问题与材料已保存，请重试。' WHERE id=? AND status='processing'",(mid,))
                        app.state.execution.finish(conn,mid,'cancelled' if task.cancelled() else 'failed','interrupted_request')
            finally:release_slot()
        job=StreamJob(generate(),workers,on_finish=finalize_task)
        return StreamingResponse(job.subscribe(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-cache'})

    app.post('/api/conversations/{cid}/messages/stream')(stream)
    return cancel_active
