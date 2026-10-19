"""Compact model references must restore exact originals, never approximate quotes."""
import json

import httpx
import pytest

from app import ai
from app.documents import text_source
from app.notice_references import build,expand,MAX_QUOTE
from test_workflow import env,account,notice


def test_reference_roundtrip_keeps_markdown_and_every_character_in_long_sections():
    original='请打开 [报名入口](https://example.org/register)；'+('长段原文甲乙丙丁。'*450)
    source=text_source(original);prepared,refs=build([source])
    assert ''.join(s['text'] for s in prepared[0]['sections'])==original
    assert all(len(v['quote'])<=MAX_QUOTE and v['quote'] in original for v in refs.values())
    raw={'facts':{'submission':{'value':'报名入口','evidence':[next(iter(refs))]}},'tasks':[]}
    restored=expand(raw,refs)
    assert '[报名入口](https://example.org/register)' in restored['facts']['submission']['evidence'][0]['quote']
    assert raw['facts']['submission']['evidence']==[next(iter(refs))]


def test_unknown_reference_is_rejected_and_repeated_reference_is_not_duplicated():
    _,refs=build([text_source('准确的原文。')]);ref=next(iter(refs))
    assert len(expand({'tasks':[{'evidence':[ref,ref]}]},refs)['tasks'][0]['evidence'])==1
    with pytest.raises(ValueError,match='编号不存在'):expand({'tasks':[{'deadline_evidence':['R999999']}]},refs)


@pytest.mark.parametrize('invalid,finish',[ (False,'stop'),(True,'stop'),(False,'length') ])
def test_real_notice_route_expands_refs_and_keeps_returned_usage_on_rejection(env,monkeypatch,invalid,finish):
    c=account(env);n=notice(c,text='请于2026年10月19日24:00前在 [平台](https://example.org/register) 上传报名表。')
    env[1].ai_api_key='synthetic-provider-key';original=httpx.Client
    def provider(request):
        payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content']);ref=context['sources'][0]['sections'][0]['ref']
        assert '"planned_at"' not in payload['messages'][0]['content']
        value='R999999' if invalid else ref
        draft={'title':'报名','summary':'核对报名要求','applicability':'needs_review','applicability_reason':'本人核对资格',
               'facts':{k:{} for k in ai.FACT_KEYS},'tasks':[{'title':'提交报名表','due_date':'2026-10-20','due_time':'00:00',
                    'action_kind':'required','depends_on':[],'conditions':['已取得签章'],
                    'deadline_text':'2026年10月19日24:00前','evidence':[value],'deadline_evidence':[value]}]}
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':json.dumps(draft)}}],
                                        'usage':{'prompt_tokens':234,'completion_tokens':456}})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(provider),**kwargs))
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==(502 if invalid or finish!='stop' else 200),response.text
    record=c.get('/api/notices/'+n['id']).json();call=record['calls'][0]
    assert call['input_tokens']==234 and call['output_tokens']==456
    assert c.get('/api/tasks').json()==[]
    if response.status_code==200:
        task=record['draft']['tasks'][0]
        assert task['due_date']=='2026-10-20' and task['due_time']=='00:00'
        assert record['draft']['plans']['0']['conditions']==['已取得签章'] and 'conditions' not in task
        assert '[平台](https://example.org/register)' in task['evidence'][0]['quote']
    else:assert record['status']=='failed' and record['draft'] is None


@pytest.mark.parametrize('body',[
    [],'not an object',{'choices':[None]},
    {'choices':[{'finish_reason':'stop','message':[]}]},
    {'choices':[{'finish_reason':'stop','message':{'content':{}}}]},
])
def test_malformed_provider_envelope_is_a_recoverable_failure(env,monkeypatch,body):
    c=account(env);n=notice(c);env[1].ai_api_key='synthetic-provider-key';original=httpx.Client
    if isinstance(body,dict):body={**body,'usage':{'prompt_tokens':234,'completion_tokens':456}}
    monkeypatch.setattr(ai.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=body)),**kwargs))
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==502,response.text
    record=c.get('/api/notices/'+n['id']).json()
    assert record['status']=='failed' and record['draft'] is None
    assert record['calls'][0]['input_tokens']==(234 if isinstance(body,dict) else None)
    assert record['calls'][0]['output_tokens']==(456 if isinstance(body,dict) else None)
    assert c.get('/api/tasks').json()==[]
