"""Cross-reference integration checks at the original chat boundary."""
import json

import pytest

from app.agent_runtime.context import compact, initial_context, size
from app.agent_runtime.types import AgentError
from test_agent_authoring import draft, forbid_writer
from test_agent_chat import enabled, final, send, writer
from test_agent_runtime import Script, answer, call
from test_workflow import account, env
from test_workspace import conversation


def test_plain_text_agent_autonomously_uses_original_memory_protocol_and_receipts(env, monkeypatch):
    c = account(env); chat = conversation(c); forbid_writer(monkeypatch)
    quote = '我长期使用中文写作'
    def maintain(messages, tools):
        result = json.loads(messages[-1]['content'])
        assert result['memory_control']['may_propose']
        assert 'organize' in result['memory_actions_schema']['properties']['operation']['enum']
        assert '不必等用户说' in result['memory_policy']
        assert all(t['function']['name'] != 'submit_interface' for t in tools)
        return draft('后续写作按你的中文偏好处理。', memory_actions=[{
            'operation': 'remember', 'content': quote, 'source_quote': quote,
            'kind': 'preference', 'basis': 'explicit', 'lifetime': 'long_term'}])
    model = Script([answer('', [call('memory_capabilities')]), maintain])
    env[0].state.agent_service.provider_factory = lambda *_: model
    result = final(send(c, chat, quote+'。这次只用纯文字回答。'))
    assert result['status'] == 'complete', result['error']
    receipts = result['grounding']['memory_operations']
    assert any(r['status'] == 'accepted' for r in receipts), receipts
    from test_memory_engine import items
    assert any(row['content'] == quote for row in items(c))
    assert len(model.inputs) == 2 and result['grounding']['route'] == 'agent_answer'
    assert result['grounding']['agent_execution']['tool_calls'] == 1


@pytest.mark.parametrize('restricted', [True, False])
def test_memory_protocol_cannot_reenable_disabled_or_restricted_memory(env, monkeypatch, restricted):
    from test_memory_context import context
    c = account(env); chat = conversation(c); forbid_writer(monkeypatch)
    if not restricted: context(c, chat, memory_enabled=False)
    model = Script([answer('', [call('memory_capabilities')]), draft('只处理本次问题。')])
    env[0].state.agent_service.provider_factory = lambda *_: model
    result = final(send(c, chat, '只用本条消息，不读取记忆，纯文字。' if restricted else '你好，纯文字。'))
    assert result['status'] == 'complete', result['error']
    assert all(t['function']['name'] != 'memory_capabilities' for t in model.inputs[0][1])
    assert json.loads(model.inputs[1][0][-1]['content']).get('error')
    assert not result['grounding'].get('memory_operations')


def test_rejected_answer_never_commits_autonomous_memory_action(env, monkeypatch):
    c = account(env); chat = conversation(c); writer(monkeypatch, reject=True)
    model = Script([answer('', [call('memory_capabilities')]), draft('待核验', memory_actions=[{
        'operation': 'remember', 'content': '我长期使用中文写作', 'source_quote': '我长期使用中文写作',
        'kind': 'preference', 'lifetime': 'long_term'}])])
    env[0].state.agent_service.provider_factory = lambda *_: model
    result = final(send(c, chat, '请核对这段材料，纯文字。'))
    assert result['status'] == 'failed'
    assert not result['grounding'].get('memory_operations')


def test_context_retains_complete_loaded_protocols_while_reclaiming_evidence():
    protocol = json.dumps({'schema': '合法字段' * 600, 'last_property': 'expected_version'}, ensure_ascii=False)
    current = [{'role': 'user', 'content': '继续处理'},
        answer('', [call('memory_capabilities', cid='contract')]),
        {'role': 'tool', 'tool_call_id': 'contract', 'content': protocol},
        answer('', [call('campus_search', cid='data')]),
        {'role': 'tool', 'tool_call_id': 'data', 'content': '原文' * 8000 + '末尾仍有约束'},
        answer('', [call('read_source', cid='latest')]),
        {'role': 'tool', 'tool_call_id': 'latest', 'content': '最新原文'}]
    packed, stats = compact('规则', [], current, [], 14000, protected_tools={'memory_capabilities'})
    assert next(x['content'] for x in packed if x.get('tool_call_id') == 'contract') == protocol
    assert '末尾仍有约束' in next(x['content'] for x in packed if x.get('tool_call_id') == 'data')
    assert stats['compacted_tool_results'] == 1 and size(packed) <= 14000
    with pytest.raises(AgentError):
        compact('规则', [], current, [], 1800, protected_tools={'memory_capabilities'})


