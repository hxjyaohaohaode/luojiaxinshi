"""Free-form UI, provider streaming and owner-scoped state; synthetic data only."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from app import genui_ai
from app.genui import parse_message
from app.genui_api import readable
from app.genui_prompt import encode_authored_ui
from app.openui import UIStreamDecoder, validate_ui
from app.genui_state import validate_snapshots
from test_workflow import env, account
from test_workspace import conversation
from test_genui_transport import events, payload

FIXTURE=Path(__file__).resolve().parent.parent/'fixtures/genui/openui-planner.json'
UI=json.loads(FIXTURE.read_text(encoding='utf-8'))


@pytest.mark.parametrize('escaped',[True,False])
def test_ui_really_streams_before_document_and_js_complete(escaped):
    ui={**UI,'title':'中文🌸工具','css':'p::after{content:"🌸\\n"}', 'html':['<p>中文🌸</p>','<p>后续段落</p>'],'jsFunctions':'','jsExpressions':[]}
    raw=json.dumps({'answer':'先看内容。','ui':ui},ensure_ascii=escaped)
    decoder=UIStreamDecoder();first=None;css_ready=None
    for i,char in enumerate(raw):
        packet=decoder.packet(char)
        if packet and packet.get('cssComplete'):css_ready=i
        if packet and packet.get('html') and first is None:first=i
    assert css_ready<first<raw.index('jsFunctions')<len(raw)-1
    assert decoder.content['html']==ui['html'] and decoder.content['css']==ui['css'] and decoder.content['title']==ui['title']
    assert decoder.content['htmlComplete']
    # Test every boundary, including key names, escapes and unicode pairs.
    for boundary in range(len(raw)+1):
        d=UIStreamDecoder();d.push(raw[:boundary]);d.push(raw[boundary:])
        assert d.content==decoder.content


def test_stream_decoder_ignores_strings_and_wrong_nested_paths():
    d=UIStreamDecoder();d.push(json.dumps({'answer':'\"ui\":{\"html\":[\"evil\"]}', 'untrusted':{'ui':UI},'ui':None}))
    assert not d.content['html']
    d=UIStreamDecoder(prefix=());d.push(json.dumps(UI));assert d.content['html']==UI['html']


def test_literal_css_unicode_escape_is_not_treated_as_a_json_surrogate():
    css='p{content:"\\uD800\\n🌸"}'
    d=UIStreamDecoder()
    for char in json.dumps({'ui':{**UI,'css':css}},ensure_ascii=True):d.push(char)
    assert d.content['css']==css


def test_local_code_only_releases_after_whole_ui_envelope_and_complete_scripts():
    raw=json.dumps({'ui':UI},ensure_ascii=False)
    decoder=UIStreamDecoder();packets=[]
    for char in raw:
        packet=decoder.packet(char)
        if packet:packets.append(packet)
    assert decoder.content['localReady'] and packets[-1]['localReady']
    functions=[p['jsFunctions'] for p in packets if 'jsFunctions' in p]
    assert functions==[UI['jsFunctions']]  # Never execute an unfinished function.
    assert [x['text'] for p in packets for x in p.get('jsExpressions',[])]==UI['jsExpressions']
    invalid=UIStreamDecoder();invalid.push(json.dumps({'ui':{**UI,'html':['<input>']}}))
    assert not invalid.content.get('localReady')


def test_reviewer_gets_all_original_ui_fields_without_nested_fence_escaping():
    from app.grounding import review_answer
    result={'answer':'简短导语。'+encode_authored_ui(UI),'claims':[],'citations':[]}
    audit=review_answer(result)
    assert audit['ui_documents']==[UI] and audit['answer'].strip()=='简短导语。'
    assert len(json.dumps(audit,ensure_ascii=False))<len(json.dumps(result,ensure_ascii=False))


def test_document_is_readable_and_native_inputs_have_real_contracts():
    parts=parse_message('开头。'+encode_authored_ui(UI))
    spec=parts[1]['spec'];assert spec['complete'] and not spec['errors']
    assert spec['state']['controls']=={'hours':'2','days':'7','filter':'all','form':False,'schedule':False,'original':False}
    assert spec['controls']['days']['label']=='准备天数'
    assert '材料准备' in readable(parts) and 'jsFunctions' not in readable(parts)
    assert not parse_message(encode_authored_ui(UI).removesuffix('```'))[1]['spec']['complete']


@pytest.mark.parametrize('change',[
    {'renderer':'raw_host_html'}, {'html':[]}, {'css':'x'*24001}, {'initialHeight':float('inf')},
    {'html':['<input id="x"><input id="x">']}, {'html':['<input>']}, {'jsExpressions':['x'*16001]},
    {'html':['<button onclick="fetch(1)">继续</button>']}, {'html':['<script>parent.x=1</script>']},
    {'html':['<input id="constructor">']}, {'html':['<input type="password" id="password">']},
])
def test_invalid_envelopes_never_become_executable(change):
    with pytest.raises(ValueError):validate_ui({**UI,**change})


def test_snapshots_only_accept_authored_controls_and_types():
    parts=parse_message(encode_authored_ui(UI));state=deepcopy(parts[1]['spec']['state']);state['controls']['days']='11'
    assert validate_snapshots({'1':{'state':state,'view':{}}},parts)['1']['state']['controls']['days']=='11'
    for bad in [{'controls':{'secret':'x'}},{'controls':{'form':'true'}},{'controls':{'filter':'invented'}}]:
        with pytest.raises(ValueError):validate_snapshots({'1':{'state':bad,'view':{}}},parts)


@pytest.mark.parametrize('envelope',['json','fence','bare_fence','serialized'])
def test_provider_stream_forwards_ui_fragments_before_final_json(env,monkeypatch,envelope):
    cfg=env[1];cfg.ai_api_key='synthetic';cfg.ai_grounding=False
    document={'answer':'合成验收示例。','ui':UI,'citations':[],'image_sources':[]}
    raw=json.dumps(document,ensure_ascii=False)
    if envelope=='fence':raw='```json\n'+raw+'\n```'
    elif envelope=='bare_fence':raw='```\n'+raw+'\n```'
    elif envelope=='serialized':raw=json.dumps(raw)
    chunks=[raw[i:i+83] for i in range(0,len(raw),83)]
    def transport(request):
        data=''.join('data: '+json.dumps({'choices':[{'delta':{'content':chunk}}]})+'\n\n' for chunk in chunks)
        data+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\n'
        return httpx.Response(200,content=data.encode())
    client=httpx.AsyncClient
    monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(transport),**kwargs))
    async def run():return [p async for p in genui_ai.stream_reply(cfg,[],[{'role':'user','content':'合成验收'}],{},1)]
    packets=asyncio.run(run());previews=[p for p in packets if p['type']=='ui_preview']
    if envelope!='serialized':assert len(previews)>10 and any(p['content'].get('html') for p in previews)
    else:assert not previews  # Cannot speculate about a second encoded layer.
    assert packets[-1]['type']=='complete'
    assert parse_message(packets[-1]['result']['answer'])[1]['spec']['sandbox']==UI


def test_stream_state_reload_followup_and_cross_account_rejection(env,monkeypatch):
    client=account(env);other=account(env,'other');chat=conversation(client)
    async def stream(*args):
        d=UIStreamDecoder();raw=json.dumps({'ui':UI},ensure_ascii=False)
        for offset in range(0,len(raw),71):
            packet=d.packet(raw[offset:offset+71])
            if packet:yield {'type':'ui_preview','content':packet}
        answer='合成验收示例。'+encode_authored_ui(UI)
        yield {'type':'delta','text':answer}
        yield {'type':'complete','result':{'answer':answer,'citations':[],'image_sources':[]},'usage':{}}
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    packets=events(client.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat)))
    assert packets[1]['type']=='ui_preview'
    final=packets[-1]['data']['conversation'];message=final['messages'][-1];assert message['genui']['validated']
    state=deepcopy(message['parts'][1]['spec']['state']);state['controls']['days']='12';state['controls']['form']=True
    endpoint=f"/api/conversations/{chat['id']}/messages/{message['id']}/ui-state"
    assert other.put(endpoint,json={'version':0,'snapshots':{'1':{'state':state,'view':{}}}}).status_code==404
    saved=client.put(endpoint,json={'version':0,'snapshots':{'1':{'state':state,'view':{}}}})
    assert saved.status_code==200,saved.text
    assert client.put(endpoint,json={'version':0,'snapshots':{}}).status_code==409
    loaded=client.get('/api/conversations/'+chat['id']).json()
    assert loaded['messages'][-1]['genui']['snapshots']['1']['state']==state
    context={'v':1,'message_id':message['id'],'snapshot_version':1,'blocks':{'1':{'inputs':state,'view':{}}}}
    response=client.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(loaded,content='按当前选择继续',ui_context=context))
    next_chat=events(response)[-1]['data']['conversation'];submitted=next_chat['messages'][-2]['interaction']
    choices={c['path']:c for c in submitted['selections']}
    assert choices['controls.days']['value']=='12' and choices['controls.days']['label']=='准备天数' and choices['controls.days']['changed']
    assert not choices['controls.hours']['changed']


def test_frame_csp_is_isolated_from_application(env):
    client=account(env)
    frame=client.get('/static/genui/sandbox.html');assert frame.status_code==200
    assert "sandbox allow-scripts" in frame.headers['content-security-policy']
    assert "connect-src 'none'" in frame.headers['content-security-policy']
    assert "allow-same-origin" not in frame.headers['content-security-policy']
    assert "'unsafe-inline'" not in client.get('/').headers['content-security-policy']


def test_dedicated_ui_writer_is_fast_model_with_no_effectful_tools(env,monkeypatch):
    from app import grounding
    from test_agent_runtime import Script,answer,call
    cfg=env[1];cfg.agent_enabled=cfg.ai_grounding=True;cfg.ai_api_key='synthetic'
    owner=account(env);chat=conversation(owner)
    main=Script([answer('',[call('compose_interface',{'brief':'生成可调整时间的试算工具'})])])
    env[0].state.agent_service.provider_factory=lambda *_:main
    requests=[];value={'answer':'合成验收工具。','ui':UI,'claims':[{'kind':'interface','text':'输入更新计算与筛选'}]}
    raw=json.dumps(value,ensure_ascii=False)
    def transport(request):
        requests.append(json.loads(request.content))
        body=''.join('data: '+json.dumps({'choices':[{'delta':{'content':raw[i:i+80]}}]})+'\n\n' for i in range(0,len(raw),80))
        body+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\n'
        return httpx.Response(200,content=body.encode())
    client=httpx.AsyncClient
    monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(transport),**kwargs))
    async def verify(settings,result,sources,*_):return [],{},grounding.check_result(result,sources)
    monkeypatch.setattr(grounding,'verify',verify)
    packets=events(owner.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat,content='用互动界面制作准备时间试算工具，每天2小时、7天。')))
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='complete',message['error']
    assert len(main.inputs)==1 and len(requests)==1
    assert requests[0]['model']==cfg.ai_ui_model and requests[0]['thinking']=={'type':'disabled'}
    assert 'tools' not in requests[0] and requests[0]['max_completion_tokens']==cfg.ai_output_tokens
    assert message['grounding']['models']['composition']==cfg.ai_ui_model
    assert message['grounding']['model_modes']['composition']=='disabled'
    assert message['grounding']['agent_execution']['model_calls']==2
    assert any(p['type']=='ui_preview' and p['data']['content'].get('localReady') for p in packets)


def test_ui_writer_preserves_append_only_tool_evidence_refs():
    sources=[{'id':'a','sections':[{'locator':'原文','text':'这是同一句原文。'}]}]
    entry={'ref':'E9','source_id':'a','locator':'原文','quote':'这是同一句原文。'}
    assert genui_ai.authoring_index(sources,{'_authoring_evidence_index':[entry]})==[entry]
    with pytest.raises(ValueError):genui_ai.authoring_index(sources,{'_authoring_evidence_index':[entry,entry]})


def test_ui_timeout_stops_generation_without_an_effectful_tool_retry(env,monkeypatch):
    from app import grounding
    from test_agent_runtime import Script,answer,call
    cfg=env[1];cfg.agent_enabled=cfg.ai_grounding=True;cfg.ai_api_key='synthetic'
    owner=account(env);chat=conversation(owner)
    main=Script([answer('',[call('compose_interface',{'brief':'生成计算工具'})])])
    env[0].state.agent_service.provider_factory=lambda *_:main
    async def timeout(*_):
        raise TimeoutError('synthetic model timeout')
        yield
    monkeypatch.setattr(genui_ai,'stream_reply',timeout)
    packets=events(owner.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload(chat,content='生成一个互动试算界面')))
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='failed' and '界面生成超时' in message['error']
    assert len(main.inputs)==1


def test_only_dedicated_ui_composition_can_use_the_fast_thinking_mode(env):
    cfg=env[1];messages=[{'role':'user','content':'制作一个界面'}]
    for tier in (1,2,3):assert genui_ai.payload(cfg,[],messages,{},tier)['thinking']['type']=='enabled'
    profile={'_ui_composition_only':True,'_grounding_context':{'interface_brief':'只做展示编排'}}
    assert genui_ai.payload(cfg,[],messages,profile,1)['thinking']['type']=='disabled'
    profile['_ui_composition_thinking']=True
    assert genui_ai.payload(cfg,[],messages,profile,1)['thinking']['type']=='enabled'
