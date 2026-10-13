"""Authenticated streaming and history tests using recorded/synthetic model events only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import uuid

import httpx
import pytest

from app import genui_ai, chat_ai
from app.ai import AIError
from app.genui import parse_message
from app.genui_ai import AnswerDecoder,choose_tier
from app.genui_api import validate_snapshots
from test_workflow import env,account
from test_workspace import conversation,material

RAW=(Path(__file__).resolve().parent.parent/'fixtures/genui/study-plan.md').read_text(encoding='utf-8')


def payload(chat,**overrides):
    return {'version':chat['version'],'content':'安排每周准备时间（工程测试）','request_id':uuid.uuid4().hex,'allow_external_processing':True,**overrides}


def events(response):
    assert response.status_code==200,response.text
    packets=[]
    for frame in response.text.split('\n\n'):
        if not frame.strip():continue
        fields=dict(line.split(': ',1) for line in frame.split('\n') if ': ' in line)
        packets.append({'type':fields['event'],'seq':int(fields['id']),'data':json.loads(fields['data'])})
    return packets


async def recorded(*args):
    for index in range(0,len(RAW),23):yield {'type':'delta','text':RAW[index:index+23]}
    yield {'type':'complete','result':{'answer':RAW,'citations':[],'image_sources':[]},'usage':{'input_tokens':10,'output_tokens':30}}


def test_answer_decoder_every_character_cut_including_escapes_and_surrogates():
    for escaped in [True,False]:
        raw=json.dumps({'citations':[{'quote':'answer is data, not a key'}],'answer':'中文🌸\n"引用"与\\路径\t尾部','image_sources':[]},ensure_ascii=escaped)
        expected=json.loads(raw)['answer']
        for index in range(len(raw)+1):
            decoder=AnswerDecoder();assert decoder.push(raw[:index])+decoder.push(raw[index:])==expected,index
        decoder=AnswerDecoder();assert ''.join(decoder.push(c) for c in raw)==expected


def test_stream_persists_raw_parts_and_replays_idempotently(env,monkeypatch):
    c=account(env);env[1].ai_api_key='fixture';monkeypatch.setattr(genui_ai,'stream_reply',recorded);chat=material(c,conversation(c));body=payload(chat)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=body));assert [p['seq'] for p in packets]==list(range(1,len(packets)+1))
    assert packets[0]['type']=='start' and packets[-1]['type']=='done'
    assert ''.join(p['data']['text'] for p in packets if p['type']=='delta')==RAW
    final=packets[-1]['data']['conversation'];message=final['messages'][-1];assert message['status']=='complete' and message['genui']['validated']
    assert message['genui']['raw']==RAW and '```genui' not in message['content']
    assert message['parts']==parse_message(RAW,data=message['genui']['data'])
    assert c.get('/api/conversations/'+chat['id']).json()==final
    replay=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=body));assert len(replay)==1 and replay[0]['data']['replayed']
    with env[0].state.db.connect() as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]=='4'
        record=db.execute('SELECT * FROM genui_messages').fetchone();assert json.loads(record['parts'])==message['parts'] and record['raw']==RAW


def test_snapshot_owner_isolation_cas_types_and_prototype_defense(env,monkeypatch):
    c=account(env);other=account(env,'other');monkeypatch.setattr(genui_ai,'stream_reply',recorded);chat=conversation(c)
    final=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation'];m=final['messages'][-1]
    index=next(i for i,p in enumerate(m['parts']) if p['kind']=='ui');spec=m['parts'][index]['spec'];state={**spec['state'],'hours':4}
    body={'version':0,'snapshots':{str(index):{'state':state,'view':{}}}};url=f"/api/conversations/{chat['id']}/messages/{m['id']}/ui-state"
    assert other.put(url,json=body).status_code==404
    saved=c.put(url,json=body);assert saved.status_code==200,saved.text
    assert c.put(url,json=body).status_code==409
    loaded=c.get('/api/conversations/'+chat['id']).json()['messages'][-1];assert loaded['genui']['snapshots'][str(index)]['state']['hours']==4
    body['version']=1;body['snapshots'][str(index)]['state']['hours']='not-number';assert c.put(url,json=body).status_code==422
    body['snapshots']={'__proto__':{'polluted':True}};assert c.put(url,json=body).status_code==422


def test_failed_and_cancelled_stream_keep_delivered_partial(env,monkeypatch):
    c=account(env);chat=conversation(c)
    async def broken(*args):
        yield {'type':'delta','text':'已收到的文字。\n```genui\n{"op":"begin","v":1}\n'}
        raise AIError('模拟连接中断')
    monkeypatch.setattr(genui_ai,'stream_reply',broken)
    final=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation'];message=final['messages'][-1]
    assert message['status']=='failed' and '已收到的文字' in message['content'] and not message['genui']['validated'];assert not message['parts'][1]['spec']['complete']
    started=threading.Event();stopped=threading.Event()
    async def slow(*args):
        try:
            yield {'type':'delta','text':'取消前已送达。'};started.set();await asyncio.sleep(20)
            yield {'type':'delta','text':'不能写入的迟到内容'}
        finally:stopped.set()
    monkeypatch.setattr(genui_ai,'stream_reply',slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(c.post,f"/api/conversations/{chat['id']}/messages/stream",json=payload(final))
        assert started.wait(5);live=c.get('/api/conversations/'+chat['id']).json()
        response=c.post('/api/conversations/'+chat['id']+'/cancel',json={'version':live['version']});assert response.status_code==200
        pending.result(timeout=5);assert stopped.wait(2)
    final=c.get('/api/conversations/'+chat['id']).json();message=final['messages'][-1]
    assert message['status']=='cancelled';assert message['genui']['raw']=='取消前已送达。';assert message['content']=='取消前已送达。';assert not final['processing']
    # The lock is released after cancellation, not held until the configured timeout.
    monkeypatch.setattr(genui_ai,'stream_reply',recorded);assert c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(final)).status_code==200


def test_disabled_preferences_leave_legacy_interface_usable(env,monkeypatch):
    c=account(env);chat=conversation(c);preference=c.get('/api/genui/preferences').json();assert preference['enabled']
    r=c.put('/api/genui/preferences',json={'version':preference['version'],'enabled':False,'theme':'dark'});assert r.status_code==200 and not r.json()['enabled']
    assert c.put('/api/genui/preferences',json={'version':0,'enabled':True}).status_code==409
    assert c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)).status_code==409
    def legacy(*args):return {'answer':'普通文字回复','citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',legacy)
    old=c.post(f"/api/conversations/{chat['id']}/messages",json=payload(chat));assert old.status_code==200 and old.json()['messages'][-1]['content']=='普通文字回复'
    assert c.get('/api/session').json()['genui']['theme']=='dark'
    env[1].genui_enabled=False;c.put('/api/genui/preferences',json={'version':1,'enabled':True})
    assert not c.get('/api/session').json()['genui']['enabled']


def test_stream_requires_consent_owner_and_csrf(env,monkeypatch):
    c=account(env);other=account(env,'other');chat=conversation(c);env[1].ai_api_key='fixture';monkeypatch.setattr(genui_ai,'stream_reply',recorded)
    url=f"/api/conversations/{chat['id']}/messages/stream"
    assert other.post(url,json=payload(chat)).status_code==404
    assert c.post(url,json=payload(chat,allow_external_processing=False)).status_code==422
    assert c.post(url,json=payload(chat),headers={'X-CSRF-Token':'bad'}).status_code==403
    assert not c.get('/api/conversations/'+chat['id']).json()['messages']


def test_unconfigured_stream_retains_question(env):
    c=account(env);chat=conversation(c)
    final=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation']
    assert final['messages'][0]['role']=='user' and final['messages'][-1]['status']=='failed' and '未配置' in final['messages'][-1]['error']


def test_capabilities_are_vendor_independent_and_conservative(env):
    cfg=env[1];assert choose_tier(cfg)==1;cfg.ai_context_tokens=8000;assert choose_tier(cfg)==2
    cfg.genui_tier='1';assert choose_tier(cfg)==2;cfg.ai_supports_json=False;assert choose_tier(cfg)==3
    cfg.ai_model='another-provider';assert choose_tier(cfg)==3


def test_real_adapter_decodes_recorded_sse_and_validates_evidence(env,monkeypatch):
    cfg=env[1];cfg.ai_api_key='synthetic-credential';seen=[]
    result={'answer':RAW,'citations':[],'image_sources':[]};raw=json.dumps(result,ensure_ascii=True)
    body=''.join('data: '+json.dumps({'choices':[{'delta':{'content':raw[i:i+13]},'finish_reason':None}]})+'\n\n' for i in range(0,len(raw),13))
    body+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':20}})+'\n\ndata: [DONE]\n\n'
    def transport(request):seen.append(json.loads(request.content));return httpx.Response(200,content=body,headers={'content-type':'text/event-stream'})
    client=httpx.AsyncClient;monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(transport),**kwargs))
    async def collect():return [event async for event in genui_ai.stream_reply(cfg,[],[{'role':'user','content':'安排学习'}],{'phone':'private-contact','campus_role':'student'},1)]
    output=asyncio.run(collect());assert ''.join(e['text'] for e in output if e['type']=='delta')==RAW
    assert output[-1]['result']==result and seen[0]['stream'];assert 'private-contact' not in json.dumps(seen)


def test_server_message_limit_preserves_last_delivered_chunk(env,monkeypatch):
    cfg=env[1];cfg.genui_limits={'messageBytes':40};c=account(env);chat=conversation(c)
    async def oversized(*args):
        yield {'type':'delta','text':'保留。'}
        yield {'type':'delta','text':'中'*20}
    monkeypatch.setattr(genui_ai,'stream_reply',oversized)
    final=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation']
    assert final['messages'][-1]['genui']['raw']=='保留。' and final['messages'][-1]['status']=='failed' and not final['processing']


def test_tightened_data_limit_degrades_without_stranding_processing():
    from app.genui_api import message_parts
    parts=message_parts(RAW,1,True,{'stringBytes':8},{'materials':[{'name':'a very long filename exceeding limit'}]})
    assert parts==[{'kind':'text','text':RAW}]
