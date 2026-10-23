from copy import deepcopy

import pytest

from tests.test_workflow import account, env, notice, manual, confirm, task


def create_tasks(c):
    n=manual(c,notice(c))
    response=c.post('/api/notices/'+n['id']+'/confirm',json={'version':n['version'],'reviewed':True,
        'tasks':[task(n,title=title,materials=[],due_date=None,due_time=None,deadline_confirmed=False) for title in ['线上途径','线下途径','领取结果']]})
    assert response.status_code==200,response.text
    return response.json()['task_ids']


def save_flow(c,tid,*,complete=False,**changes):
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    return c.put('/api/tasks/'+tid+'/workflow',json={'version':t['workflow']['version'],'task_version':t['version'],
        'complete':complete,'data':{**t['workflow']['data'],**changes}})


def finish_task(c,tid):
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    return c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'done','data':t['data'],'reason':'本人确认已经完成'})


def test_alternative_paths_require_one_actual_completed_and_current_predecessor(env):
    c=account(env);a,b,target=create_tasks(c)
    assert save_flow(c,target,dependencies=[a,b],dependency_mode='any',execution_mode='collection').status_code==200
    assert finish_task(c,target).status_code==422
    assert finish_task(c,a).status_code==200
    assert not c.get('/api/tasks/'+target+'/workflow').json()['task']['workflow']['blocked']
    assert finish_task(c,target).status_code==200
    # Switching to all does not inherit the historical completion as valid.
    updated=save_flow(c,target,dependency_mode='all')
    assert updated.status_code==200 and updated.json()['change_review']['state']=='pending'


def test_any_conditions_never_bypass_participation_or_unknown_conditions(env):
    c=account(env);tid=create_tasks(c)[0]
    conditions=[{'id':'online','text':'线上资格已经通过','state':'unknown','note':''},
                {'id':'offline','text':'线下资格已经通过','state':'not_met','note':'未通过现场核查'}]
    assert save_flow(c,tid,condition_mode='any',conditions=conditions,action_kind='optional').status_code==200
    assert finish_task(c,tid).status_code==422
    conditions[0].update(state='met',note='已查看本人的线上资格结果')
    assert save_flow(c,tid,conditions=conditions).status_code==200
    assert finish_task(c,tid).status_code==422
    assert save_flow(c,tid,participation='joined',complete=True).status_code==200


@pytest.mark.parametrize('mode',['reading','attendance','decision','collection','payment','waiting','task','custom'])
def test_non_submission_modes_record_real_outcomes_without_invented_receipts(env,mode):
    c=account(env);tid=create_tasks(c)[0]
    result=save_flow(c,tid,execution_mode=mode,stage='recorded',outcome='本人已完成核对并记录结果',complete=True)
    assert result.status_code==200,result.text
    assert result.json()['status']=='done'
    assert result.json()['workflow']['data']['receipt']==''


def test_custom_milestones_are_not_silently_completed_when_renamed(env):
    c=account(env);tid=create_tasks(c)[0]
    steps=[{'id':'contact','title':'联系指导老师','done':False,'note':''},{'id':'confirm','title':'确认场地','done':True,'note':'现场核对'}]
    assert save_flow(c,tid,execution_mode='custom',phase_label='准备展示',milestones=steps).status_code==200
    assert save_flow(c,tid,complete=True).status_code==422
    steps[0]['done']=True
    assert save_flow(c,tid,milestones=steps,complete=True).status_code==200
    steps[1]['title']='确认新的展示场地'
    result=save_flow(c,tid,milestones=steps)
    assert result.status_code==200,result.text
    assert result.json()['workflow']['data']['milestones'][1]['done'] is False
    assert result.json()['change_review']['state']=='pending'


def test_any_dependency_cannot_cross_accounts_or_create_cycles(env):
    c=account(env);a,b,_=create_tasks(c)
    other=account(env,'other');foreign=create_tasks(other)[0]
    assert save_flow(c,a,dependencies=[foreign],dependency_mode='any').status_code==422
    assert save_flow(c,a,dependencies=[b],dependency_mode='any').status_code==200
    assert save_flow(c,b,dependencies=[a],dependency_mode='any').status_code==422


def test_draft_modes_and_alternatives_reach_confirmed_workflow(env):
    c=account(env);n=manual(c,notice(c))
    data=task(n,materials=[])
    r=c.post('/api/notices/'+n['id']+'/confirm',json={'version':n['version'],'reviewed':True,'tasks':[data,data,data],
        'plans':{'2':{'action_kind':'required','execution_mode':'decision','dependency_mode':'any','condition_mode':'any','depends_on':[0,1],'conditions':['拿到线上结果','拿到线下结果']}}})
    assert r.status_code==200,r.text
    tid=r.json()['task_ids'][2]
    flow=c.get('/api/tasks/'+tid+'/workflow').json()['task']['workflow']['data']
    assert flow['execution_mode']=='decision' and flow['dependency_mode']==flow['condition_mode']=='any'
    assert len(flow['dependencies'])==2


@pytest.mark.parametrize('change_kind',['requirements','conditions'])
def test_recorded_outcome_requires_review_after_requirements_or_conditions_change(env,change_kind):
    c=account(env);tid=create_tasks(c)[0]
    recorded=save_flow(c,tid,execution_mode='reading',stage='recorded',outcome='已核对并记录阅读结果')
    assert recorded.status_code==200,recorded.text
    t=recorded.json()
    assert t['status']=='pending' and not t['change_review']
    if change_kind=='requirements':
        changed=c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'pending',
            'data':{**t['data'],'details':'通知新增阅读范围，需要重新核对原结果'},'reason':'根据原文核实新增要求'})
    else:
        changed=save_flow(c,tid,conditions=[{'id':'new-condition','text':'新增适用条件','state':'unknown','note':''}])
    assert changed.status_code==200,changed.text
    assert changed.json()['change_review']['state']=='pending'
