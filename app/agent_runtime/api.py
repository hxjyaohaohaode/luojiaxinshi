"""Authenticated persistent App Server: REST, replayable SSE and a small JSON-RPC API."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, ValidationError

from ..models import Strict
from .runtime import Service
from .sandbox import Files
from .store import ACTIVE
from .types import AgentError, ApprovalDecision, NewThread, StartTurn


class RPC(Strict):
    jsonrpc: str = Field(pattern=r'^2\.0$')
    id: str | int
    method: str = Field(max_length=100)
    params: dict = Field(default_factory=dict)


def install(app, db, settings, user, owner):
    service = Service(db, settings, owner)
    app.state.agent_service = service
    db.agent_service = service

    def enabled(current=Depends(user)):
        if not settings.agent_enabled:
            raise HTTPException(503, '智能任务已由维护者关闭')
        return current

    def detail(tid, uid):
        with db.connect() as conn:
            result = service.store.own(conn, tid, uid)
            result['turns'] = [dict(r) for r in conn.execute('SELECT * FROM agent_turns WHERE thread_id=? ORDER BY created_at,rowid', (tid,))]
            result['approvals'] = [{**dict(r), 'arguments': json.loads(r['arguments'])} for r in conn.execute("SELECT a.* FROM agent_approvals a JOIN agent_turns r ON r.id=a.turn_id WHERE r.thread_id=? AND a.status='pending'", (tid,))]
            return result

    def events(tid, uid, after):
        with db.connect() as conn:
            service.store.own(conn, tid, uid)
            rows = [{**dict(r), 'data': json.loads(r['data'])} for r in conn.execute('SELECT * FROM agent_events WHERE thread_id=? AND seq>? ORDER BY seq LIMIT 200', (tid, after))]
            return {'events': rows, 'next_cursor': rows[-1]['seq'] if rows else after}

    def create(uid, payload):
        try:
            for skill in payload.skills:
                service.skills.load(skill)
        except AgentError as exc:
            raise HTTPException(422, str(exc)) from None
        return service.store.create(uid, payload)

    @app.post('/api/conversations/{cid}/agent/approvals/{aid}')
    def chat_approval(cid: str, aid: str, payload: ApprovalDecision, current=Depends(enabled)):
        with db.connect() as conn:
            row = conn.execute('''SELECT r.thread_id FROM agent_approvals a JOIN agent_turns r ON r.id=a.turn_id
                JOIN agent_threads t ON t.id=r.thread_id JOIN conversation_messages m ON m.id=r.request_id
                JOIN conversations c ON c.id=t.conversation_id
                WHERE a.id=? AND c.id=? AND c.user_id=? AND m.conversation_id=c.id
                AND m.status='processing' AND c.processing_token IS NOT NULL''', (aid, cid, current['id'])).fetchone()
        if not row:
            raise HTTPException(409, '审批不属于当前正在执行的回复，未执行操作')
        return service.store.decide(current['id'], row['thread_id'], aid, payload)

    @app.post('/api/conversations/{cid}/agent/operations/{oid}/undo')
    def undo_operation(cid: str, oid: str, current=Depends(user)):
        from .workspace import undo
        with db.connect(write=True) as conn:
            return undo(conn, db, current['id'], cid, oid)

    @app.get('/api/agent/config')
    def configuration(current=Depends(enabled)):
        from .providers import completion_budget
        return {'skills': service.skills.metadata(), 'providers': {'mimo': bool(settings.ai_api_key), 'oss': bool(settings.agent_oss_model)},
                'mcp_servers': list(settings.agent_mcp_servers), 'sandbox_configured': bool(settings.agent_sandbox_image),
                'limits': {'steps': 12, 'children': 3, 'model_calls_per_turn': 24, 'context_bytes': settings.agent_context_bytes,
                           'mimo_context_tokens':settings.ai_context_tokens,'mimo_output_tokens':completion_budget(settings),
                           'mimo_input_bytes':min(settings.agent_context_bytes,max(512,settings.ai_context_tokens-completion_budget(settings))*2),
                           'oss_context_tokens':settings.agent_oss_context_tokens}}

    @app.get('/api/agent/threads')
    def threads(current=Depends(enabled)):
        with db.connect() as conn:
            return {'items': [dict(r) for r in conn.execute('SELECT id,title,conversation_id,created_at FROM agent_threads WHERE user_id=? ORDER BY created_at DESC,rowid DESC', (current['id'],))]}

    @app.post('/api/agent/threads')
    def new_thread(payload: NewThread, current=Depends(enabled)):
        return create(current['id'], payload)

    @app.get('/api/agent/threads/{tid}')
    def read_thread(tid: str, current=Depends(enabled)):
        return detail(tid, current['id'])

    @app.delete('/api/agent/threads/{tid}')
    def delete_thread(tid: str, current=Depends(enabled)):
        with db.connect(write=True) as conn:
            service.store.own(conn, tid, current['id'])
            if conn.execute("SELECT 1 FROM agent_turns WHERE thread_id=? AND status IN ('running','waiting_approval')", (tid,)).fetchone():
                raise HTTPException(409, '请先停止当前任务再删除')
            # Files remain under the owner's workspace for explicit local cleanup.
            # User-level deletion revokes API access immediately.
            conn.execute('DELETE FROM agent_threads WHERE id=?', (tid,))
        return {'deleted': True}

    @app.post('/api/agent/threads/{tid}/turns')
    async def start(tid: str, payload: StartTurn, current=Depends(enabled)):
        return service.submit(current['id'], tid, payload)

    @app.post('/api/agent/threads/{tid}/turns/{rid}/interrupt')
    async def interrupt(tid: str, rid: str, current=Depends(enabled)):
        # Cancelling asyncio tasks must run on the owning event-loop thread.
        return service.cancel(current['id'], tid, rid)

    @app.post('/api/agent/threads/{tid}/approvals/{aid}')
    def decide(tid: str, aid: str, payload: ApprovalDecision, current=Depends(enabled)):
        return service.store.decide(current['id'], tid, aid, payload)

    @app.get('/api/agent/threads/{tid}/events')
    def read_events(tid: str, after: int = Query(default=0, ge=0), current=Depends(enabled)):
        return events(tid, current['id'], after)

    @app.get('/api/agent/threads/{tid}/stream')
    async def stream(tid: str, request: Request, after: int = Query(default=0, ge=0), current=Depends(enabled)):
        try:
            after = max(after, int(request.headers.get('last-event-id', '0')))
        except ValueError:
            raise HTTPException(422, '事件游标无效') from None
        events(tid, current['id'], after)

        async def source():
            cursor, idle = after, 0
            while not await request.is_disconnected():
                with db.connect() as conn:
                    if not conn.execute('SELECT 1 FROM sessions WHERE token_hash=? AND user_id=? AND expires_at>?',
                                        (current['session_hash'], current['id'], int(time.time()))).fetchone():
                        return
                page = events(tid, current['id'], cursor)
                for item in page['events']:
                    cursor = item['seq']
                    yield 'id: ' + str(cursor) + '\ndata: ' + json.dumps(item, ensure_ascii=False) + '\n\n'
                with db.connect() as conn:
                    running = conn.execute("SELECT 1 FROM agent_turns WHERE thread_id=? AND status IN ('running','waiting_approval')", (tid,)).fetchone()
                if not running and len(page['events']) < 200:
                    return
                idle += 1
                if idle % 40 == 0:
                    yield ': keepalive\n\n'
                await asyncio.sleep(0.25)
        return StreamingResponse(source(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get('/api/agent/threads/{tid}/files')
    def files(tid: str, current=Depends(enabled)):
        with db.connect() as conn:
            service.store.own(conn, tid, current['id'])
        try:
            return {'items': Files(settings.data_dir, current['id'], tid).listing()}
        except AgentError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get('/api/agent/threads/{tid}/file')
    def download(tid: str, path: str = Query(min_length=1, max_length=240), current=Depends(enabled)):
        from fastapi import Response
        from urllib.parse import quote
        with db.connect() as conn:
            service.store.own(conn, tid, current['id'])
        try:
            content = Files(settings.data_dir, current['id'], tid).read(path)['content']
        except AgentError as exc:
            raise HTTPException(400, str(exc)) from None
        return Response(content, media_type='text/plain; charset=utf-8', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(Path(path).name)})

    @app.post('/api/agent/rpc')
    async def rpc(payload: RPC, current=Depends(enabled)):
        methods = {'initialize', 'thread/start', 'thread/read', 'turn/start', 'turn/interrupt', 'approval/respond', 'events/read'}
        try:
            p, method = payload.params, payload.method
            if method not in methods:
                return {'jsonrpc': '2.0', 'id': payload.id, 'error': {'code': -32601, 'message': '未知方法'}}
            if method == 'initialize':
                value = {'protocol': 'campus-agent/1', 'methods': sorted(methods), 'event_transport': 'sse', 'codex_wire_compatible': False}
            elif method == 'thread/start':
                value = create(current['id'], NewThread.model_validate(p))
            elif method == 'thread/read':
                value = detail(p['thread_id'], current['id'])
            elif method == 'turn/start':
                value = service.submit(current['id'], p['thread_id'], StartTurn.model_validate({k: v for k, v in p.items() if k != 'thread_id'}))
            elif method == 'turn/interrupt':
                value = service.cancel(current['id'], p['thread_id'], p['turn_id'])
            elif method == 'approval/respond':
                value = service.store.decide(current['id'], p['thread_id'], p['approval_id'], ApprovalDecision.model_validate({'digest': p['digest'], 'decision': p['decision']}))
            else:
                after = p.get('after', 0)
                if type(after) is not int or after < 0:
                    raise ValueError('cursor')
                value = events(p['thread_id'], current['id'], after)
            return {'jsonrpc': '2.0', 'id': payload.id, 'result': value}
        except (KeyError, ValueError, TypeError, ValidationError):
            return {'jsonrpc': '2.0', 'id': payload.id, 'error': {'code': -32602, 'message': '参数不符合要求'}}
        except HTTPException as exc:
            return {'jsonrpc': '2.0', 'id': payload.id, 'error': {'code': -32000, 'message': str(exc.detail), 'data': {'status': exc.status_code}}}
