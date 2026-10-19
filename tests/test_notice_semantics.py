import json

import httpx
import pytest

from app import ai
from app.notice_semantics import prepare,validate
from test_workflow import env,account,notice,raw_ai


def install_provider(env,monkeypatch,*,issue=True,second_status=200,invalid=False,expected_review_model=None):
    c=account(env);n=notice(c);cfg=env[1];cfg.ai_api_key='synthetic-only';cfg.notice_semantic_review=True
    original=httpx.Client;seen=[]
    def provider(request):
        payload=json.loads(request.content);seen.append(payload)
        if len(seen)==1:
            result=raw_ai(n);result['tasks'][0]['title']='缴纳未规定的申请费'
            usage={'prompt_tokens':100,'completion_tokens':50,'completion_tokens_details':{'reasoning_tokens':20}}
        else:
            assert len(seen)==2 and payload['model']==(expected_review_model or cfg.notice_review_model) and payload['thinking']['type']=='enabled'
            assert payload['max_completion_tokens']==(6144 if payload['model']=='mimo-v2.6-flash' else 16384)
            if second_status!=200:return httpx.Response(second_status,json={'message':'PROVIDER_PRIVATE_BODY'})
            body=json.loads(payload['messages'][1]['content']);ref=body['sources'][0]['sections'][0]['ref']
            result={'source_checks':[{'source_index':0,'requirements_summary':'原文要求本人提交申请表。','evidence_refs':[ref],'coverage':'covered'}],
                'checked_task_indices':[] if invalid else [0],'issues':[{'task_index':0,'code':'procedure','message':'原文只要求提交申请表，没有要求缴纳费用。','evidence_refs':[ref]}] if issue else []}
            usage={'prompt_tokens':80,'completion_tokens':30,'completion_tokens_details':{'reasoning_tokens':10}}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}],'usage':usage})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    return c,n,seen


@pytest.mark.parametrize('options,status,complete,tokens',[({},'needs_review',True,180),({'issue':False},'passed',True,180),
    ({'second_status':429},'unavailable',False,100),({'invalid':True},'unavailable',True,180)])
def test_two_stage_draft_preserves_findings_usage_and_requires_explicit_resolution(env,monkeypatch,options,status,complete,tokens):
    c,n,seen=install_provider(env,monkeypatch,**options)
    r=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert r.status_code==200,r.text
    result=r.json();quality=result['draft']['quality'];assert quality['status']==status
    assert len(seen)==2 and c.get('/api/tasks').json()==[]
    run=c.get('/api/executions').json()['items'][0];metrics=run['metrics']
    assert metrics['call_count']==2 and metrics['usage_complete'] is complete and metrics['input_tokens']==tokens
    assert result['calls'][0]['input_tokens']==tokens
    assert [call['purpose'] for call in metrics['calls']]==['extraction','semantic_review']
    assert 'PROVIDER_PRIVATE_BODY' not in json.dumps(result)
    payload={'version':result['version'],'reviewed':True,'tasks':result['draft']['tasks']}
    if status!='passed':
        assert c.post('/api/notices/'+n['id']+'/confirm',json=payload).status_code==422
        assert c.get('/api/tasks').json()==[]
        payload['quality_resolution']='已对照原文删除收费表述，当前步骤仅保留提交申请表。'
        payload['tasks'][0]['title']='提交申请表'
        if status=='needs_review':
            payload.update(source_indices=[0],issue_resolutions=[{'issue_index':0,'action':'changed','task_indices':[0]}])
        else:payload['manual_quality_reviewed']=True
    accepted=c.post('/api/notices/'+n['id']+'/confirm',json=payload)
    assert accepted.status_code==200,accepted.text
    replay=c.post('/api/notices/'+n['id']+'/confirm',json={**payload,'quality_resolution':''})
    assert replay.status_code==200 and replay.json()['replayed']
    with env[0].state.db.connect() as conn:
        audit=conn.execute("SELECT before_json,after_json FROM audit WHERE notice_id=? AND action='confirm_draft'",(n['id'],)).fetchone()
        assert json.loads(audit['before_json'])['quality']['status']==status
        assert json.loads(audit['after_json'])['quality_resolution']==payload.get('quality_resolution','')


