import json
import sqlite3
from contextlib import closing

import httpx
import pytest

from app import ai,notice_stream
from app.db import Database
from app.models import Extraction
from app.notice_progress import public_metrics
from app.notice_references import output_schema
from test_workflow import env,account,notice


class Chunks(httpx.SyncByteStream):
    def __init__(self,body):self.body=body;self.closed=False
    def __iter__(self):
        for start in range(0,len(self.body),13):yield self.body[start:start+13]
    def close(self):self.closed=True


def packet(value):return ('data: '+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))+'\r\n\r\n').encode('utf8')


def setup_provider(env,monkeypatch,*,end=True,finish='stop',invalid=False,error=False):
    c=account(env);n=notice(c);env[1].ai_api_key='synthetic-only';original=httpx.Client
    seen=[];streams=[]
    def provider(request):
        payload=json.loads(request.content);seen.append(payload)
        assert payload['stream'] and payload['stream_options']['include_usage']
        context=json.loads(payload['messages'][1]['content']);ref=context['sources'][0]['sections'][0]['ref']
        raw={'title':'合成通知','summary':'逐项核对','applicability':'needs_review','applicability_reason':'请核对本人条件',
             'facts':{k:{} for k in ai.FACT_KEYS},'tasks':[{'title':'提交申请表','evidence':['R999999' if invalid else ref]}]}
        answer=json.dumps(raw,ensure_ascii=False)
        body=b': keepalive\r\n\r\n'+packet({'choices':[{'index':0,'delta':{'reasoning_content':'PRIVATE_REASONING_NEVER_STORE'}}]})
        for part in [answer[:50],answer[50:]]:body+=packet({'choices':[{'index':0,'delta':{'content':part}}]})
        body+=packet({'choices':[{'delta':{},'finish_reason':finish}]})
        body+=packet({'choices':[],'usage':{'prompt_tokens':123,'completion_tokens':456,
            'prompt_tokens_details':{'cached_tokens':32},'completion_tokens_details':{'reasoning_tokens':99},'injected':'MUST_NOT_STORE'}})
        if error:body+=packet({'error':{'message':'PRIVATE_PROVIDER_ERROR'}})
        if end:body+=packet('[DONE]')
        stream=Chunks(body);streams.append(stream)
        return httpx.Response(200,headers={'content-type':'text/event-stream; charset=utf-8'},stream=stream)
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    return c,n,seen,streams


@pytest.mark.parametrize('options,expected',[({},200),({'invalid':True},502),({'end':False},502),({'finish':'length'},502),({'error':True},502)])
def test_stream_validates_before_publication_retains_scalar_usage_and_never_retries(env,monkeypatch,options,expected):
    c,n,seen,streams=setup_provider(env,monkeypatch,**options)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==expected,response.text
    record=c.get('/api/notices/'+n['id']).json();run=c.get('/api/executions').json()['items'][0]
    assert len(seen)==1 and streams[0].closed
    assert record['calls'][0]['input_tokens']==123 and record['calls'][0]['output_tokens']==456
    metrics=run['metrics'];assert metrics['transport']=='sse' and metrics['reasoning_tokens']==99 and metrics['cached_input_tokens']==32
    assert metrics['call_count']==1 and metrics['calls'][0]['status']==('succeeded' if expected==200 else 'failed')
    assert metrics['usage_complete']
    assert metrics['first_answer_seconds']>=0 and metrics['elapsed_seconds']>=metrics['first_answer_seconds']
    assert c.get('/api/tasks').json()==[]
    assert (record['draft'] is not None)==(expected==200)
    assert all(secret not in json.dumps([record,run]) for secret in ['PRIVATE_REASONING','PRIVATE_PROVIDER_ERROR','MUST_NOT_STORE'])
    with env[0].state.db.connect() as conn:
        stored=conn.execute('SELECT metrics FROM execution_metrics').fetchone()[0]
        assert 'PRIVATE' not in stored and 'MUST_NOT_STORE' not in stored
    progress=c.get('/api/notices/'+n['id']+'/processing').json()
    assert 'sources' not in progress and progress['elapsed_seconds'] is None
    other=account(env,'someone.else')
    assert other.get('/api/notices/'+n['id']+'/processing').status_code==404
    assert other.get('/api/executions').json()['items']==[]


def test_stream_bounds_even_a_single_unterminated_line(env,monkeypatch):
    from app.notice_progress import Trace
    monkeypatch.setattr(notice_stream,'MAX_EVENT_BYTES',100)
    stream=Chunks(b'data: '+b'x'*101)
    with closing(httpx.Response(200,headers={'content-type':'text/event-stream'},stream=stream)) as response:
        with pytest.raises(ValueError,match='event_too_large'):notice_stream.read_reply(response,Trace())
    assert stream.closed


def test_unknown_invalid_and_private_metric_values_never_cross_the_api():
    assert public_metrics({'transport':'<script>','prompt':'private','input_tokens':True,'output_tokens':-1,
                           'cached_input_tokens':3.5,'reasoning_tokens':None,'elapsed_seconds':float('nan')})=={}
    assert public_metrics({'transport':'json','input_tokens':0,'elapsed_seconds':1.25})=={'transport':'json','input_tokens':0,'elapsed_seconds':1.25}


def test_provider_schema_requires_evidence_actor_and_plans_without_changing_manual_schema():
    original=Extraction.model_json_schema();schema=output_schema(original)
    assert {'scope','evidence','action_kind','depends_on','conditions','due_date','due_time','deadline_text','deadline_evidence'}<=set(schema['$defs']['TaskData']['required'])
    assert schema['$defs']['TaskData']['properties']['evidence']['minItems']==1
    assert set(schema['properties']['facts']['required'])==ai.FACT_KEYS
    assert set(schema['$defs']['Fact']['required'])=={'value','evidence'}
    assert original==Extraction.model_json_schema()


def test_execution_schema_one_upgrades_without_changing_its_runs(env,tmp_path):
    from test_execution import pending
    c=account(env);key,_,_=pending(env,c,'notice');target=tmp_path/'old.sqlite3';env[0].state.db.backup(target)
    with sqlite3.connect(target) as conn:
        conn.execute('DROP TABLE execution_metrics');conn.execute("UPDATE meta SET value='1' WHERE key='execution_schema_version'")
    upgraded=Database(target)
    with upgraded.connect() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='execution_schema_version'").fetchone()[0]=='2'
        assert conn.execute('SELECT status FROM executions WHERE id=?',(key,)).fetchone()[0]=='running'
        assert conn.execute('SELECT count(*) FROM execution_metrics').fetchone()[0]==0
