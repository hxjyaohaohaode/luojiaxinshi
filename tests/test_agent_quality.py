"""Counterexamples for completion, context loss and presentation repair."""
import asyncio
import json

import httpx
import pytest

from app.agent_runtime.authoring import compile_answer
from app.agent_runtime.context import compact, size
from app.agent_runtime.providers import Provider
from app.agent_runtime.runtime import Run
from app.agent_runtime.tools import compact_schema
from app.agent_runtime.types import AgentError
from app.ai import AIError
from app.work_summary import completed_work
from test_agent_authoring import forbid_writer
from test_agent_chat import enabled, send, final
from test_agent_runtime import Script, answer, call, setup, thread, start, wait
from test_workflow import env, account
from test_workspace import conversation


@pytest.mark.parametrize('child_fails', [False, True])
def test_final_submit_must_receive_child_result_even_if_it_finishes_during_parent_request(env, monkeypatch, child_fails):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    class Coordinated:
        model='synthetic'
        def __init__(self):self.root_calls=0;self.child_started=asyncio.Event();self.release=asyncio.Event()
        async def complete(self, messages, tools):
            child=not any(t['function']['name']=='submit_answer' for t in tools)
            if child:
                self.child_started.set();await self.release.wait()
                if child_fails:raise AgentError('合成读取失败')
                return answer('子任务核对结果：报名资格尚未说明'),{}
            self.root_calls+=1
            if self.root_calls==1:
                result=answer('',[call('spawn_agent',{'name':'eligibility','task':'核对资格缺口'})])
            elif self.root_calls==2:
                await self.child_started.wait();self.release.set()
                result=answer('',[call('submit_answer',{'answer':'不应发布的提前结论'})])
            else:
                text=json.dumps(messages,ensure_ascii=False)
                assert ('子任务未完成' if child_fails else '报名资格尚未说明') in text
                result=answer('',[call('submit_answer',{'answer':'资格信息尚不完整，请补充报名资格原文。'})])
            return result,{}
    model=Coordinated();env[0].state.agent_service.provider_factory=lambda *_:model
    result=final(send(c,chat,'测试任务，核对资格，不联网'))
    assert result['status']=='complete',result['error']
    assert model.root_calls==3 and '提前结论' not in result['content']
    states=result['grounding']['agent_execution']['subagent_results']
    assert states[0]['status']==('failed' if child_fails else 'completed')


def test_child_must_apply_message_arriving_during_final_model_request(env, monkeypatch):
    c,_=setup(env,[]);received=asyncio.Event();child_started=asyncio.Event();child_inputs=[]
    original=Run.execute_tool
    async def observe(self,name,args,child=False):
        result=await original(self,name,args,child)
        if name=='send_message':received.set()
        return result
    monkeypatch.setattr(Run,'execute_tool',observe)
    class Coordinated:
        model='synthetic'
        async def complete(self,messages,tools):
            child=not any(t['function']['name']=='spawn_agent' for t in tools)
            if child:
                child_inputs.append(messages)
                if len(child_inputs)==1:
                    child_started.set();await received.wait();return answer('旧结果不能直接结束'),{}
                assert '新增约束：仅核对课程截图' in json.dumps(messages,ensure_ascii=False)
                return answer('已按新增约束核对课程截图'),{}
            results=[json.loads(m['content']) for m in messages if m['role']=='tool']
            if not results:return answer('',[call('spawn_agent',{'name':'check','task':'只读核对'})]),{}
            if len(results)==1:
                await child_started.wait();aid=results[0]['agent_id']
                return answer('',[call('send_message',{'agent_id':aid,'message':'新增约束：仅核对课程截图'}),call('wait_agents',{'agent_ids':[aid]})]),{}
            assert '已按新增约束核对课程截图' in json.dumps(messages,ensure_ascii=False)
            return answer('核对完成'),{}
    env[0].state.agent_service.provider_factory=lambda *_:Coordinated()
    with c:
        t=thread(c);start(c,t['id']);result=wait(c,t['id'])
        assert result['turns'][0]['status']=='completed',result
    assert len(child_inputs)==2


def test_wait_wakes_on_first_completed_child_and_keeps_other_child_running():
    async def scenario():
        run=Run.__new__(Run);gate=asyncio.Event()
        async def quick():return
        async def slow():await gate.wait()
        run.agents={'a':{'task':asyncio.create_task(quick()),'status':'completed','name':'a','result':'ready'},
                    'b':{'task':asyncio.create_task(slow()),'status':'running','name':'b','result':''}}
        result=await asyncio.wait_for(run.wait_agents(['a','b'],30),.5)
        assert result[0]['result']=='ready' and not run.agents['b']['task'].done()
        gate.set();await run.agents['b']['task']
    asyncio.run(scenario())


