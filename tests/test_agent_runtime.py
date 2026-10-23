"""Real DB/HTTP/runtime tests with synthetic model responses; no paid requests."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

import httpx
import pytest

from app.agent_runtime.context import compact, size
from app.agent_runtime.mcp import MCP, validate_servers
from app.agent_runtime.providers import Provider, loopback_url
from app.agent_runtime.runtime import Service
from app.agent_runtime.sandbox import Files, command
from app.agent_runtime.skills import Skills
from app.agent_runtime.store import recover
from app.agent_runtime.types import AgentError
from app.backups import restore_database
from app.db import Database
from test_workflow import env, account
from test_workspace import conversation, material


def test_tool_result_budget_includes_nested_json_escaping():
    from app.agent_runtime.runtime import bounded_result
    from app.db import dumps
    result = {'records': [{'notes': '\\"\n\t\u0001中文' * 1000}]}
    bounded = bounded_result(result, 1600)
    assert bounded['truncated'] and size(dumps(bounded)) <= 1600
    assert bounded['excerpt']


@pytest.fixture(autouse=True)
def enable_runtime(env):
    env[1].agent_enabled = True


def call(name, args=None, cid=None):
    return {'id': cid or uuid.uuid4().hex, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args or {}, ensure_ascii=False)}}


def answer(text='工程夹具：任务完成', calls=None):
    return {'role': 'assistant', 'content': text, **({'tool_calls': calls} if calls else {})}


class Script:
    model = 'synthetic-no-network'

    def __init__(self, responses):
        self.responses = iter(responses)
        self.inputs = []

    async def complete(self, messages, tools):
        self.inputs.append((messages, tools))
        result = next(self.responses)
        if callable(result):
            result = result(messages, tools)
        if hasattr(result, '__await__'):
            result = await result
        return result, {'prompt_tokens': 12, 'completion_tokens': 6}


def setup(env, responses):
    c = account(env)
    provider = Script(responses)
    env[0].state.agent_service.provider_factory = lambda *_: provider
    return c, provider


def thread(c, **options):
    response = c.post('/api/agent/threads', json=options)
    assert response.status_code == 200, response.text
    return response.json()


def start(c, tid, prompt='核对资料', request_id=None):
    payload = {'prompt': prompt, 'request_id': request_id or uuid.uuid4().hex, 'allow_external_processing': True}
    response = c.post(f'/api/agent/threads/{tid}/turns', json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload


def wait(c, tid, *, approval=False):
    for _ in range(160):
        response = c.get(f'/api/agent/threads/{tid}')
        assert response.status_code == 200, response.text
        data = response.json()
        if approval and data['approvals'] or data['turns'][-1]['status'] not in {'running', 'waiting_approval'}:
            return data
        time.sleep(.025)
    pytest.fail('Synthetic task did not reach expected state')


def test_loop_retrieves_current_owned_material_and_preserves_original_workflow(env):
    c, model = setup(env, [answer('', [call('campus_search', {'query': '报名表'})]), answer()])
    other = account(env, 'bob')
    material(other, conversation(other), '另一个账号的秘密材料')
    chat = material(c, conversation(c), '本人须提交报名表。')
    with c:
        t = thread(c, conversation_id=chat['id'])
        run, request = start(c, t['id'])
        data = wait(c, t['id'])
        assert data['turns'][0]['status'] == 'completed', data
        serialized = json.dumps(model.inputs, ensure_ascii=False)
        assert '本人须提交报名表' in serialized
        assert '另一个账号的秘密材料' not in serialized
        assert len(model.inputs) == 2
        replay = c.post(f"/api/agent/threads/{t['id']}/turns", json=request)
        assert replay.json()['id'] == run['id'] and len(model.inputs) == 2
        assert c.get('/api/tasks').json() == []
        page = c.get(f"/api/agent/threads/{t['id']}/events").json()
        assert any(e['type'] == 'tool.completed' for e in page['events'])
        cursor = page['next_cursor']
        assert c.get(f"/api/agent/threads/{t['id']}/events?after={cursor}").json()['events'] == []
        streamed = c.get(f"/api/agent/threads/{t['id']}/stream", headers={'Last-Event-ID': str(cursor-1)})
        assert 'turn.completed' in streamed.text


def test_one_daily_task_can_complete_multiple_model_steps(env):
    env[1].ai_daily_limit=1
    c,model=setup(env,[answer('',[call('list_files')]),answer()])
    with c:
        t=thread(c)
        start(c,t['id'])
        result=wait(c,t['id'])
        assert result['turns'][-1]['status']=='completed' and len(model.inputs)==2
        again=c.post(f"/api/agent/threads/{t['id']}/turns",json={'prompt':'another task','request_id':uuid.uuid4().hex,'allow_external_processing':True})
        assert again.status_code==429 and '今日智能任务次数' in again.text


def test_owner_csrf_and_external_consent_cannot_be_bypassed(env):
    c, _ = setup(env, [])
    other = account(env, 'bob')
    t = thread(c)
    for endpoint in ('', '/events', '/files', '/stream'):
        assert other.get(f"/api/agent/threads/{t['id']}" + endpoint).status_code == 404
    assert other.post('/api/agent/threads', json={'conversation_id': t['conversation_id']}).status_code == 404
    response = c.post(f"/api/agent/threads/{t['id']}/turns", json={'prompt': '测试', 'request_id': uuid.uuid4().hex})
    assert response.status_code == 422
    assert c.post('/api/agent/threads', json={}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert c.post('/api/agent/threads', json={'user_id': 'forged'}).status_code == 422


@pytest.mark.parametrize('decision', ['approve', 'deny'])
def test_approval_is_exact_single_use_and_gates_file_side_effect(env, decision):
    c, model = setup(env, [answer('', [call('write_file', {'path': '清单.md', 'content': '工程材料清单'})]), answer()])
    other = account(env, 'bob')
    with c:
        t = thread(c)
        start(c, t['id'])
        data = wait(c, t['id'], approval=True)
        pending = data['approvals'][0]
        endpoint = f"/api/agent/threads/{t['id']}/approvals/{pending['id']}"
        assert c.get(f"/api/agent/threads/{t['id']}/files").json()['items'] == []
        assert other.post(endpoint, json={'digest': pending['digest'], 'decision': decision}).status_code == 404
        assert c.post(endpoint, json={'digest': '0'*64, 'decision': decision}).status_code == 409
        assert c.post(endpoint, json={'digest': pending['digest'], 'decision': decision}).status_code == 200
        assert c.post(endpoint, json={'digest': pending['digest'], 'decision': decision}).status_code == 409
        result = wait(c, t['id'])
        assert result['turns'][0]['status'] == 'completed', result
        files = c.get(f"/api/agent/threads/{t['id']}/files").json()['items']
        assert bool(files) == (decision == 'approve')
        if files:
            downloaded = c.get(f"/api/agent/threads/{t['id']}/file", params={'path': '清单.md'})
            assert downloaded.text == '工程材料清单'
        assert len(model.inputs) == 2


def test_noninteractive_policy_and_unknown_tool_are_feedback_without_host_execution(env):
    c, model = setup(env, [answer('', [call('write_file', {'path': '../secret', 'content': 'x'}), call('host_shell', {'cmd': 'whoami'})]), answer()])
    with c:
        t = thread(c, approval_policy='deny')
        start(c, t['id'])
        data = wait(c, t['id'])
        assert data['turns'][0]['status'] == 'completed'
        assert not data['approvals']
        assert '本会话禁止' in json.dumps(model.inputs, ensure_ascii=False)
        assert c.get(f"/api/agent/threads/{t['id']}/files").json()['items'] == []


def test_cancel_while_waiting_for_approval_is_durable_and_never_writes(env):
    c, model = setup(env, [answer('', [call('write_file', {'path': 'cancelled.md', 'content': 'x'})])])
    with c:
        t = thread(c)
        run, _ = start(c, t['id'])
        data = wait(c, t['id'], approval=True)
        assert c.post(f"/api/agent/threads/{t['id']}/turns/{run['id']}/interrupt").json()['cancelled']
        assert wait(c, t['id'])['turns'][0]['status'] == 'cancelled'
        pending = data['approvals'][0]
        assert c.post(f"/api/agent/threads/{t['id']}/approvals/{pending['id']}", json={'digest':pending['digest'],'decision':'approve'}).status_code == 409
        assert c.get(f"/api/agent/threads/{t['id']}/files").json()['items'] == []


def test_changed_material_discards_output_without_retry(env):
    c, model = setup(env, [])
    chat = material(c, conversation(c))
    def changed(*_):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE conversations SET version=version+1 WHERE id=?', (chat['id'],))
        return answer('过期回复不能发布')
    model.responses = iter([changed])
    with c:
        t = thread(c, conversation_id=chat['id'])
        start(c, t['id'])
        result = wait(c, t['id'])['turns'][0]
        assert result['status'] == 'failed' and result['answer'] == ''
        assert '变化' in result['error']
        assert json.loads(result['usage'])['model_calls'] == 1
        assert len(model.inputs) == 1


def test_parallel_children_have_bounded_permissions_and_share_budget(env):
    c, model = setup(env, [])
    async def respond(messages, tools):
        prompt = messages[-1].get('content', '')
        if messages[0]['content'].endswith('你是只读子任务，只完成分配的任务并给出证据和不确定性。'):
            assert 'spawn_agent' not in {t['function']['name'] for t in tools}
            assert 'write_file' not in {t['function']['name'] for t in tools}
            await asyncio.sleep(.03)
            return answer('子任务已完成核对')
        if len(messages) == 2:
            return answer('', [call('spawn_agent', {'name': 'dates', 'task': '核对期限'}), call('spawn_agent', {'name': 'materials', 'task': '核对材料'})])
        return answer('汇总两个子任务的结果')
    class Dynamic:
        model = 'synthetic'
        async def complete(self, messages, tools):
            return await respond(messages, tools), {'prompt_tokens':1,'completion_tokens':1}
    env[0].state.agent_service.provider_factory = lambda *_: Dynamic()
    with c:
        t = thread(c)
        start(c, t['id'])
        result = wait(c, t['id'])['turns'][0]
        assert result['status'] == 'completed', result
        events = c.get(f"/api/agent/threads/{t['id']}/events").json()['events']
        assert sum(e['type'] == 'agent.started' for e in events) == 2
        assert sum(e['type'] == 'agent.completed' for e in events) == 2
        assert json.loads(result['usage'])['model_calls'] <= 6


def test_identical_no_progress_loop_is_bounded(env):
    c, _ = setup(env, [answer('', [call('list_files')]) for _ in range(3)])
    with c:
        t = thread(c)
        start(c, t['id'])
        result = wait(c, t['id'])['turns'][0]
        assert result['status'] == 'failed' and '无进展' in result['error']


def test_recovery_marks_expired_runs_without_replaying_and_backup_roundtrip(env, tmp_path):
    c, _ = setup(env, [])
    t = thread(c)
    service = env[0].state.agent_service
    from app.agent_runtime.types import StartTurn
    _, row, _ = service.store.start(c.get('/api/session').json()['user']['id'], t['id'], StartTurn(prompt='恢复测试', request_id=uuid.uuid4().hex), 30)
    db = env[0].state.db
    backup = tmp_path/'backup.sqlite3'
    db.backup(backup)
    restored = tmp_path/'restored.sqlite3'
    restore_database(backup, restored)
    with Database(restored).connect() as conn:
        assert conn.execute('SELECT status FROM agent_turns').fetchone()[0] == 'interrupted'
    with db.connect(write=True) as conn:
        conn.execute('UPDATE execution_owners SET expires_at=0')
        assert recover(conn, int(time.time())) == 1
        assert recover(conn, int(time.time())) == 0
    assert c.get(f"/api/agent/threads/{t['id']}").json()['turns'][0]['status'] == 'interrupted'


def test_schema_version_fails_before_modification(env):
    db = env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute("UPDATE meta SET value='999' WHERE key='agent_schema_version'")
    with pytest.raises(RuntimeError, match='智能任务'):
        Database(db.path)


@pytest.mark.parametrize('name', ['../x','/etc/passwd','C:/Windows/a','a\\b','.env','a/../../x','x:stream','CON','folder/NUL.txt'])
def test_workspace_path_escape_and_reserved_names_are_rejected(tmp_path, name):
    files = Files(tmp_path, 'a'*32, 'b'*32)
    with pytest.raises(AgentError):
        files.write(name, 'test', '')


def test_workspace_atomic_version_checks_and_account_separation(tmp_path):
    a, b = Files(tmp_path, 'a'*32, 'b'*32), Files(tmp_path, 'c'*32, 'b'*32)
    saved = a.write('材料/清单.md', 'old', '')
    with pytest.raises(AgentError):
        a.write('材料/清单.md', 'bad', '')
    with pytest.raises(AgentError):
        b.read('材料/清单.md')
    a.write('材料/清单.md', 'new', saved['sha256'])
    with pytest.raises(AgentError):
        a.write('材料/清单.md', 'stale', saved['sha256'])
    assert a.read('材料/清单.md')['content'] == 'new'


def test_sandbox_has_no_unsandboxed_fallback(tmp_path):
    files = Files(tmp_path, 'a'*32, 'b'*32)
    with pytest.raises(AgentError, match='沙箱未配置'):
        asyncio.run(command(files, ['echo', 'hello'], ''))


def test_compaction_keeps_current_tool_pairs_and_does_not_mutate_history():
    history = [{'role':'user','content':'old'*1000} for _ in range(30)]
    current = [{'role':'user','content':'new'}, answer('',[call('list_files',cid='call-1')]), {'role':'tool','tool_call_id':'call-1','content':'[]'}]
    original = json.dumps(history)
    packed, report = compact('system', history, current, [], 8000)
    assert packed[-3:] == current and report['omitted_messages'] > 0
    assert size(packed) <= 8000 and json.dumps(history) == original
    with pytest.raises(AgentError):
        compact('system', [], [{'role':'user','content':'x'*9000}], [], 8000)


def test_skills_are_metadata_first_and_invalid_entries_not_loaded(tmp_path):
    folder = tmp_path/'notice';folder.mkdir()
    (folder/'SKILL.md').write_text('---\nname: notice\ndescription: Test skill\n---\nNo secrets.', encoding='utf-8')
    skill = Skills(tmp_path)
    assert skill.metadata() == [{'name':'notice','description':'Test skill'}]
    assert skill.load('notice') == 'No secrets.'
    with pytest.raises(AgentError):
        skill.load('../notice')


@pytest.mark.parametrize('url', ['https://example.com/v1','http://127.0.0.1.evil/v1','http://localhost@evil/v1','ftp://127.0.0.1/v1','http://127.0.0.1/v1?token=x'])
def test_oss_rejects_nonlocal_or_credential_urls(url):
    with pytest.raises(ValueError):
        loopback_url(url)


def test_oss_requires_explicit_model_and_never_uses_mimo_key(env):
    cfg = env[1]
    cfg.ai_api_key = 'synthetic-secret'
    with pytest.raises(AgentError):
        Provider(cfg, 'oss')
    cfg.agent_oss_model = 'local-test'
    provider = Provider(cfg, 'oss')
    assert provider.key == '' and provider.url == 'http://127.0.0.1:11434/v1'


def test_mcp_handshake_allowlist_session_and_error_handling():
    received = []
    def transport(request):
        body = json.loads(request.content);received.append((body, dict(request.headers)))
        method = body['method']
        if method == 'initialize':
            return httpx.Response(200, json={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':'2025-03-26'}}, headers={'Mcp-Session-Id':'fixture-session'})
        assert request.headers['Mcp-Session-Id'] == 'fixture-session'
        if method == 'notifications/initialized':
            return httpx.Response(202)
        result = {'tools':[{'name':'allowed'},{'name':'forbidden'}]} if method == 'tools/list' else {'content':[{'type':'text','text':'fixture result'}]}
        return httpx.Response(200, json={'jsonrpc':'2.0','id':body['id'],'result':result})
    config = validate_servers({'fixture':{'url':'http://127.0.0.1:9999/mcp','tools':['allowed']}})
    client = MCP(config, httpx.MockTransport(transport))
    assert asyncio.run(client.request('fixture','tools/list',{}))['tools'] == [{'name':'allowed'}]
    assert asyncio.run(client.request('fixture','tools/call',{'name':'allowed','arguments':{}}))['content'][0]['text'] == 'fixture result'
    count = len(received)
    with pytest.raises(AgentError):
        asyncio.run(client.request('fixture','tools/call',{'name':'forbidden','arguments':{}}))
    assert len(received) == count


def test_rpc_auth_contract_and_parameter_errors(env):
    c, _ = setup(env, [])
    init = c.post('/api/agent/rpc', json={'jsonrpc':'2.0','id':1,'method':'initialize'}).json()
    assert init['result']['protocol'] == 'campus-agent/1'
    assert not init['result']['codex_wire_compatible']
    missing = c.post('/api/agent/rpc', json={'jsonrpc':'2.0','id':2,'method':'turn/start'}).json()
    assert missing['error']['code'] == -32602
    unknown = c.post('/api/agent/rpc', json={'jsonrpc':'2.0','id':3,'method':'unknown'}).json()
    assert unknown['error']['code'] == -32601


def test_midturn_compaction_keeps_pairs_and_original_tool_outputs():
    current = [{'role':'user','content':'original task'}, answer('',[call('read_file',{'path':'old.md'},'c1')]),
               {'role':'tool','tool_call_id':'c1','content':'old result '*800},
               answer('',[call('read_file',{'path':'new.md'},'c2')]),
               {'role':'tool','tool_call_id':'c2','content':'latest result'}]
    packed, report = compact('system', [], current, [], 4000)
    assert report['compacted_tool_results'] == 1
    assert json.loads(packed[3]['content'])['context_compacted']
    assert packed[-2:] == current[-2:]
    assert current[2]['content'] == 'old result '*800


def test_subagent_message_delivery_and_forbidden_write_are_enforced(env):
    c, _ = setup(env, [])
    child_inputs = []
    class Coordinated:
        model = 'synthetic'
        async def complete(self, messages, tools):
            child = messages[0]['content'].endswith('你是只读子任务，只完成分配的任务并给出证据和不确定性。')
            if child:
                child_inputs.append(messages)
                if len(child_inputs) == 1:
                    await asyncio.sleep(.1)
                    result = answer('',[call('write_file',{'path':'forbidden.txt','content':'bad'})])
                else:
                    result = answer('已收到补充，只读核对完成')
            else:
                results = [json.loads(m['content']) for m in messages if m['role']=='tool']
                if not results:
                    result = answer('',[call('spawn_agent',{'name':'review','task':'只读核对'})])
                elif len(results)==1:
                    aid=results[0]['agent_id']
                    result=answer('',[call('send_message',{'agent_id':aid,'message':'补充要求：不得写入'}),call('wait_agents',{'agent_ids':[aid]})])
                else:
                    result=answer('协调完成')
            return result,{'prompt_tokens':1,'completion_tokens':1}
    env[0].state.agent_service.provider_factory=lambda *_:Coordinated()
    with c:
        t=thread(c);start(c,t['id']);result=wait(c,t['id'])
        assert result['turns'][0]['status']=='completed',result
        assert len(child_inputs)==2
        assert '补充要求：不得写入' in json.dumps(child_inputs[-1],ensure_ascii=False)
        assert '没有权限' in json.dumps(child_inputs[-1],ensure_ascii=False)
        assert not result['approvals']
        assert c.get(f"/api/agent/threads/{t['id']}/files").json()['items']==[]


def test_oss_protocol_never_sends_cloud_authorization(env,monkeypatch):
    cfg=env[1];cfg.ai_api_key='synthetic-secret';cfg.agent_oss_model='local-fixture'
    captured=[]
    def handle(request):
        captured.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'local result'}}],'usage':{'prompt_tokens':2,'completion_tokens':1}})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    response,usage=asyncio.run(Provider(cfg,'oss').complete([{'role':'user','content':'fixture'}],[]))
    assert response['content']=='local result' and usage['prompt_tokens']==2
    assert len(captured)==1 and 'authorization' not in captured[0].headers
    assert captured[0].url.host=='127.0.0.1'
    payload=json.loads(captured[0].content)
    assert payload['model']=='local-fixture' and 'thinking' not in payload


@pytest.mark.parametrize('streaming', [False, True])
def test_mimo_thinking_survives_tool_continuation_without_leaking_to_transcript(env, monkeypatch, streaming):
    cfg = env[1]
    cfg.ai_api_key = 'synthetic-secret'
    captured, previews = [], []
    private = 'private fixture reasoning'  # Synthetic, never a real model trace.
    tool = call('list_files', cid='thinking-test')
    def handle(request):
        captured.append(json.loads(request.content))
        first = len(captured) == 1
        msg = {'content': '' if first else 'Done', **({'tool_calls': [tool], 'reasoning_content': private} if first else {})}
        finish = 'tool_calls' if first else 'stop'
        usage = {'prompt_tokens': 20, 'completion_tokens': 12, 'completion_tokens_details': {'reasoning_tokens': 9}}
        if not streaming:
            return httpx.Response(200, json={'model': cfg.ai_model, 'choices': [{'finish_reason': finish, 'message': msg}], 'usage': usage})
        delta = {**msg, **({'tool_calls': [{'index': 0, **tool}]} if first else {})}
        packets = [{'model': cfg.ai_model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}, {'choices': [], 'usage': usage}]
        return httpx.Response(200, text=''.join('data: '+json.dumps(p)+'\n\n' for p in packets)+'data: [DONE]\n\n')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    async def run():
        provider = Provider(cfg, 'mimo')
        history = [{'role': 'user', 'content': 'Inspect this directory'}]
        async def request():
            return await provider.complete_stream(history, [], previews.append) if streaming else await provider.complete(history, [])
        first, usage = await request()
        assert 'reasoning_content' not in first
        assert usage['provider_model'] == cfg.ai_model
        assert usage['completion_tokens_details']['reasoning_tokens'] == 9
        history.extend([first, {'role': 'tool', 'tool_call_id': tool['id'], 'content': '{}'}])
        assert provider.reasoning_bytes(history) >= len(private)
        second, _ = await request()
        assert second['content'] == 'Done'
        assert private not in json.dumps(history) and private not in ''.join(previews)
        assert captured[1]['messages'][1]['reasoning_content'] == private
        assert all(p['thinking'] == {'type': 'enabled'} and 'temperature' not in p for p in captured)
        await provider.aclose()
        assert not provider._reasoning
    asyncio.run(run())


def test_workspace_rejects_hard_links_and_symbolic_links(tmp_path):
    import os
    files=Files(tmp_path,'a'*32,'b'*32)
    external=tmp_path/'external.txt';external.write_text('private',encoding='utf-8')
    os.link(external,files.root/'hard.txt')
    with pytest.raises(AgentError):files.read('hard.txt')
    try:os.symlink(external,files.root/'symbolic.txt')
    except OSError:return  # Windows without Developer Mode still tests hardlinks.
    with pytest.raises(AgentError):files.read('symbolic.txt')


def test_sdk_default_approval_refusal_and_replay_cursor():
    from app.agent_runtime.sdk import Client
    tid='a'*32;rid='b'*32;calls=[]
    stream=[{'seq':1,'turn_id':rid,'type':'approval.requested','data':{'id':'c'*32,'digest':'d'*64,'tool':'write_file','arguments':{'path':'x'}}},
            {'seq':2,'turn_id':rid,'type':'turn.completed','data':{'status':'completed','answer':'fixture','error':'','usage':{}}}]
    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/turns'):return httpx.Response(200,json={'id':rid})
        if request.url.path.endswith('/stream'):return httpx.Response(200,text=''.join('data: '+json.dumps(item)+'\n\n' for item in stream))
        return httpx.Response(200,json={'status':'deny'})
    async def run():
        async with Client(transport=httpx.MockTransport(handle)) as client:
            t=client.resume_thread(tid)
            value=await t.run('fixture',allow_external_processing=True)
            assert value['status']=='completed' and value['final_response']=='fixture'
            with pytest.raises(ValueError):client.resume_thread('../../auth/logout')
    asyncio.run(run())
    decision=next(json.loads(r.content) for r in calls if '/approvals/' in r.url.path)
    assert decision=={'digest':'d'*64,'decision':'deny'}


def test_mcp_sse_response_and_denied_redirect():
    def handle(request):
        payload=json.loads(request.content)
        if payload['method']=='initialize':return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':'2025-03-26'}})
        if 'id' not in payload:return httpx.Response(202)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: '+json.dumps({'jsonrpc':'2.0','id':payload['id'],'result':{'tools':[{'name':'lookup'}]}})+'\n\n')
    config={'test':{'url':'http://127.0.0.1/mcp','tools':['lookup']}}
    value=asyncio.run(MCP(config,httpx.MockTransport(handle)).request('test','tools/list',{}))
    assert value['tools']==[{'name':'lookup'}]
    with pytest.raises(AgentError,match='HTTP 302'):
        asyncio.run(MCP(config,httpx.MockTransport(lambda r:httpx.Response(302,headers={'Location':'https://example.com'}))).request('test','tools/list',{}))
