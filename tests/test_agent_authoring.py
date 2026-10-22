"""The tool loop authors the existing chat answer, never bypassing publication."""
import asyncio
import json

import pytest

from app import grounding, genui_ai
from app.agent_runtime.authoring import extend_index, compile_answer
from app.agent_runtime.providers import stream_message
from app.agent_runtime.types import AgentError
from test_agent_chat import enabled, send, final, writer
from test_agent_runtime import Script, answer, call
from test_workflow import env, account
from test_workspace import conversation


def draft(text='你好，需要整理什么内容？', **kw):
    return answer(json.dumps({'answer':text, 'claims':[], **kw},ensure_ascii=False))


def forbid_writer(monkeypatch):
    writer(monkeypatch)
    async def forbidden(*args, **kwargs):
        raise AssertionError('Direct agent answer must not run another writer')
        yield
    monkeypatch.setattr(genui_ai, 'stream_reply', forbidden)


def test_direct_answer_uses_one_agent_call_and_existing_review(env, monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([draft()]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'你好'))
    assert m['status']=='complete',m['error']
    assert m['grounding']['route']=='agent_answer' and len(model.inputs)==1
    assert m['grounding']['status']=='checked' and m['genui']['validated']
    assert m['grounding']['work_summary']['verified']
    assert m['grounding']['work_summary']['tool_calls']==0


def test_tool_receipt_is_cited_by_same_agent_and_real_work_is_recorded(env, monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    def finish(messages, tools):
        result=json.loads(messages[-1]['content']);ref=result['evidence_index'][0]['ref']
        return draft(f'对话工作目录为空。[{ref}]',claims=[{'kind':'fact','text':'工作目录为空','evidence_refs':[ref]}])
    model=Script([answer('',[call('list_files')]),finish]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'请查看对话文件'))
    assert m['status']=='complete',m['error']
    assert len(model.inputs)==2 and 'research_complete' not in str(model.responses)
    assert m['grounding']['work_summary']['outcomes']==['列出 0 个对话文件']
    assert len(m['citations'])==1


def test_invalid_answer_feedback_returns_to_loop_without_fake_completion(env, monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([draft('虚构事实[E900]'),draft('当前没有足够依据。')]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'请整理'))
    assert m['status']=='complete',m['error']
    assert 'E900' in model.inputs[1][0][-1]['content']
    assert '虚构事实' not in m['content']


def test_native_authored_ui_not_old_compact_template(env, monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    ui={'state':{'checked':[]},'nodes':[{'id':'choice','type':'Checklist','props':{'label':'准备事项','bind':'checked','items':[{'id':'a','label':'核对原文'}]}}]}
    model=Script([draft('先核对原文，再准备材料。',ui=ui)]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'做一个可勾选的准备清单'))
    assert m['status']=='complete',m['error']
    assert 'Checklist' in m['grounding']['work_summary']['ui_components'] and m['genui']['validated']
    assert genui_ai.presentation_tier(1,'compact')==1
    assert genui_ai.presentation_tier(2,'compact')==2


def test_independent_rejection_cannot_publish_agent_draft(env, monkeypatch):
    c=account(env);chat=conversation(c);writer(monkeypatch,reject=True)
    model=Script([draft('应被拦截的内容')]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat))
    assert m['status']=='failed' and not m['genui']['validated']
    assert m['grounding']['status']=='not_published'


def test_evidence_refs_remain_stable_across_additional_searches():
    sources=[grounding.source('a','第一份',[{'locator':'段1','text':'原句A'}],'material')]
    entries=[];extend_index(entries,sources)
    first=dict(entries[0])
    sources.append(grounding.source('b','第二份',[{'locator':'段2','text':'原句B'}],'material'))
    extend_index(entries,list(reversed(sources)))
    assert entries[0]==first and len(entries)==2
    result=compile_answer(json.dumps({'answer':'原句A[E1]','claims':[{'kind':'fact','text':'原句A','evidence_refs':['E1']}]}),sources,entries)
    assert result['citations'][0]['source_id']=='a'


def test_stream_previews_only_answer_and_assembles_tool_arguments():
    class Response:
        async def aiter_bytes(self):
            packets=[{'choices':[{'delta':{'content':'{"answer":"你'}}]},
                     {'choices':[{'delta':{'content':'好"}','reasoning_content':'private'}}]},
                     {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c1','type':'function','function':{'name':'list_files','arguments':'{'}}]}}]},
                     {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'}'}}]},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':2}}]
            data=''.join('data: '+json.dumps(p,ensure_ascii=False)+'\n\n' for p in packets).encode()
            for i in range(0,len(data),7):yield data[i:i+7]
    text=[];result=asyncio.run(stream_message(Response(),text.append))
    assert ''.join(text)=='{"answer":"你好"}' and 'private' not in str(result)
    assert result['choices'][0]['message']['tool_calls'][0]['function']['arguments']=='{}'


