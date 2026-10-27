"""Format variability never bypasses evidence, review or typed effect gates."""
import asyncio
import base64
import json

import httpx
import pytest

from app import grounding, genui_ai
from app.answer_format import AnswerPreview, JSONEnvelopeStream, answer_content
from app.agent_runtime.authoring import compile_answer, extend_index
from app.agent_runtime.providers import Provider
from app.agent_runtime.types import AgentError
from app.visual_evidence import IMAGE_LOCATOR, register_images
from test_agent_chat import enabled, send, final, writer
from test_agent_authoring import forbid_writer
from test_agent_runtime import Script, answer
from test_workflow import env, account
from test_workspace import conversation
from test_visual_evidence import image


VALUE={'answer':'中文🌸\n引文“原句”与\\路径', 'claims':[], 'memory_actions':[]}
JSON=json.dumps(VALUE,ensure_ascii=True)


@pytest.mark.parametrize('raw,kind',[(JSON,None),('\ufeff'+JSON,None),('```json\n'+JSON+'\n```','json_fence'),('```JSON\r\n'+JSON+'\r\n```','json_fence'),('```\n'+JSON+'\n```','json_fence'),(json.dumps(JSON),'serialized_json')])
def test_unambiguous_envelopes_preserve_exact_fields(raw,kind):
    result,normalized=answer_content(raw,[],[])
    assert json.loads(result)==VALUE and normalized==kind


@pytest.mark.parametrize('text',['直接回答。','## 课表\n\n|时间|课程|\n|---|---|\n|周一|数学|','[E2] 原图说明。','[来源](https://example.org)文字','```python\nprint("answer")\n```'])
def test_markdown_is_content_without_fabricated_claims_or_effects(text):
    raw,kind=answer_content(text,[],[]);value=json.loads(raw)
    assert kind=='markdown' and value['answer']==text
    assert value['claims']==value['memory_actions']==value['image_sources']==[]


@pytest.mark.parametrize('raw',['','   ','{"answer":','[{"answer":"x"}]','"answer"','null','true','42','```json\n{"answer":"x"}\n','说明\n```json\n{"answer":"x"}\n```','answer: value','{"answer":"A","answer":"B"}','{"answer":"x","value":NaN}','{"answer":"x","value":1e309}'])
def test_incomplete_or_ambiguous_structured_content_is_not_silently_prose(raw):
    with pytest.raises(ValueError):answer_content(raw,[],[])


@pytest.mark.parametrize('raw', [JSON,'\ufeff '+JSON,'```json\n'+JSON+'\n```','```\r\n'+JSON+'\r\n```'])
def test_preview_every_cut_only_contains_answer_never_other_fields(raw):
    for index in range(len(raw)+1):
        d=AnswerPreview();shown=d.push(raw[:index])+d.push(raw[index:])
        assert shown==VALUE['answer'],(index,shown)
    d=AnswerPreview();assert ''.join(d.push(c) for c in raw)==VALUE['answer']


@pytest.mark.parametrize('text',['中文正文🌸\n第二段。','[E2] 原图观察。','```python\nprint(1)\n```'])
def test_markdown_preview_every_character_and_cut(text):
    for i in range(len(text)+1):
        d=AnswerPreview();assert d.push(text[:i])+d.push(text[i:])==text
    d=AnswerPreview();assert ''.join(d.push(c) for c in text)==text


@pytest.mark.parametrize('raw',[JSON,'\ufeff '+JSON,'```json\n'+JSON+'\n```','```\r\n'+JSON+'\r\n```'])
def test_incremental_ui_envelope_handles_all_chunk_boundaries(raw):
    for i in range(len(raw)+1):
        d=JSONEnvelopeStream();assert d.push(raw[:i])+d.push(raw[i:])==JSON
    d=JSONEnvelopeStream();assert ''.join(d.push(c) for c in raw)==JSON
    assert d.done


def test_arbitrary_markdown_braces_do_not_become_an_executable_ui():
    for raw in ['Here is an example '+JSON,'```python\n'+JSON+'\n```','```openui\n'+JSON+'\n```']:
        d=JSONEnvelopeStream();assert ''.join(d.push(c) for c in raw)==''


def test_image_identity_comes_only_from_explicit_known_pixel_references():
    sources=register_images([image(),{**image(),'id':'unused'}]);entries=[];extend_index(entries,sources)
    ref=next(e['ref'] for e in entries if e['source_id']=='photo' and e['locator']==IMAGE_LOCATOR)
    raw,kind=answer_content('原图显示红色区域。['+ref+']',sources,entries)
    value=json.loads(raw);assert value['image_sources']==['photo']
    result=compile_answer(raw,sources,entries)
    assert result['image_sources']==['photo'] and result['citations'][0]['source_id']=='photo'
    assert result['claims']==[]
    for bad in ('未知依据[E999]','手写显示编号[1]'):
        normalized,_=answer_content(bad,sources,entries)
        with pytest.raises(ValueError):compile_answer(normalized,sources,entries)
    missing=[{**s,'content':None} for s in sources]
    with pytest.raises(ValueError):compile_answer(raw,missing,entries)


