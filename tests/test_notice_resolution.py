import copy
import json

import pytest

from test_workflow import env,account
from test_notice_semantics import install_provider


def review_fixture(env,monkeypatch,*,global_issue=False):
    c,n,_=install_provider(env,monkeypatch)
    response=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert response.status_code==200,response.text
    record=response.json()
    if global_issue:
        record['draft']['quality']['issues'].append({'task_index':None,'code':'obligation','message':'参赛纪律是全程注意事项，原草稿未说明。','evidence':record['draft']['quality']['issues'][0]['evidence']})
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(record['draft']),n['id']))
    payload={'version':record['version'],'reviewed':True,'tasks':copy.deepcopy(record['draft']['tasks']),
             'source_indices':[0],'issue_resolutions':[{'issue_index':0,'action':'changed','task_indices':[0]}]}
    payload['tasks'][0]['title']='提交申请表'
    return c,record,payload


@pytest.mark.parametrize('fault',['old_blanket_note','unchanged','private_note_only','missing_source','duplicate_source','boolean_source',
    'duplicate_issue','unknown_issue','excluded_but_selected','new_label_without_change','wrong_target','acknowledge_local','short_disagreement'])
def test_invalid_resolutions_cannot_create_tasks_or_confirmation(env,monkeypatch,fault):
    c,n,p=review_fixture(env,monkeypatch)
    decision=p['issue_resolutions'][0]
    if fault=='old_blanket_note':p.pop('issue_resolutions');p['quality_resolution']='我已经全部核实处理好了。'
    elif fault in {'unchanged','private_note_only','new_label_without_change'}:
        p['tasks']=copy.deepcopy(n['draft']['tasks'])
        if fault=='private_note_only':p['tasks'][0]['notes']='个人计划明天准备材料。'
        if fault=='new_label_without_change':p['source_indices']=[None]
    elif fault=='missing_source':p.pop('source_indices')
    elif fault=='duplicate_source':p['tasks'].append(copy.deepcopy(p['tasks'][0]));p['source_indices']=[0,0]
    elif fault=='boolean_source':p['source_indices']=[False]
    elif fault=='duplicate_issue':p['issue_resolutions'].append(copy.deepcopy(decision))
    elif fault=='unknown_issue':decision['issue_index']=1
    elif fault=='excluded_but_selected':decision.update(action='excluded',task_indices=[])
    elif fault=='wrong_target':decision['task_indices']=[1]
    elif fault=='acknowledge_local':decision.update(action='acknowledged',task_indices=[],note='本人已核实，作为一般注意事项。')
    elif fault=='short_disagreement':decision.update(action='disagreed',task_indices=[],note='不适用')
    rejected=c.post('/api/notices/'+n['id']+'/confirm',json=p)
    assert rejected.status_code==422,rejected.text
    assert c.get('/api/tasks').json()==[]
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM confirmations').fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM audit WHERE action='confirm_draft'").fetchone()[0]==0


def test_each_issue_has_its_own_decision_and_original_receipt_survives_reload(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch,global_issue=True)
    url='/api/notices/'+n['id']
    assert c.post(url+'/confirm',json=p).status_code==422
    p['issue_resolutions'].append({'issue_index':1,'action':'acknowledged','note':'已对照原文核对参赛纪律，团队办理全程遵守，不另造申请手续。'})
    accepted=c.post(url+'/confirm',json=p);assert accepted.status_code==200,accepted.text
    receipt=c.get(url).json()['quality_receipt']
    assert receipt['version']==1 and receipt['review_status']=='needs_review'
    assert [item['action'] for item in receipt['issues']]==['changed','acknowledged']
    assert receipt['issues'][0]['finding']==n['draft']['quality']['issues'][0]
    assert receipt['issues'][0]['task_titles']==['提交申请表']
    replay=c.post(url+'/confirm',json={**p,'issue_resolutions':[]})
    assert replay.status_code==200 and replay.json()['replayed']
    assert c.get(url).json()['quality_receipt']==receipt and len(c.get('/api/tasks').json())==1


def test_excluded_step_cannot_be_reintroduced_by_claiming_it_is_new(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch)
    p['tasks']=copy.deepcopy(n['draft']['tasks']);p['source_indices']=[None]
    p['issue_resolutions']=[{'issue_index':0,'action':'excluded'}]
    assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==422
    p['tasks'][0].update(title='对照原文核实提交渠道',origin='manual')
    p['plans']={0:{'action_kind':'verification'}}
    accepted=c.post('/api/notices/'+n['id']+'/confirm',json=p)
    assert accepted.status_code==200,accepted.text
    assert c.get('/api/notices/'+n['id']).json()['quality_receipt']['issues'][0]['action']=='excluded'


