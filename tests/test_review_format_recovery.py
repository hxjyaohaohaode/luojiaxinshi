"""Completed malformed reviews may recover once; uncertain requests never replay."""
import json
import httpx
import pytest
from app import ai
from app.notice_progress import Trace
from app.notice_semantics import reviewed
from tests.test_workflow import env,account,notice,raw_ai


def setup(env,monkeypatch,*,initial_format=False,substantive=False,again=False,failure=None,change=False,enabled=True):
    c=account(env);n=notice(c);app,cfg=env
    cfg.ai_api_key='synthetic-only';cfg.notice_semantic_review=True;cfg.notice_auto_repair=enabled
    original=httpx.Client;seen=[];first_review=3 if initial_format else 2
    def provider(request):
        payload=json.loads(request.content);seen.append(payload);number=len(seen)
        assert number<=4,'Shared notice model-call cap exceeded'
        if number==first_review and failure:
            if failure=='timeout':raise httpx.ReadTimeout('synthetic ambiguous timeout',request=request)
            if failure=='http':return httpx.Response(503,json={'message':'PRIVATE_PROVIDER_DETAIL'})
        if number<first_review:
            result={'wrong_schema':True} if initial_format and number==1 else raw_ai(n)
            if substantive and 'tasks' in result:result['tasks'][0]['title']='缴纳未规定的申请费'
        else:
            data=json.loads(payload['messages'][1]['content']);ref=data['sources'][0]['allowed_evidence_refs'][0]
            result={'checked_task_indices':[0],'source_checks':[{'source_index':0,'requirements_summary':'本科生本人按原文提交申请表。',
                'evidence_refs':['R999999'] if number==first_review or again else [ref],'coverage':'covered'}],
                'issues':[{'task_index':0,'code':'procedure','message':'草稿写了缴费，但原文只要求提交申请表，未要求缴费。','evidence_refs':[ref]}] if substantive else []}
            if number>first_review:
                assert data['previous_review']['failure_code']=='unknown_reference'
                assert '不得为了通过格式检查删掉实质问题' in data['correction_request']
            if number==first_review and change:
                with app.state.db.connect(write=True) as conn:conn.execute('UPDATE users SET profile=?',(json.dumps({'college':'changed'}),))
        finish='length' if failure=='truncated' and number==first_review else 'stop'
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':json.dumps(result)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':50}})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    return c,n,seen


def generate(c,n):return c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})


def test_completed_invalid_review_gets_one_exactly_validated_recovery_and_accounting(env,monkeypatch):
    c,n,seen=setup(env,monkeypatch);r=generate(c,n)
    assert r.status_code==200,r.text
    quality=r.json()['draft']['quality']
    assert quality['status']=='passed' and quality['review_format_repair']['outcome']=='corrected'
    assert len(seen)==3 and c.get('/api/tasks').json()==[]
    metrics=c.get('/api/executions').json()['items'][0]['metrics']
    assert metrics['call_count']==3 and metrics['input_tokens']==300 and metrics['output_tokens']==150
    assert [x['purpose'] for x in metrics['calls']]==['extraction','semantic_review','review_format_repair']


def test_recovered_format_does_not_erase_findings_or_purchase_a_fifth_stage(env,monkeypatch):
    c,n,seen=setup(env,monkeypatch,substantive=True,initial_format=True);r=generate(c,n)
    assert r.status_code==200,r.text
    draft=r.json()['draft'];assert draft['quality']['status']=='needs_review' and draft['quality']['issues']
    assert len(seen)==4 and draft['tasks'][0]['title']=='缴纳未规定的申请费'
    assert c.post('/api/notices/'+n['id']+'/confirm',json={'version':r.json()['version'],'tasks':draft['tasks'],'reviewed':True}).status_code==422


@pytest.mark.parametrize('failure',['timeout','http','truncated'])
def test_uncertain_transport_http_or_unfinished_review_is_never_replayed(env,monkeypatch,failure):
    c,n,seen=setup(env,monkeypatch,failure=failure);r=generate(c,n)
    assert r.status_code==200,r.text
    assert r.json()['draft']['quality']['status']=='unavailable' and len(seen)==2
    assert 'review_format_repair' not in r.json()['draft']['quality']
    assert 'PRIVATE_PROVIDER_DETAIL' not in r.text


@pytest.mark.parametrize('enabled,again,expected',[(False,False,2),(True,True,3)])
def test_disabled_or_still_invalid_recovery_stops_without_publishing_trust(env,monkeypatch,enabled,again,expected):
    c,n,seen=setup(env,monkeypatch,enabled=enabled,again=again);r=generate(c,n)
    assert r.status_code==200,r.text
    assert r.json()['draft']['quality']['status']=='unavailable' and len(seen)==expected
    assert c.get('/api/tasks').json()==[]


def test_context_changes_after_completed_bad_review_stop_before_another_paid_call(env,monkeypatch):
    c,n,seen=setup(env,monkeypatch,change=True);r=generate(c,n)
    assert r.status_code==409,r.text
    assert len(seen)==2 and c.get('/api/tasks').json()==[]
    assert c.get('/api/executions').json()['items'][0]['status']=='discarded'


def test_shared_cap_is_checked_before_any_review_request(env,monkeypatch):
    c=account(env);n=notice(c);trace=Trace();trace.metrics={'calls':[{'requested':True} for _ in range(4)]}
    def forbidden(*args,**kwargs):raise AssertionError('Must stop before a fifth paid request')
    monkeypatch.setattr('app.notice_semantics.review',forbidden)
    result,recovered=reviewed(env[1],n,n['sources'],{},raw_ai(n),trace)
    assert result['status']=='unavailable' and not recovered and len(trace.metrics['calls'])==4
