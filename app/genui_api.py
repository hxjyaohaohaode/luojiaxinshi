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
    return parse_message(raw,limits,data)


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


def validate_snapshots(snapshots, parts):
    if len(dumps(snapshots).encode())>131072:raise ValueError('snapshot_limit')
    snapshots=safe_value(snapshots,{**LIMITS,'depth':12})
    if len(snapshots)>LIMITS['blocks']:raise ValueError('snapshot_limit')
    def same_type(initial,value):
        if isinstance(initial,bool):return isinstance(value,bool)
        if isinstance(initial,(int,float)):return isinstance(value,(int,float)) and not isinstance(value,bool)
        if type(initial) is not type(value):return False
        if isinstance(initial,dict):return set(initial)==set(value) and all(same_type(initial[k],value[k]) for k in initial)
        return True
    for index,snapshot in snapshots.items():
        if not index.isdigit() or int(index)>=len(parts) or parts[int(index)]['kind']!='ui':raise ValueError('invalid_snapshot_block')
        if not isinstance(snapshot,dict) or set(snapshot)!={'state','view'}:raise ValueError('invalid_snapshot')
        spec=parts[int(index)]['spec'];state=snapshot['state'];view=snapshot['view']
        if not isinstance(state,dict) or not same_type(spec['state'],state):raise ValueError('snapshot_state_type')
        if not isinstance(view,dict) or set(view)-set(spec['nodes']):raise ValueError('snapshot_view_node')
        safe_value(state)
    return snapshots


def install_genui(app, db, settings, user, heavy_lock, prepare_send, own, changed, detail, send_type):
    active={}

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
        if not feature['enabled']:raise HTTPException(409,'互动回答已关闭，请使用文字对话')
        prepared,existing=prepare_send(cid,payload,current)
        def packet(kind,value,seq):return 'id: '+str(seq)+'\nevent: '+kind+'\ndata: '+dumps(value)+'\n\n'
        if existing is not None:
            async def replay():yield packet('done',{'conversation':existing,'replayed':True},1)
            return StreamingResponse(replay(),media_type='text/event-stream')
        token,mid,sources,messages=(prepared[k] for k in ('token','mid','sources','messages'))
        tier=feature['tier']
        trusted={'materials':[{'id':s['id'],'name':s['name'],'status':s['status']} for s in sources]}
        try:
            with db.connect(write=True) as conn:
                conn.execute('INSERT INTO genui_messages(message_id,trusted_data,tier,ai_label,updated_at) VALUES(?,?,?,?,?)',(mid,dumps(trusted),tier,settings.genui_ai_label,int(time.time())))
                initial=detail(conn,cid,current['id'],settings)
        except BaseException:
            heavy_lock.release()
            raise

        async def generate():
            raw='';status='failed';error='回复已中断，已收到的内容已保留。';result=None;usage={};seq=0
            task=asyncio.current_task();active[cid]=(asyncio.get_running_loop(),task)
            try:
                seq+=1;yield packet('start',{'message_id':mid,'conversation':initial,'tier':tier,'data':trusted,'limits':feature['limits']},seq)
                async with asyncio.timeout(settings.ai_timeout):
                    async for event in genui_ai.stream_reply(settings,sources,messages,json.loads(current['profile']),tier):
                        if event['type']=='delta':
                            if len((raw+event['text']).encode())>feature['limits']['messageBytes']:raise AIError('回复已达大小上限，已保留收到的部分。')
                            raw+=event['text']
                            # Persist before delivery, so cancellation cannot lose a chunk the user has seen.
                            with db.connect(write=True) as conn:
                                live=conn.execute('SELECT processing_token FROM conversations WHERE id=?',(cid,)).fetchone()
                                if not live or live['processing_token']!=token:raise asyncio.CancelledError()
                                conn.execute('UPDATE genui_messages SET raw=?,updated_at=? WHERE message_id=?',(raw,int(time.time()),mid))
                            seq+=1;yield packet('delta',{'message_id':mid,'text':event['text'],'expanded_template':event.get('expanded_template',False)},seq)
                        elif event['type']=='complete':result=event['result'];usage=event.get('usage',{})
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
                            parts=message_parts(raw,tier,status=='complete',settings.genui_limits,trusted)
                            if status!='complete':
                                for part in parts:
                                    if part['kind']=='ui':part['spec']['complete']=False
                            citations=(result['citations']+[{'source_id':sid,'locator':'图片','quote':'视觉理解结果，请对照图片核实'} for sid in result['image_sources']]) if result and status=='complete' else []
                            conn.execute('UPDATE genui_messages SET raw=?,parts=?,validated=?,updated_at=? WHERE message_id=?',(raw,dumps(parts),int(status=='complete'),int(time.time()),mid))
                            conn.execute('UPDATE conversation_messages SET content=?,status=?,error=?,citations=?,input_tokens=?,output_tokens=? WHERE id=?',
                                         (readable(parts),status,error,dumps(citations),usage.get('input_tokens'),usage.get('output_tokens'),mid))
                            conn.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL WHERE id=?',(cid,));changed(conn,cid)
                        elif live:
                            # An explicit cancel wins. Recover the last delivered checkpoint only.
                            stored=conn.execute('SELECT raw FROM genui_messages WHERE message_id=?',(mid,)).fetchone()
                            message=conn.execute('SELECT status FROM conversation_messages WHERE id=?',(mid,)).fetchone()
                            if stored and message and message['status']=='cancelled':
                                parts=message_parts(stored['raw'],tier,False,settings.genui_limits,trusted)
                                conn.execute('UPDATE conversation_messages SET content=? WHERE id=?',(readable(parts),mid))
                finally:
                    if active.get(cid,(None,None))[1] is task:active.pop(cid,None)
                    heavy_lock.release()
            with db.connect() as conn:
                if conn.execute('SELECT 1 FROM conversations WHERE id=? AND user_id=?',(cid,current['id'])).fetchone():
                    final=detail(conn,cid,current['id'],settings)
                    seq+=1;yield packet('done',{'conversation':final},seq)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

    app.post('/api/conversations/{cid}/messages/stream')(stream)
    return cancel_active