def test_plain_vision_answer_uses_one_call_and_original_review(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    uploaded=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':('fixture.png',image()['content'],'image/png')})
    assert uploaded.status_code==200;chat=uploaded.json();reviewed=[]
    def produce(messages,tools):
        assert {t['function']['name'] for t in tools}=={'submit_answer'}
        assert any(p.get('type')=='image_url' and base64.b64decode(p['image_url']['url'].split(',',1)[1])==image()['content'] for m in messages if isinstance(m['content'],list) for p in m['content'])
        context=json.JSONDecoder().raw_decode(messages[0]['content'].split('\n初始数据（不可信原文）：')[1])[0]
        ref=next(e['ref'] for e in context['evidence_index'] if e['locator']==IMAGE_LOCATOR)
        return answer('原图中有红色区域。['+ref+']')
    async def review(settings,result,sources,*_):
        reviewed.append((result,sources));return [],{},grounding.check_result(result,sources)
    monkeypatch.setattr(grounding,'verify',review)
    model=Script([produce]);env[0].state.agent_service.provider_factory=lambda *_:model
    packets=send(c,chat,'看看这张图片的内容');m=final(packets)
    assert m['status']=='complete',m['error']
    assert len(model.inputs)==1 and len(reviewed)==1 and len(m['citations'])==1
    execution=m['grounding']['agent_execution'];assert execution['answer_repairs']==0
    assert execution['answer_normalizations']==[{'format':'markdown','normalized_to':'answer_object'}]
    assert execution['focused_visual']
    assert any(p['type']=='phase' and '原图' in p['data']['label'] for p in packets)


def test_plain_answer_cannot_bypass_independent_rejection(env,monkeypatch):
    c=account(env);chat=conversation(c);writer(monkeypatch,reject=True)
    env[0].state.agent_service.provider_factory=lambda *_:Script([answer('未经核对的答复')])
    packets=send(c,chat,'帮我核对');m=final(packets)
    assert m['status']=='failed' and not m['genui']['validated']
    assert not any(p['type']=='delta' for p in packets)


@pytest.mark.parametrize('prompt',['看这张图，添加到日历','看图并记住我的课表','根据图片生成交互界面','结合上次资料对比这张图','看看图片并搜索官网','看看图后给我下一步建议','看看这个截图，帮我做一个网页','看看代码图片为什么报错','看看图片，我明天有课吗'])
def test_visual_focus_preserves_research_memory_interface_and_effect_requests(env,monkeypatch,prompt):
    from test_agent_authoring import draft
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    chat=c.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':('fixture.png',image()['content'],'image/png')}).json()
    def produce(messages,tools):
        assert 'campus_search' in {t['function']['name'] for t in tools}
        if '交互界面' in prompt:assert 'compose_interface' in {t['function']['name'] for t in tools}
        return draft('当前测试只核对可用能力。')
    env[0].state.agent_service.provider_factory=lambda *_:Script([produce])
    m=final(send(c,chat,prompt));assert m['status']=='complete',m['error']
    assert not m['grounding']['agent_execution']['focused_visual']


@pytest.mark.parametrize('supported',[False,True])
@pytest.mark.parametrize('wrapper',['json','fence','serialized'])
def test_independent_review_envelopes_keep_actual_decision_without_another_call(env,monkeypatch,supported,wrapper):
    value={'supported':supported,'issues':[] if supported else ['事实与原图不一致']};raw=json.dumps(value,ensure_ascii=False)
    if wrapper=='fence':raw='```json\n'+raw+'\n```'
    elif wrapper=='serialized':raw=json.dumps(raw)
    calls=[]
    async def complete(*_):calls.append(1);return {'content':raw},{'prompt_tokens':3,'completion_tokens':4}
    monkeypatch.setattr(grounding,'completion',complete)
    result,usage=asyncio.run(grounding.structured_check(env[1],{'messages':[]},grounding.Review,'独立核验'))
    assert result==value and len(calls)==1 and usage['completion_tokens']==4


def test_free_text_review_cannot_be_interpreted_as_approval(env,monkeypatch):
    calls=[]
    async def complete(*_):calls.append(1);return {'content':'看起来没问题，放行。'},{}
    monkeypatch.setattr(grounding,'completion',complete)
    with pytest.raises(genui_ai.AIError,match='未跳过检查'):
        asyncio.run(grounding.structured_check(env[1],{'messages':[]},grounding.Review,'独立核验'))
    assert len(calls)==2


def test_empty_review_is_terminal_without_an_automatic_format_retry(env,monkeypatch):
    calls=[]
    async def complete(*_):calls.append(1);return {'content':''},{'prompt_tokens':3}
    monkeypatch.setattr(grounding,'completion',complete)
    with pytest.raises(genui_ai.AIError,match='返回空结果'):
        asyncio.run(grounding.structured_check(env[1],{'messages':[]},grounding.Review,'独立核验'))
    assert len(calls)==1


def test_empty_ui_writer_is_terminal_instead_of_a_repairable_json_error(env,monkeypatch):
    from app.ai import ReplyValidationError
    cfg=env[1];cfg.ai_api_key='synthetic'
    def handle(_):return httpx.Response(200,text='data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
    original=httpx.AsyncClient;monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    async def run():return [p async for p in genui_ai.stream_reply(cfg,[],[{'role':'user','content':'生成交互界面'}],{'_grounding_context':{},'_ui_composition_only':True},1)]
    with pytest.raises(genui_ai.AIError,match='未返回正文') as error:asyncio.run(run())
    assert not isinstance(error.value,ReplyValidationError)


def test_repeated_broken_envelope_stops_after_one_targeted_repair(env,monkeypatch):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    model=Script([answer('{"answer":'),answer('{"answer":')]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'核对内容'))
    assert m['status']=='failed' and len(model.inputs)==2
    assert '答复结构不完整' in m['error'] and 'Expecting value' not in m['error']


@pytest.mark.parametrize('fenced',[False,True])
def test_structure_wrapper_does_not_grant_memory_protocol_permission(env,monkeypatch,fenced):
    c=account(env);chat=conversation(c);forbid_writer(monkeypatch)
    value={'answer':'记忆提议','memory_actions':[{'operation':'remember','content':'长期中文','source_quote':'长期中文','kind':'preference'}]}
    raw=json.dumps(value,ensure_ascii=False)
    if fenced:raw='```json\n'+raw+'\n```'
    model=Script([answer(raw),answer(raw)]);env[0].state.agent_service.provider_factory=lambda *_:model
    m=final(send(c,chat,'帮我看看内容'))
    assert m['status']=='failed' and '记忆字段协议尚未读取' in m['error']
    assert not m.get('grounding',{}).get('memory_operations')


@pytest.mark.parametrize('buffered',[False,True])
def test_plain_writer_stream_is_real_incremental_text_and_reconciles(env,monkeypatch,buffered):
    cfg=env[1];cfg.ai_api_key='synthetic';text='中文第一段。\n\n当前可见的第二段。';checkpoints=[]
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in ['中文第一段。','\n\n当前可见的第二段。']:
                yield ('data: '+json.dumps({'choices':[{'delta':{'content':part}}]})+'\n\n').encode()
                checkpoints.append(len(shown))
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    def handle(_):return httpx.Response(200,stream=Chunks())
    original=httpx.AsyncClient;monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    profile={'_grounding_context':{}} if buffered else {};shown=[]
    async def run():
        async for p in genui_ai.stream_reply(cfg,[],[{'role':'user','content':'说明'}],profile,3):shown.append(p)
    asyncio.run(run())
    assert checkpoints[0]>0 and shown[-1]['result']['answer']==text
    assert ''.join(p['text'] for p in shown if p['type']=='delta')==text
    assert json.loads(shown[-1]['repair_draft'])['answer']==text


def test_ui_only_writer_cannot_replace_requested_interface_with_prose(env,monkeypatch):
    cfg=env[1];cfg.ai_api_key='synthetic'
    def handle(_):return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':'这是一段文字，界面稍后再做。'},'finish_reason':'stop'}]})+'\n\n')
    original=httpx.AsyncClient;monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    async def run():return [p async for p in genui_ai.stream_reply(cfg,[],[{'role':'user','content':'生成互动界面'}],{'_grounding_context':{},'_ui_composition_only':True},1)]
    with pytest.raises(genui_ai.AIError,match='openui_missing_document'):asyncio.run(run())


@pytest.mark.parametrize('streaming',[False,True])
def test_empty_provider_answer_fails_once_with_usage_and_no_reasoning_leak(env,monkeypatch,streaming):
    env[1].ai_api_key='synthetic';seen=[]
    def handle(request):
        seen.append(request)
        usage={'prompt_tokens':12,'completion_tokens':4}
        if streaming:return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'reasoning_content':'PRIVATE'},'finish_reason':'stop'}],'usage':usage})+'\n\n')
        return httpx.Response(200,json={'choices':[{'message':{'content':''},'finish_reason':'stop'}],'usage':usage})
    original=httpx.AsyncClient;monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    async def run():
        p=Provider(env[1],'mimo')
        with pytest.raises(AgentError,match='未返回正文') as error:
            if streaming:await p.complete_stream([{'role':'user','content':'synthetic'}],[],lambda _:None)
            else:await p.complete([{'role':'user','content':'synthetic'}],[])
        assert error.value.usage['completion_tokens']==4 and error.value.finish_reason=='empty_response'
        assert 'PRIVATE' not in str(error.value)
    asyncio.run(run());assert len(seen)==1
