"""Regression coverage for real streaming, adaptive retrieval and UI host actions."""
import asyncio
import json

import httpx
import pytest

from app import genui_ai, grounding
from app.genui import validate_node
from test_workflow import env, account
from test_workspace import conversation, material
from test_genui_transport import events, payload
from test_grounding import mocks, answer


def test_grounded_adapter_yields_text_before_provider_finishes(env, monkeypatch):
    cfg = env[1]
    cfg.ai_api_key = 'synthetic-only'
    consumed = []
    parts = ['{"answer":"第一段', '，第二段","claims":[],"citations":[],"image_sources":[]}']

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index, content in enumerate(parts):
                consumed.append(index)
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': content}, 'finish_reason': None}]}) + '\n\n').encode()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

    client = httpx.AsyncClient
    monkeypatch.setattr(genui_ai.httpx, 'AsyncClient', lambda **kw: client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=Stream())), **kw))

    async def run():
        stream = genui_ai.stream_reply(cfg, [], [{'role': 'user', 'content': '测试文字流'}], {'_grounding_context': {'route': 'focused_text'}}, 3)
        first = await anext(stream)
        assert first == {'type': 'preview', 'text': '第一段'}
        assert consumed == [0], 'The provider was buffered until completion'
        rest = [event async for event in stream]
        assert rest[-1]['type'] == 'complete'
        assert rest[-1]['result']['answer'] == '第一段，第二段'
        assert ''.join(e['text'] for e in [first, *rest] if e['type'] == 'preview') == '第一段，第二段'
    asyncio.run(run())


def test_model_can_combine_coverage_but_preview_never_commits_unverified_result(env, monkeypatch):
    mocks(monkeypatch)
    env[1].ai_grounding = True
    env[1].ai_api_key = 'synthetic-only'
    c = account(env)
    chat = conversation(c)

    async def plan(*args):
        return {'local_queries': ['课表'], 'public_queries': [], 'web_reason': '当前课表查询', 'strategy': 'integrated', 'local_scopes': ['schedule']}, {}

    async def no_extra_coverage(*args):
        raise AssertionError('The model chose integrated coverage')

    async def stream(*args):
        yield {'type': 'preview', 'text': '正在组织的暂存文字'}
        yield {'type': 'complete', 'result': answer(), 'usage': {}}

    async def verify(*args):
        with env[0].state.db.connect() as conn:
            row = conn.execute("SELECT m.content,g.raw,g.validated FROM conversation_messages m JOIN genui_messages g ON g.message_id=m.id WHERE m.conversation_id=?", (chat['id'],)).fetchone()
        assert row['content'] == '' and row['raw'] == '' and not row['validated']
        return [], {}, ['独立检查仍然保留']

    monkeypatch.setattr(grounding, 'plan', plan)
    monkeypatch.setattr(grounding, 'assess_coverage', no_extra_coverage)
    monkeypatch.setattr(genui_ai, 'stream_reply', stream)
    monkeypatch.setattr(grounding, 'verify', verify)
    packets = events(c.post(f"/api/conversations/{chat['id']}/messages/stream", json=payload(chat)))
    preview_index = next(i for i, p in enumerate(packets) if p['type'] == 'preview')
    verified_index = next(i for i, p in enumerate(packets) if p['type'] == 'phase' and p['data']['phase'] == 'verifying')
    delta_index = next(i for i, p in enumerate(packets) if p['type'] == 'delta')
    assert preview_index < verified_index < delta_index
    final = packets[-1]['data']['conversation']['messages'][-1]
    assert final['status'] == 'complete' and final['content'] == answer()['answer']
    assert final['grounding']['planning_decisions'] == {'coverage': 'integrated_with_answer', 'local_scopes': ['schedule']}
    retrieval = next(p['data'] for p in packets if p['type'] == 'phase' and p['data']['phase'] == 'retrieving')
    assert '待办与日程' in retrieval['label'] and '个人档案' not in retrieval['label']


def test_model_scope_selection_never_reenables_user_denied_records(env):
    c = account(env)
    chat = material(c, conversation(c), '仅此账号附件')
    uid = c.get('/api/session').json()['user']['id']
    _, coverage = grounding.retrieve(env[0].state.db, uid, chat['id'], [],
        [{'role': 'user', 'content': '不要读取日程。查看资料。'}],
        {'_retrieval_scopes': ['schedule']}, ['课表'])
    assert coverage['access'] == {'library': False, 'schedule': False, 'profile': False, 'attachments': True}
    assert coverage['scanned']['materials'] == 0 and coverage['scanned']['arrangements'] == 0


def test_generated_upload_action_opens_host_flow_without_accepting_arbitrary_parameters():
    node = {'id': 'upload', 'type': 'Button', 'props': {'label': '上传课表'}, 'on': {'click': {'kind': 'host', 'name': 'upload_material', 'params': {}}}}
    validate_node(node)
    node['on']['click']['params'] = {'path': 'C:/private/file'}
    with pytest.raises(ValueError):
        validate_node(node)
