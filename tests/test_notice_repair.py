"""Corrections must earn an independent review, preserve evidence and stop safely."""
import json

import httpx
import pytest

from app import ai
from test_workflow import env, account, notice, raw_ai


def provider_for(env, monkeypatch, *, failure=None, change_after=None):
    c = account(env)
    n = notice(c)
    cfg = env[1]
    cfg.ai_api_key = 'synthetic-only'
    cfg.notice_semantic_review = cfg.notice_auto_repair = True
    original = httpx.Client
    seen = []

    def provider(request):
        payload = json.loads(request.content)
        seen.append(payload)
        number = len(seen)
        assert number <= 4, 'Corrections must never loop'
        if failure == number:
            return httpx.Response(429, json={'message': 'PRIVATE_PROVIDER_ERROR'})
        if number in {1, 3}:
            result = raw_ai(n)
            result['tasks'][0]['title'] = '缴纳未规定的申请费' if number == 1 else '提交申请表'
            if failure == 'invented_ref' and number == 3:
                result['tasks'][0]['evidence'] = [{'ref': 'R999999'}]
        else:
            body = json.loads(payload['messages'][1]['content'])
            ref = body['sources'][0]['sections'][0]['ref']
            result = {
                'source_checks': [{'source_index': 0, 'requirements_summary': '原文要求本科生本人提交申请表。',
                                   'evidence_refs': [ref], 'coverage': 'covered'}],
                'checked_task_indices': [0],
                'issues': [{'task_index': 0, 'code': 'procedure', 'message': '原文要求提交申请表，没有规定缴纳申请费。',
                            'evidence_refs': [ref]}] if number == 2 else [],
            }
        if change_after == number:
            with env[0].state.db.connect(write=True) as conn:
                conn.execute('UPDATE users SET profile=?', (json.dumps({'school': 'changed'}),))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}],
                                       'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    monkeypatch.setattr(ai.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(provider), **kw))
    return c, n, seen


def generate(c, n):
    return c.post('/api/notices/' + n['id'] + '/generate', json={'version': n['version'], 'allow_external_processing': True})


def test_repair_is_rechecked_before_replacing_draft_and_all_calls_are_accounted(env, monkeypatch):
    c, n, seen = provider_for(env, monkeypatch)
    response = generate(c, n)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['draft']['tasks'][0]['title'] == '提交申请表'
    assert result['draft']['quality']['status'] == 'passed'
    assert result['draft']['quality']['auto_repair']['previous_issue_count'] == 1
    assert len(seen) == 4
    assert '办理方案补正' in seen[2]['messages'][0]['content']
    run = c.get('/api/executions').json()['items'][0]
    assert run['metrics']['call_count'] == 4
    assert run['metrics']['input_tokens'] == 400 and run['metrics']['output_tokens'] == 200
    assert run['metrics']['usage_complete']
    assert [call['purpose'] for call in run['metrics']['calls']] == ['extraction', 'semantic_review', 'notice_repair', 'repair_review']
    assert result['calls'][0]['input_tokens'] == 400
    assert c.get('/api/tasks').json() == []
    accepted = c.post('/api/notices/' + n['id'] + '/confirm', json={
        'version': result['version'], 'tasks': result['draft']['tasks'], 'reviewed': True})
    assert accepted.status_code == 200, accepted.text


@pytest.mark.parametrize('failure,calls,outcome', [(3, 3, 'not_applied'), (4, 4, 'review_unavailable'), ('invented_ref', 3, 'not_applied')])
def test_failed_or_unreviewed_repair_keeps_original_findings(env, monkeypatch, failure, calls, outcome):
    c, n, seen = provider_for(env, monkeypatch, failure=failure)
    response = generate(c, n)
    assert response.status_code == 200, response.text
    draft = response.json()['draft']
    assert len(seen) == calls
    assert draft['tasks'][0]['title'] == '缴纳未规定的申请费'
    assert draft['quality']['status'] == 'needs_review'
    assert draft['quality']['auto_repair']['outcome'] == outcome
    assert 'PRIVATE_PROVIDER_ERROR' not in response.text
    assert c.post('/api/notices/' + n['id'] + '/confirm', json={
        'version': response.json()['version'], 'tasks': draft['tasks'], 'reviewed': True}).status_code == 422