def test_overall_omission_can_reference_an_actual_new_step(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch)
    with env[0].state.db.connect(write=True) as conn:
        draft=n['draft'];draft['quality']['issues'][0].update(task_index=None,code='omission')
        conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(draft),n['id']))
    p['tasks'][0].update(title='补充原文要求的申请表',origin='manual');p['source_indices']=[None]
    accepted=c.post('/api/notices/'+n['id']+'/confirm',json=p)
    assert accepted.status_code==200,accepted.text


def test_changed_classification_is_a_real_correction(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch)
    p['tasks']=copy.deepcopy(n['draft']['tasks'])
    p['plans']={0:{'action_kind':'optional','participation':'undecided'}}
    accepted=c.post('/api/notices/'+n['id']+'/confirm',json=p)
    assert accepted.status_code==200,accepted.text


def test_manual_review_requires_explicit_attestation_and_explanation(env,monkeypatch):
    c,n,_=install_provider(env,monkeypatch,second_status=429)
    n=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True}).json()
    p={'version':n['version'],'reviewed':True,'tasks':n['draft']['tasks'],'quality_resolution':'已逐份人工对照原文，移除了原文未规定的收费。'}
    p['tasks'][0]['title']='提交申请表'
    url='/api/notices/'+n['id']
    assert c.post(url+'/confirm',json=p).status_code==422
    p['manual_quality_reviewed']=True
    accepted=c.post(url+'/confirm',json=p);assert accepted.status_code==200,accepted.text
    assert c.get(url).json()['quality_receipt']['manual_reviewed'] is True


def test_reordering_alone_does_not_count_as_a_correction(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch)
    original=n['draft']['tasks'][0];second={**copy.deepcopy(original),'title':'准备原文要求的材料'}
    n['draft']['tasks'].append(second);n['draft']['quality']['checked_tasks']=2
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(n['draft']),n['id']))
    p.update(tasks=[copy.deepcopy(second),copy.deepcopy(original)],source_indices=[1,0],issue_resolutions=[{'issue_index':0,'action':'changed','task_indices':[1]}])
    assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==422
    p['tasks'][1]['title']='提交申请表'
    accepted=c.post('/api/notices/'+n['id']+'/confirm',json=p);assert accepted.status_code==200,accepted.text


@pytest.mark.parametrize('missing_source',[False,True])
def test_portable_receipt_round_trip_is_historical_owner_scoped_and_keeps_basis(env,monkeypatch,missing_source):
    c,n,p=review_fixture(env,monkeypatch)
    p['issue_resolutions'][0]['note']='已经删去原文未规定的收费要求，仅保留提交申请表。'
    assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==200
    bundle=c.get('/api/export').json()
    original_source=n['sources'][0]['id']
    if missing_source:bundle['notices'][0]['sources']=[]
    for username in ('receipt-bob','receipt-carol'):
        other=account(env,username)
        assert other.get('/api/notices/'+n['id']).status_code==404
        preview=other.post('/api/import',json={'data':bundle});assert preview.status_code==200,preview.text
        assert any('逐条核对记录' in w for w in preview.json()['warnings'])
        imported=other.post('/api/import',json={'data':bundle,'confirm':True,'digest':preview.json()['digest']})
        assert imported.status_code==200,imported.text
        bundle=other.get('/api/export').json();notice=bundle['notices'][0];receipt=notice['quality_receipt']
        assert receipt['imported'] and receipt['issues'][0]['note']==p['issue_resolutions'][0]['note']
        evidence=receipt['issues'][0]['finding']['evidence'][0]
        assert evidence['quote']==n['draft']['quality']['issues'][0]['evidence'][0]['quote']
        if missing_source:assert evidence['source_id']==''
        else:
            assert evidence['source_id']!=original_source
            assert evidence['source_id'] in {s['id'] for s in notice['sources']}
        assert all(not t['data']['deadline_confirmed'] for t in notice['tasks'])


def test_invalid_imported_review_payload_is_rejected_before_writes(env,monkeypatch):
    c,n,p=review_fixture(env,monkeypatch)
    assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==200
    bundle=c.get('/api/export').json();bundle['notices'][0]['quality_receipt']['issues'][0]['note']='x'*701
    other=account(env,'invalid-receipt')
    assert other.post('/api/import',json={'data':bundle}).status_code==422
    assert other.get('/api/export').json()['notices']==[]