def test_stream_does_not_accept_unfinished_calls():
    class Response:
        async def aiter_bytes(self):yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{"}}]}}]}\n\n'
    result=asyncio.run(stream_message(Response(),lambda _:None))
    assert result['choices'][0]['finish_reason'] is None  # Provider rejects before execution.


def test_serialized_presentation_gets_full_validation_and_effect_inputs_stay_strict():
    from pydantic import ValidationError
    from app.agent_runtime.chat import SubmitAnswer
    from app.agent_runtime.types import WriteFile
    ui={'state':{},'nodes':[{'id':'note','type':'Markdown','props':{'text':'测试'}}]}
    value=SubmitAnswer.model_validate({'answer':'测试','ui':json.dumps(ui)},strict=True)
    assert compile_answer(value.model_dump_json(),[],[])['answer'].endswith('```')
    assert SubmitAnswer.model_validate({'answer':'测试','ui':'null'},strict=True).ui is None
    for invalid in ('[]','true','{"nodes":[],"state":{}}'):
        with pytest.raises(ValidationError):SubmitAnswer.model_validate({'answer':'测试','ui':invalid},strict=True)
    ui['nodes'][0]['on']={'click':{'kind':'open_url','url':'javascript:alert(1)'}}
    with pytest.raises((ValueError,genui_ai.AIError)):
        compile_answer(SubmitAnswer.model_validate({'answer':'测试','ui':json.dumps(ui)}).model_dump_json(),[],[])
    with pytest.raises(ValidationError):WriteFile.model_validate({'path':'x.txt','content':123},strict=True)


def test_invalid_tool_feedback_identifies_field_without_echoing_content(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([answer('',[call('read_file',{'path':{'secret':'never-echo'}})]),draft()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'测试读取'))
    feedback=json.loads(model.inputs[1][0][-1]['content'])
    assert m['status']=='complete' and feedback['fields']==[{'path':'path','type':'string_type'}]
    assert 'never-echo' not in json.dumps(feedback)


def test_submit_preview_starts_before_tool_finish_and_never_streams_other_arguments():
    from app.genui_ai import AnswerDecoder
    decoder=AnswerDecoder();shown=[];checkpoints=[]
    def preview(delta):shown.append(decoder.push(delta))
    class Response:
        async def aiter_bytes(self):
            packets=[{'tool_calls':[{'index':0,'id':'c1','function':{'name':'submit_','arguments':'{"answer":"先'}}]},
                     {'tool_calls':[{'index':0,'function':{'name':'answer','arguments':'给结论"'}}]},
                     {'tool_calls':[{'index':1,'id':'c2','function':{'name':'write_file','arguments':'{"content":"PRIVATE"}'}}]},
                     {'tool_calls':[{'index':0,'function':{'arguments':',"ui":null}'}}]}]
            for delta in packets:
                yield ('data: '+json.dumps({'choices':[{'delta':delta}]},ensure_ascii=False)+'\n\n').encode()
                checkpoints.append(''.join(shown))
            yield b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    result=asyncio.run(stream_message(Response(),lambda _:None,preview))
    assert checkpoints[1]=='先给结论' and ''.join(shown)=='先给结论'
    assert result['choices'][0]['message']['tool_calls'][1]['function']['arguments']=='{"content":"PRIVATE"}'


def test_final_answer_cannot_share_batch_with_effectful_tool(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([answer('',[call('submit_answer',{'answer':'完成'}),call('write_file',{'path':'x.txt','content':'x'})])])
    env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'测试批次'))
    assert m['status']=='failed' and not m['content']
    assert not m.get('agent',{}).get('approvals')


def test_review_effort_tracks_derivation_not_presence_of_interface(env):
    source=grounding.source('s','说明',[{'locator':'p1','text':'准备两份材料'}],'material')
    simple={'answer':'先准备材料。','claims':[]}
    options=grounding.review_options(env[1],simple,[source])
    assert options['thinking']['type']=='disabled' and options['max_completion_tokens']<=2048
    calculation={**simple,'claims':[{'kind':'inference','text':'按已给数值计算'}]}
    assert grounding.review_options(env[1],calculation,[source])['thinking']['type']=='enabled'
    assert grounding.review_options(env[1],simple,[source]*3)['thinking']['type']=='enabled'


def test_committed_cancel_flag_wins_race_before_async_cancel_callback(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    def stop_before_next_guard(messages,tools):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute("UPDATE conversation_messages SET status='cancelled' WHERE conversation_id=? AND status='processing'",(chat['id'],))
        return answer('',[call('write_file',{'path':'never.txt','content':'not written'})])
    env[0].state.agent_service.provider_factory=lambda *_:Script([stop_before_next_guard])
    send(c,chat,'测试取消先发生的竞态')
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT status FROM agent_turns').fetchone()['status']=='cancelled'
        assert conn.execute('SELECT count(*) FROM agent_approvals').fetchone()[0]==0


def test_component_protocol_pages_whole_schemas_within_budget():
    from app.agent_runtime.authoring import capabilities,page_capabilities
    from app.agent_runtime.chat import SubmitAnswer
    from app.genui import CATALOG
    from app.db import dumps
    names=sorted(CATALOG['components'],key=lambda n:len(dumps(CATALOG['components'][n])),reverse=True)[:12]
    complete=capabilities(names)
    assert len(dumps(capabilities([])).encode())<9000
    page=page_capabilities(complete,9000)
    assert len(dumps(page).encode())<=9000 and page['deferred_components']
    for name,schema in page['components'].items():assert schema==complete['components'][name]
    assert set(page['components'])|set(page['deferred_components'])==set(complete['components'])
    with pytest.raises(ValueError):page_capabilities(complete,512)
    ui_schema=SubmitAnswer.model_json_schema()['properties']['ui']
    assert '$ref' in ui_schema and 'anyOf' not in ui_schema  # Optional object, no provider stringification hint.