def test_profile_change_after_extraction_stops_before_second_paid_request(env,monkeypatch):
    c,n,seen=install_provider(env,monkeypatch);original=ai.validate_extraction
    def changed(*args):
        draft=original(*args)
        with env[0].state.db.connect(write=True) as conn:conn.execute("UPDATE users SET profile=?",(json.dumps({'school':'changed'}),))
        return draft
    monkeypatch.setattr(ai,'validate_extraction',changed)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==409,response.text
    assert len(seen)==1 and c.get('/api/tasks').json()==[]
    run=c.get('/api/executions').json()['items'][0]
    assert run['status']=='discarded' and run['stop_reason']=='context_changed'
    assert run['metrics']['call_count']==1 and run['metrics']['input_tokens']==100


@pytest.mark.parametrize('checked,task,refs',[([],0,['R000001']),([0,0],0,['R000001']),([True],0,['R000001']),([0],True,['R000001']),([0],1,['R000001']),([0],0,['R999999'])])
def test_incomplete_coverage_invalid_task_and_invented_evidence_are_rejected(checked,task,refs):
    value={'source_checks':[{'source_index':0,'requirements_summary':'核对该份原始材料的要求。','evidence_refs':['R000001'],'coverage':'covered'}],
        'checked_task_indices':checked,'issues':[{'task_index':task,'code':'procedure','message':'必须能回查真实原文才能提示。','evidence_refs':refs}]}
    with pytest.raises(ValueError):validate(value,{'R000001':{'source_id':'s','locator':'第1段','quote':'原文'}},1)


def test_review_projection_does_not_send_private_task_fields_or_repeat_quotes(env):
    c=account(env);n=notice(c);draft=raw_ai(n)
    draft['tasks'][0].update(notes='PRIVATE_NOTES',resolution_note='PRIVATE_RESOLUTION',reminder_at='PRIVATE_REMINDER')
    _,_,_,body=prepare(n,n['sources'],{'phone':'PRIVATE_PHONE','goals':'相关目标'},draft)
    for private in ['PRIVATE_NOTES','PRIVATE_RESOLUTION','PRIVATE_REMINDER','PRIVATE_PHONE']:assert private not in body
    assert '相关目标' in body


def test_review_budget_guard_keeps_draft_and_does_not_send_second_request(env,monkeypatch):
    c,n,seen=install_provider(env,monkeypatch);original=ai.validate_extraction
    def oversized_review(*args):
        draft=original(*args)
        draft['tasks'][0]['details']='这是一条长办理说明。'*250
        env[1].notice_input_tokens=4096
        return draft
    monkeypatch.setattr(ai,'validate_extraction',oversized_review)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==200,response.text
    assert len(seen)==1 and response.json()['draft']['quality']['status']=='unavailable'
    metrics=c.get('/api/executions').json()['items'][0]['metrics']
    assert metrics['call_count']==1 and metrics['calls'][1]['status']=='skipped'
    assert metrics['usage_complete'] and metrics['input_tokens']==100
    assert c.get('/api/tasks').json()==[]


@pytest.mark.parametrize('problem',['missing_source','wrong_source_ref','missing_gap_issue','duplicate_source'])
def test_source_coverage_is_complete_and_uses_its_own_originals(problem):
    refs={'R000001':{'source_id':'a','quote':'本人提交申请表','locator':'第1段'},'R000002':{'source_id':'b','quote':'须交付手机应用','locator':'第1段'}}
    checks=[{'source_index':i,'requirements_summary':'此材料说明本人需要提交的内容。','evidence_refs':[f'R00000{i+1}'],'coverage':'covered'} for i in range(2)]
    if problem=='missing_source':checks.pop()
    elif problem=='wrong_source_ref':checks[1]['evidence_refs']=['R000001']
    elif problem=='missing_gap_issue':checks[1]['coverage']='gaps'
    else:checks[1]['source_index']=0
    with pytest.raises(ValueError):validate({'source_checks':checks,'checked_task_indices':[0],'issues':[]},refs,1)