@pytest.mark.parametrize('budget',[1500,3000])
def test_large_initial_context_keeps_permissions_and_whole_evidence_with_explicit_omissions(budget):
    value = {'now': '2026-10-22', 'timezone': 'Asia/Shanghai', 'web_restricted': True,
        'memory_control': {'mode': 'auto', 'may_propose': True, 'working_version': 4},
        'working_memory': '工作记录' * 4000,
        'sources': [{'id': 'notice-1', 'name': '原通知'}], 'user_sources': [{'id': 'user-input'}],
        'evidence_index': [{'ref': 'E1', 'source_id': 'notice-1', 'quote': '太长的片段' * 2000},
                           {'ref': 'E2', 'source_id': 'notice-1', 'quote': '一条完整依据'}]}
    result = initial_context(value, budget)
    assert result['web_restricted'] and result['memory_control']['working_version'] == 4
    assert result['evidence_index'] == [value['evidence_index'][1]]
    assert result['deferred']['evidence_index']['omitted'] == 1
    assert 'working_memory' in result['deferred'] and size(result) <= budget


def test_long_term_memory_cannot_inherit_a_neighbouring_temporary_instruction():
    from app.agent_runtime.authoring import compile_answer
    quote = '我长期用中文写报告，所有项目都习惯先看结论再看依据。请用纯文字简短回复，不联网。'
    with pytest.raises(ValueError, match='长期记忆混入临时要求'):
        compile_answer(json.dumps({'answer':'已了解', 'memory_actions':[
            {'operation':'remember','kind':'preference','lifetime':'long_term',
             'content':quote,'source_quote':quote}]}),[],[])


def test_ui_discovery_receives_actual_private_media_without_an_extra_writer(env, monkeypatch):
    from test_chat_media import MP4
    c = account(env); outsider = account(env, 'media-outsider'); chat = conversation(c); forbid_writer(monkeypatch)
    response = c.post(f"/api/conversations/{chat['id']}/sources", data={'version': chat['version']},
                      files={'files': ('说明.mp4', MP4, 'video/mp4')})
    assert response.status_code == 200, response.text
    chat = response.json()
    observed = []
    def compose(messages, tools):
        result = json.loads(messages[-1]['content'])
        observed.append(result)
        resources = result['host_data']['resources']
        assert len(resources) == 1 and resources[0]['id'] == chat['sources'][0]['id']
        assert 'data:video' not in json.dumps(result)
        return answer('', [call('submit_interface', {'lead': '这是你上传的视频。', 'nodes': [
            {'id': 'clip', 'type': 'Video', 'props': {'src': {'$ref': 'resources.0.src'}, 'label': '上传的视频'}}]})])
    model = Script([answer('', [call('ui_capabilities', {'components': ['Video']})]), compose])
    env[0].state.agent_service.provider_factory = lambda *_: model
    result = final(send(c, chat, '在回复里放一个播放器，展示我上传的视频，无需分析视频。'))
    assert result['status'] == 'complete', (result['error'], [r.get('host_data') for r in observed],
        [json.loads(m['content']).get('error') for messages,_ in model.inputs for m in messages if m['role']=='tool'])
    assert result['genui']['validated'] and result['grounding']['route'] == 'agent_answer'
    assert 'Video' in result['grounding']['work_summary']['ui_components']
    path = observed[0]['host_data']['resources'][0]['src']
    assert c.get(path).content == MP4 and outsider.get(path).status_code == 404
