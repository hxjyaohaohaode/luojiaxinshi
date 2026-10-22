"""Exercise the existing chat route end-to-end with synthetic model boundaries."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time

import pytest

from app import grounding, genui_ai
from app.db import dumps
from app.agent_runtime.sandbox import Files
from test_workflow import env, account
from test_workspace import conversation, material
from test_genui_transport import events, payload
from test_agent_runtime import Script, call, answer


def complete(**kw):
    return answer('', [call('research_complete', {'web_reason': '使用已提供资料', 'presentation': 'text', **kw})])


@pytest.fixture(autouse=True)
def enabled(env, monkeypatch):
    env[1].agent_enabled = env[1].ai_grounding = True
    env[1].ai_api_key = 'synthetic-no-network'
    async def forbidden(*args, **kwargs):
        raise AssertionError('Legacy planning or a real network boundary was used')
    monkeypatch.setattr(grounding, 'plan', forbidden)
    monkeypatch.setattr(grounding, 'completion', forbidden)
    monkeypatch.setattr(grounding, 'assess_coverage', forbidden)


def writer(monkeypatch, *, reject=False, seen=None):
    async def stream(settings, sources, messages, profile, tier):
        if seen is not None:
            seen.append({'sources': sources, 'profile': profile, 'messages': messages})
        source = next(s for s in sources if s['evidence_kind'] == 'user_input')
        part = source['sections'][0]
        value = {'answer': '你提供的要求是：' + part['text'] + '[1]',
                 'citations': [{'source_id': source['id'], 'locator': part['locator'], 'quote': part['text']}],
                 'image_sources': [], 'claims': [{'kind': 'fact', 'text': part['text'], 'citation_indices': [1]}]}
        yield {'type': 'complete', 'result': value, 'usage': {'input_tokens': 10, 'output_tokens': 10}}
    async def verify(settings, result, sources, question, context):
        checks = grounding.check_result(result, sources)
        return (['合成审查拒绝'] if reject else []), {}, checks
    monkeypatch.setattr(genui_ai, 'stream_reply', stream)
    monkeypatch.setattr(grounding, 'verify', verify)


def send(c, chat, text='请整理报名材料', **kw):
    return events(c.post(f"/api/conversations/{chat['id']}/messages/stream", json=payload(chat, content=text, **kw)))


def final(packets):
    return packets[-1]['data']['conversation']['messages'][-1]


def test_original_chat_runs_tools_then_the_existing_writer_and_reviewer(env, monkeypatch):
    c = account(env);chat = material(c, conversation(c), '报名需要成绩单和申请表。')
    model = Script([answer('', [call('campus_search', {'query': '报名', 'scopes': ['library']})]), complete()])
    env[0].state.agent_service.provider_factory = lambda *_: model
    seen = [];writer(monkeypatch, seen=seen)
    packets = send(c, chat);m = final(packets)
    assert m['status'] == 'complete', m['error']
    assert m['grounding']['planning_mode'] == 'agent_tool_loop'
    assert m['grounding']['agent_execution']['tool_calls'] == 2
    assert m['grounding']['harness']['call_count'] == 2  # Writer/reviewer are synthetic in this test.
    assert m['grounding']['status'] == 'checked' and m['genui']['validated']
    assert len(model.inputs) == 2 and any(s['id'] == chat['sources'][0]['id'] for s in seen[0]['sources'])
    assert any(p['type'] == 'agent' and p['data']['kind'] == 'tool.completed' for p in packets)
    assert any(step['stage'] == 'agent_tool' and step['state'] == 'complete' for step in m['grounding']['steps'])
    assert c.get('/api/conversations').json()[0]['id'] == chat['id']
    assert len(c.get('/api/conversations').json()) == 1
    assert c.get('/agent').status_code == 404
    assert 'agent-entry' not in c.get('/').text
    assert '报名需要成绩单' in json.dumps(model.inputs[1], ensure_ascii=False)


def test_ordinary_nonstreaming_chat_uses_same_agent(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch)
    model = Script([complete()]);env[0].state.agent_service.provider_factory = lambda *_: model
    result = c.post(f"/api/conversations/{chat['id']}/messages", json=payload(chat, content='你好'))
    assert result.status_code == 200
    assert result.json()['messages'][-1]['status'] == 'complete', result.text
    assert result.json()['messages'][-1]['grounding']['planning_mode'] == 'agent_tool_loop'


def test_final_review_cannot_be_bypassed_by_agent_completion(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch, reject=True)
    env[0].state.agent_service.provider_factory = lambda *_: Script([complete()])
    packets = send(c, chat);m = final(packets)
    assert m['status'] == 'failed' and not m['genui']['validated']
    assert not any(p['type'] == 'delta' for p in packets)
    assert m['grounding']['status'] == 'not_published'


def test_user_scope_and_account_isolation_apply_to_tools_and_children(env, monkeypatch):
    c = account(env);other = account(env, 'outsider')
    material(other, conversation(other), 'FOREIGN-SECRET-777')
    material(c, conversation(c), 'OWNER-PRIVATE-888')
    chat = conversation(c);writer(monkeypatch)
    model = Script([answer('', [call('campus_search', {'query': 'SECRET PRIVATE', 'scopes': ['library', 'schedule', 'profile']})]), complete()])
    env[0].state.agent_service.provider_factory = lambda *_: model
    m = final(send(c, chat, '只用本条消息提供的材料：报名事项。不要联网，不读取我的资料库和记忆。'))
    assert m['status'] == 'complete', m['error']
    raw = json.dumps(model.inputs, ensure_ascii=False)
    assert 'FOREIGN-SECRET-777' not in raw and 'OWNER-PRIVATE-888' not in raw
    assert all(t['function']['name'] != 'public_search' for t in model.inputs[0][1])


def wait_approval(c, cid):
    for _ in range(240):
        chat = c.get('/api/conversations/' + cid).json()
        current = chat['messages'][-1] if chat['messages'] else {}
        if current.get('agent', {}).get('approvals') if current.get('agent') else False:
            return chat, current['agent']['approvals'][0]
        if current.get('status') == 'failed':
            pytest.fail(current['error'])
        time.sleep(.025)
    pytest.fail('Existing chat did not expose its pending approval')


@pytest.mark.parametrize('decision', ['approve', 'deny'])
def test_inline_approval_refresh_owner_digest_and_actual_effect(env, monkeypatch, decision):
    c = account(env);outsider = account(env, 'outsider');chat = conversation(c);writer(monkeypatch)
    model = Script([answer('', [call('write_file', {'path': 'checklist.md', 'content': '# 原聊天草稿'})]), complete()])
    env[0].state.agent_service.provider_factory = lambda *_: model
    with ThreadPoolExecutor() as pool:
        job = pool.submit(send, c, chat, '请保存一个材料清单文件')
        current, approval = wait_approval(c, chat['id'])
        state = current['messages'][-1]['agent'];uid = c.get('/api/session').json()['user']['id']
        fs = Files(env[1].data_dir, uid, state['thread_id'])
        assert not fs.listing()
        endpoint = f"/api/conversations/{chat['id']}/agent/approvals/{approval['id']}"
        body = {'digest': approval['digest'], 'decision': decision}
        assert outsider.post(endpoint, json=body).status_code == 409
        assert c.post(endpoint, json={**body, 'digest': '0'*64}).status_code == 409
        assert c.get('/api/conversations/' + chat['id']).json()['messages'][-1]['agent']['approvals'][0]['id'] == approval['id']
        assert c.post(endpoint, json=body).status_code == 200
        assert c.post(endpoint, json=body).status_code == 409
        m = final(job.result(timeout=15))
    assert m['status'] == 'complete', m['error']
    assert bool(fs.listing()) == (decision == 'approve')
    assert bool(m['agent']['files']) == (decision == 'approve')
    if decision == 'approve':
        assert fs.read('checklist.md')['content'] == '# 原聊天草稿'


def test_cancel_original_chat_cancels_approval_and_prevents_write(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch)
    env[0].state.agent_service.provider_factory = lambda *_: Script([answer('', [call('write_file', {'path': 'never.md', 'content': 'cancelled'})])])
    with ThreadPoolExecutor() as pool:
        job = pool.submit(send, c, chat, '请保存草稿文件')
        current, approval = wait_approval(c, chat['id'])
        state = current['messages'][-1]['agent']
        response = c.post(f"/api/conversations/{chat['id']}/cancel", json={'version': current['version']})
        assert response.status_code == 200
        job.result(timeout=15)
    assert c.post(f"/api/conversations/{chat['id']}/agent/approvals/{approval['id']}", json={'digest': approval['digest'], 'decision': 'approve'}).status_code == 409
    uid = c.get('/api/session').json()['user']['id']
    assert not Files(env[1].data_dir, uid, state['thread_id']).listing()
    assert c.get('/api/conversations/' + chat['id']).json()['messages'][-1]['agent']['status'] == 'cancelled'


def test_subagents_share_real_evidence_with_chat_writer(env, monkeypatch):
    c = account(env);chat = material(c, conversation(c), '报名需要申请表。');seen=[];writer(monkeypatch, seen=seen)
    class Parallel:
        model = 'synthetic'
        root_step = 0
        child_running = 0
        peak = 0
        async def complete(self, messages, tools):
            child = not any(t['function']['name'] == 'spawn_agent' for t in tools)
            if child:
                if messages[-1]['role'] == 'tool':
                    result = answer('已核对工具返回原文。')
                else:
                    self.child_running += 1;self.peak = max(self.peak, self.child_running)
                    await asyncio.sleep(.05);self.child_running -= 1
                    result = answer('', [call('campus_search', {'query': '报名', 'scopes': ['library']})])
            else:
                self.root_step += 1
                if self.root_step == 1:
                    result = answer('', [call('spawn_agent', {'name': 'materials', 'task': '核对材料'}), call('spawn_agent', {'name': 'conditions', 'task': '核对条件'})])
                elif self.root_step == 2:
                    ids = [json.loads(m['content'])['agent_id'] for m in messages if m['role'] == 'tool' and 'agent_id' in json.loads(m['content'])]
                    result = answer('', [call('wait_agents', {'agent_ids': ids, 'timeout_seconds': 2})])
                else:result = complete()
            return result, {}
    model = Parallel();env[0].state.agent_service.provider_factory = lambda *_: model
    m = final(send(c, chat))
    assert m['status'] == 'complete', m['error']
    assert model.peak == 2 and m['grounding']['agent_execution']['subagents'] == 2
    assert chat['sources'][0]['id'] in {s['id'] for s in seen[0]['sources']}
    assert sum(step['stage'] == 'subagent' and step['state'] == 'complete' for step in m['grounding']['steps']) == 2


def test_duplicate_original_request_does_not_repeat_inference_or_tools(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch)
    model = Script([complete()]);env[0].state.agent_service.provider_factory = lambda *_: model
    body = payload(chat, content='你好')
    url = f"/api/conversations/{chat['id']}/messages/stream"
    assert final(events(c.post(url, json=body)))['status'] == 'complete'
    replay = events(c.post(url, json=body))
    assert len(replay) == 1 and replay[0]['data']['replayed'] and len(model.inputs) == 1


def test_mid_inference_context_change_blocks_all_tool_effects_and_publication(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch)
    def changed(messages, tools):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE conversations SET version=version+1 WHERE id=?', (chat['id'],))
        return complete()
    env[0].state.agent_service.provider_factory = lambda *_: Script([changed])
    packets = send(c, chat);m = final(packets)
    assert m['status'] == 'failed' and '已变化' in m['error']
    assert not any(e['type'] == 'delta' for e in packets)
    with env[0].state.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM agent_events WHERE type='tool.started'").fetchone()[0] == 0


def test_original_steering_stops_old_approval_and_runs_new_question(env, monkeypatch):
    c = account(env);chat = conversation(c);writer(monkeypatch)
    scripts = iter([Script([answer('', [call('write_file', {'path': 'old.md', 'content': 'old'})])]), Script([complete()])])
    env[0].state.agent_service.provider_factory = lambda *_: next(scripts)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(send, c, chat, '请保存清单')
        current, approval = wait_approval(c, chat['id']);mid=current['messages'][-1]['id']
        packets = send(c, current, '补充：先不要保存，仅回答这条补充。', steer_message_id=mid)
        first.result(timeout=15)
    assert final(packets)['status'] == 'complete', final(packets)['error']
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT status FROM agent_turns WHERE request_id=?', (mid,)).fetchone()[0] == 'cancelled'
    assert c.post(f"/api/conversations/{chat['id']}/agent/approvals/{approval['id']}", json={'digest': approval['digest'], 'decision': 'approve'}).status_code == 409


def test_public_search_feedback_registers_unique_sources_and_redacts_queries(env, monkeypatch):
    from app import evidence_web
    queries=[]
    async def search(settings, proposed, urls=None):
        queries.extend(proposed)
        number=len(queries)
        return [{**grounding.source('web-1', '官方页'+str(number), [{'locator':'原文','text':'公开报名办法'+str(number)}], 'web_page'),
                 'url': f'https://example.edu/p{number}'}], {'status':'searched','queries':proposed}, {'prompt_tokens':1}
    monkeypatch.setattr(evidence_web,'search',search)
    c=account(env);chat=conversation(c);seen=[];writer(monkeypatch,seen=seen)
    model=Script([answer('',[call('public_search',{'query':'公开报名办法 手机13800138000'}),call('public_search',{'query':'公开报名办法例外'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'请联网核对公开报名办法'))
    assert m['status']=='complete',m['error']
    assert len(queries)==2 and '13800138000' not in str(queries)
    web=[s for s in seen[0]['sources'] if s['evidence_kind']=='web_page']
    assert len(web)==2 and len({s['id'] for s in web})==2
    assert m['grounding']['web']['pages_read']==2


def test_read_source_pages_original_beyond_retrieval_excerpt(env, monkeypatch):
    c=account(env);chat=material(c,conversation(c),'报名材料：'+'甲'*6200+'分页末尾证据');writer(monkeypatch)
    source=chat['sources'][0]
    model=Script([answer('',[call('read_source',{'source_id':source['id'],'locator':source['sections'][0]['locator'],'offset':6100,'limit':400})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'请核对所附报名材料'))
    assert m['status']=='complete',m['error']
    feedback=[json.loads(v['content']) for v in model.inputs[1][0] if v['role']=='tool']
    assert any('分页末尾证据' in dumps(v) for v in feedback)


def test_tool_memory_is_bound_to_the_existing_context_snapshot(env, monkeypatch):
    from test_memory_context import memory
    c=account(env);chat=conversation(c);record=memory(c,content='PREFERENCE-SYNTHETIC 先列清单')
    seen=[];writer(monkeypatch,seen=seen)
    model=Script([answer('',[call('memory_recall',{'query':'PREFERENCE-SYNTHETIC 清单'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'按我的偏好整理清单'))
    assert m['status']=='complete',m['error']
    assert 'memory-'+record['id'] in m['grounding']['context_snapshot']['memory_ids']
    assert any(s.get('memory_id')==record['id'] for s in seen[0]['sources'])


def test_sdk_uses_original_chat_and_replays_verified_result(env, monkeypatch):
    import httpx
    from app.agent_runtime.sdk import Client
    c=account(env);chat=conversation(c);writer(monkeypatch)
    model=Script([complete()]);env[0].state.agent_service.provider_factory=lambda *_:model
    async def run():
        async with Client(env[1].origin,transport=httpx.ASGITransport(app=env[0])) as sdk:
            sdk.http.cookies.update(c.cookies)
            sdk.http.headers['X-CSRF-Token']=c.headers['X-CSRF-Token']
            return await sdk.conversation(chat['id']).run('你好',allow_external_processing=True)
    result=asyncio.run(run())
    assert result['status']=='complete' and result['conversation_id']==chat['id']
    assert result['grounding']['planning_mode']=='agent_tool_loop' and result['grounding']['status']=='checked'


def test_latest_full_length_input_survives_long_history_without_disabling_loop(env, monkeypatch):
    from app.db import ident
    c=account(env);chat=conversation(c);writer(monkeypatch)
    with env[0].state.db.connect(write=True) as conn:
        for _ in range(12):
            conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",
                         (ident(),chat['id'],'旧要求：'+'甲'*5500,int(time.time())-86400))
    model=Script([complete()]);env[0].state.agent_service.provider_factory=lambda *_:model
    text='当前要求：'+'乙'*5900+'最终条件不能丢失'
    m=final(send(c,chat,text))
    assert m['status']=='complete',m['error']
    assert model.inputs[0][0][-1]['content']==text
    assert m['grounding']['agent_execution']['compactions'][0]['omitted_messages']>0


def test_skills_load_on_demand_inside_existing_chat(env, monkeypatch):
    c=account(env);chat=conversation(c);writer(monkeypatch)
    model=Script([answer('',[call('load_skill',{'name':'notice-evidence'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'请核对通知原文'))
    assert m['status']=='complete',m['error']
    assert m['grounding']['agent_execution']['skills']==['notice-evidence']
    assert any(v['role']=='tool' and 'cannot_expand_permissions' in v['content'] for v in model.inputs[1][0])