def test_repeated_status_checks_do_not_cancel_a_still_running_child(env):
    c,_=setup(env,[])
    class Coordinated:
        model='synthetic'
        def __init__(self):self.release=asyncio.Event();self.count=0
        async def complete(self,messages,tools):
            if not any(t['function']['name']=='spawn_agent' for t in tools):
                await self.release.wait();return answer('子任务完成'),{}
            self.count+=1
            if self.count==1:return answer('',[call('spawn_agent',{'name':'check','task':'只读核对'})]),{}
            if self.count<=4:
                if self.count==4:self.release.set()
                return answer('',[call('list_agents')]),{}
            return answer('协调完成'),{}
    model=Coordinated();env[0].state.agent_service.provider_factory=lambda *_:model
    with c:
        t=thread(c);start(c,t['id']);result=wait(c,t['id'])
        assert result['turns'][0]['status']=='completed',result


def test_recent_long_turn_is_excerpted_without_substituting_older_turn():
    history=[{'role':'user','content':'过期的旧问题'}, {'role':'assistant','content':'过期的旧答案'},
             {'role':'user','content':'最新上下文'}, {'role':'assistant','content':'新答案开头'+('长内容'*2000)+'新答案末尾'}]
    before=json.dumps(history)
    packed,stats=compact('system',history,[{'role':'user','content':'继续刚才最新的答案'}],[],2600)
    text=json.dumps(packed,ensure_ascii=False)
    assert '最新上下文' in text and '新答案开头' in text and '新答案末尾' in text
    assert '过期的旧' not in text and '中间原文已省略' in text
    assert stats['compacted_history_messages']==1 and stats['omitted_messages']==2
    assert size(packed)+512<=2600 and json.dumps(history)==before


def test_history_drops_whole_turn_instead_of_orphaning_assistant():
    history=[{'role':'user','content':'old-'*2000},{'role':'assistant','content':'orphan'},
             {'role':'user','content':'recent request'},{'role':'assistant','content':'recent answer'}]
    packed,_=compact('system',history,[{'role':'user','content':'follow up'}],[],1600)
    assert 'orphan' not in json.dumps(packed)
    assert [m['content'] for m in packed if m['role']!='system']==['recent request','recent answer','follow up']


def test_tool_compaction_preserves_error_at_tail_and_call_pair():
    current=[{'role':'user','content':'check'}, answer('',[call('read_file',{'path':'a.txt'},'one')]),
             {'role':'tool','tool_call_id':'one','content':'start'+('x'*8000)+'END: permission denied'},
             answer('',[call('list_files',cid='two')]), {'role':'tool','tool_call_id':'two','content':'[]'}]
    packed,_=compact('system',[],current,[],2400)
    assert 'END: permission denied' in packed[3]['content']
    assert packed[2]['tool_calls'][0]['id']==packed[3]['tool_call_id']


def test_alternating_bad_final_arguments_stop_after_three_attempts(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([answer('',[call('submit_answer',{'answer':{'invalid':n}})]) for n in range(4)])
    env[0].state.agent_service.provider_factory=lambda *_:model
    result=final(send(c,chat,'仅作协议工程测试'))
    assert result['status']=='failed' and len(model.inputs)==3
    assert '三次' in result['error'] and not result['content']


def test_schema_optimization_preserves_real_title_field_and_constraints():
    schema={'title':'Display Title','type':'object','required':['title'],'additionalProperties':False,
            'properties':{'title':{'title':'Title','type':'string','minLength':1},
                          'metadata':{'default':{'title':'literal-value'},'type':'object'}}}
    compacted=compact_schema(schema)
    assert 'title' not in compacted and compacted['properties']['title']=={'type':'string','minLength':1}
    assert compacted['properties']['metadata']['default']['title']=='literal-value'
    assert compacted['required']==['title'] and compacted['additionalProperties'] is False


def test_connection_reuse_and_cost_details_preserve_provider_boundaries(env,monkeypatch):
    cfg=env[1];cfg.agent_oss_model='fixture';clients=[];requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'ok'}}],
            'usage':{'prompt_tokens':100,'completion_tokens':30,'prompt_tokens_details':{'cached_tokens':60,'private':'never-store'},
                     'completion_tokens_details':{'reasoning_tokens':8}}})
    original=httpx.AsyncClient
    def client(**kw):
        instance=original(**kw,transport=httpx.MockTransport(handle));clients.append(instance);return instance
    monkeypatch.setattr(httpx,'AsyncClient',client)
    async def scenario():
        provider=Provider(cfg,'oss');provider.reuse_connections=True
        for _ in range(2):
            _,usage=await provider.complete([{'role':'user','content':'fixture'}],[])
        assert usage['prompt_tokens_details']=={'cached_tokens':60}
        assert usage['completion_tokens_details']=={'reasoning_tokens':8}
        assert 'private' not in json.dumps(usage)
        await provider.aclose()
    asyncio.run(scenario())
    assert len(clients)==1 and clients[0].is_closed and len(requests)==2
    assert all('authorization' not in request.headers for request in requests)