@pytest.mark.parametrize('after', [2, 3])
def test_context_change_stops_before_next_paid_correction_or_review(env, monkeypatch, after):
    c, n, seen = provider_for(env, monkeypatch, change_after=after)
    response = generate(c, n)
    assert response.status_code == 409, response.text
    assert len(seen) == after
    assert c.get('/api/tasks').json() == []
    run = c.get('/api/executions').json()['items'][0]
    assert run['status'] == 'discarded' and run['metrics']['call_count'] == after


def test_fast_first_pass_escalates_one_correction_without_changing_shared_configuration(env, monkeypatch):
    c,n,seen=provider_for(env,monkeypatch)
    before=(env[1].ai_model,env[1].notice_review_model,env[1].notice_thinking)
    response=c.post('/api/notices/'+n['id']+'/generate',json={
        'version':n['version'],'allow_external_processing':True,'processing_mode':'daily'})
    assert response.status_code==200,response.text
    assert [item['thinking']['type'] for item in seen]==['disabled','disabled','enabled','enabled']
    assert [item['model'] for item in seen]==['mimo-v2.6-flash','mimo-v2.6-flash',env[1].ai_composition_model,'mimo-v2.6-flash']
    assert response.json()['draft']['quality']['auto_repair']['escalated']
    assert response.json()['draft']['quality']['status']=='passed'
    assert (env[1].ai_model,env[1].notice_review_model,env[1].notice_thinking)==before


def test_informational_unknown_date_marker_is_not_confused_with_an_unreferenced_fact():
    sources=[{'id':'synthetic-source','name':'通知正文','kind':'text','status':'ok',
              'sections':[{'locator':'第1段','text':'通知只供知悉，无需办理。'}]}]
    raw={'title':'知悉公告','summary':'通知只供知悉，无需办理手续。','applicability':'matches_known',
         'applicability_reason':'普通知悉信息，不产生办理任务。','facts':{key:{'value':'','evidence':[]} for key in ai.FACT_KEYS},'tasks':[],'warnings':[]}
    raw['facts']['dates']['value']='通知未给出具体日期'
    result=ai.validate_extraction(raw,sources,None)
    assert result['facts']['dates']['value']=='' and result['tasks']==[]
    for invented in ['2027年10月20日','须支付申请费','通知未给出具体日期，但我推测是明天']:
        raw['facts']['dates']['value']=invented
        with pytest.raises(ValueError,match='缺少原文依据'):ai.validate_extraction(raw,sources,None)


@pytest.mark.parametrize('bad_answer',[None,{'properties':{},'type':'object'}])
@pytest.mark.parametrize('findings',[False,True])
def test_format_correction_requires_review_and_does_not_start_another_repair_loop(env,monkeypatch,bad_answer,findings):
    c=account(env);n=notice(c);cfg=env[1]
    cfg.ai_api_key='synthetic';cfg.notice_semantic_review=cfg.notice_auto_repair=True
    original=httpx.Client;seen=[]
    def provider(request):
        payload=json.loads(request.content);seen.append(payload)
        if len(seen)==1:result=bad_answer
        elif len(seen)==2:result=raw_ai(n)
        else:
            assert len(seen)==3, 'The shared correction budget was already used'
            data=json.loads(payload['messages'][1]['content']);ref=data['sources'][0]['sections'][0]['ref']
            result={'source_checks':[{'source_index':0,'requirements_summary':'本人需要在规定时间提交申请表。','evidence_refs':[ref],'coverage':'covered'}],
                'checked_task_indices':[0],'issues':[{'task_index':0,'code':'procedure','message':'办理步骤还需本人对照原文进一步核对。','evidence_refs':[ref]}] if findings else []}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':50}})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    response=generate(c,n);assert response.status_code==200,response.text
    assert len(seen)==3 and c.get('/api/tasks').json()==[]
    quality=response.json()['draft']['quality']
    assert quality['status']==('needs_review' if findings else 'passed')
    assert quality['auto_repair']['outcome']=='format_corrected'
    metrics=c.get('/api/executions').json()['items'][0]['metrics']
    assert metrics['call_count']==3 and metrics['input_tokens']==300
    assert [call['purpose'] for call in metrics['calls']]==['extraction','format_repair','semantic_review']
    assert response.json()['calls'][0]['input_tokens']==300