def test_structural_ui_spelling_is_normalized_without_changing_content():
    node={'id':'group','type':'Section','props':{'children':[{'id':'body','type':'Markdown','props':{'text':'合成内容'}}]}}
    raw=json.dumps({'answer':'结果','ui':{'nodes':[node]}},ensure_ascii=False)
    changes=[];result=compile_answer(raw,[],[],normalization_log=changes)
    assert '合成内容' in result['answer'] and changes==[{'node':'group','field':'props.children','normalized_to':'children'}]
    assert 'children' in node['props']  # No mutation of the original model output.
    node['children']=[]
    with pytest.raises(ValueError,match='歧义'):compile_answer(json.dumps({'answer':'结果','ui':{'nodes':[node]}}),[],[])


def test_normalized_container_cannot_smuggle_an_unsafe_action():
    node={'id':'group','type':'Section','props':{'children':[{'id':'go','type':'Button','props':{'label':'测试'},
         'on':{'click':{'kind':'open_url','url':'javascript:alert(1)'}}}]}}
    with pytest.raises((ValueError,AIError)) as error:
        compile_answer(json.dumps({'answer':'结果','ui':{'nodes':[node]}}),[],[])
    assert '歧义' not in str(error.value)  # Reaches the original action safety boundary.


def test_work_highlights_reuse_only_checked_conclusions_and_keep_unknowns_separate():
    result={'answer':'测试','claims':[{'kind':'fact','text':'截止时间为 18:00 [E1]'},
            {'kind':'unknown','text':'报名资格尚未提供'},{'kind':'interface','text':'清单用于记录准备进度'}]}
    receipt=completed_work(result,{'status':'checked'},[])
    assert receipt['highlights']==['截止时间为 18:00','清单用于记录准备进度']
    assert receipt['gaps']==['报名资格尚未提供'] and not receipt['outcomes']
    assert not completed_work(result,{'status':'checking'},[])['highlights']


def test_interface_contract_is_discovered_lazily_and_uses_same_review(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    def first(messages,tools):
        assert 'submit_interface' not in [t['function']['name'] for t in tools]
        submit=next(t['function'] for t in tools if t['function']['name']=='submit_answer')
        assert 'ui' not in submit['parameters']['properties']
        return answer('',[call('ui_capabilities',{'components':['Checklist']})])
    def second(messages,tools):
        assert 'submit_interface' in [t['function']['name'] for t in tools]
        return answer('',[call('submit_interface',{'lead':'整理后的准备事项。','state':{'ready':[]},
            'nodes':[{'id':'list','type':'Checklist','props':{'bind':'ready','label':'准备事项','items':[{'id':'one','label':'核对原文'}]}}]})])
    model=Script([first,second]);env[0].state.agent_service.provider_factory=lambda *_:model
    result=final(send(c,chat,'生成可勾选的准备事项'))
    assert result['status']=='complete' and result['grounding']['status']=='checked',result['error']
    assert result['genui']['validated'] and 'Checklist' in result['grounding']['work_summary']['ui_components']
    assert len(model.inputs)==2 and result['grounding']['agent_execution']['answer_in_loop']


def test_interface_stream_only_previews_lead_never_nodes_or_actions():
    from app.genui_ai import AnswerDecoder
    from app.agent_runtime.providers import stream_message
    decoder=AnswerDecoder(fields=('lead',));shown=[]
    class Response:
        async def aiter_bytes(self):
            for fragment in ('{"lead":"正在','整理","nodes":[{"props":{"text":"PRIVATE-NODE"}}]}'):
                packet={'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':fragment},
                    **({'id':'ui1','function':{'name':'submit_interface','arguments':fragment}} if not shown else {})}]}}]}
                yield ('data: '+json.dumps(packet)+'\n\n').encode()
            yield b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    asyncio.run(stream_message(Response(),lambda _:None,lambda text:shown.append(decoder.push(text))))
    assert ''.join(shown)=='正在整理' and 'PRIVATE' not in ''.join(shown)


def test_native_claim_schema_has_one_stable_citation_protocol():
    from app.agent_runtime.chat import SubmitAnswer,SubmitInterface
    from pydantic import ValidationError
    for model in (SubmitAnswer,SubmitInterface):
        claim=model.model_json_schema()['$defs']['AgentClaim']
        assert set(claim['properties'])=={'kind','text','evidence_refs'}
    with pytest.raises(ValidationError):
        SubmitAnswer.model_validate({'answer':'测试','claims':[{'kind':'fact','text':'测试','citation_indices':[0]}]})


def test_identical_control_heading_deduplicates_without_removing_distinct_information():
    from app.agent_runtime.authoring import normalize_ui
    heading={'id':'heading','type':'Heading','props':{'text':'材料清单','level':3}}
    checklist={'id':'list','type':'Checklist','props':{'label':'材料清单','items':[]}}
    result,changes=normalize_ui({'nodes':[heading,checklist]})
    assert result['nodes']==[checklist] and changes[0]['field']=='duplicate_heading'
    heading['props']['text']='必交材料'
    assert len(normalize_ui({'nodes':[heading,checklist]})[0]['nodes'])==2
    heading['props']['text']='材料清单';heading['on']={'click':{'kind':'state','key':'x','value':True}}
    assert len(normalize_ui({'nodes':[heading,checklist]})[0]['nodes'])==2
