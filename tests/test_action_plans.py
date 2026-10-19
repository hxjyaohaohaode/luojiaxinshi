"""Confirmed action plans remain distinct from actual fulfillment of conditions."""
import pytest
import json

from test_workflow import env,account,notice,manual,task
from test_action_workflow import setup_tasks,workflow
from test_workflow_migration import import_file


def finish(c,tid):
    t=c.get(f'/api/tasks/{tid}/workflow').json()['task']
    return c.put('/api/tasks/'+tid,json={'version':t['version'],'data':t['data'],'status':'done','reason':'本人核对后完成'})


@pytest.mark.parametrize('participation',['undecided','declined'])
def test_optional_action_requires_explicit_participation_before_completion_or_submission(env,participation):
    c=account(env);_,ids=setup_tasks(c);tid=ids[0]
    assert workflow(c,tid,action_kind='optional',participation=participation).status_code==200
    assert finish(c,tid).status_code==422
    assert workflow(c,tid,stage='submitted',prepared_materials=['申请表'],receipt='本人记录').status_code==422
    assert workflow(c,tid,participation='joined').status_code==200
    assert finish(c,tid).status_code==200


def test_confirmed_plan_maps_forward_dependencies_and_preserves_unknown_conditions(env):
    c=account(env);n=manual(c,notice(c))
    payload={'version':n['version'],'reviewed':True,'tasks':[task(n,title='提交'),task(n,title='取得签章')],
             'plans':{'0':{'action_kind':'required','depends_on':[1],'conditions':['已获得正式立项通知']},
                      '1':{'action_kind':'optional'}}}
    r=c.post('/api/notices/'+n['id']+'/confirm',json=payload);assert r.status_code==200,r.text
    ids=r.json()['task_ids'];t=c.get('/api/tasks/'+ids[0]+'/workflow').json()['task']
    assert t['workflow']['data']['dependencies']==[ids[1]]
    assert t['workflow']['data']['conditions'][0]['state']=='unknown'
    assert finish(c,ids[0]).status_code==422
    assert c.post('/api/notices/'+n['id']+'/confirm',json=payload).json()['task_ids']==ids
    assert len(c.get('/api/tasks').json())==2


@pytest.mark.parametrize('plans',[
    {'0':{'depends_on':[0]}}, {'0':{'depends_on':[1]},'1':{'depends_on':[0]}},
    {'2':{'action_kind':'required'}}, {'0':{'depends_on':[2]}},
])
def test_invalid_plan_rolls_back_the_entire_confirmation(env,plans):
    c=account(env);n=manual(c,notice(c))
    r=c.post('/api/notices/'+n['id']+'/confirm',json={'version':n['version'],'reviewed':True,
          'tasks':[task(n,title='第一步'),task(n,title='第二步')],'plans':plans})
    assert r.status_code==422,r.text
    assert c.get('/api/tasks').json()==[]
    assert c.get('/api/notices/'+n['id']).json()['status']=='draft'


def test_conditions_need_actual_evidence_and_cannot_be_bypassed_by_done(env):
    c=account(env);_,ids=setup_tasks(c);tid=ids[0]
    condition={'id':'condition-a','text':'已获得正式立项通知','state':'unknown','note':''}
    r=workflow(c,tid,conditions=[condition]);assert r.status_code==200,r.text
    assert finish(c,tid).status_code==422
    assert workflow(c,tid,conditions=[{**condition,'state':'met'}]).status_code==422
    assert workflow(c,tid,conditions=[{**condition,'state':'met','note':'本人核对立项名单包含本团队'}]).status_code==200
    assert finish(c,tid).status_code==200
    r=workflow(c,tid,conditions=[{**condition,'state':'not_met','note':'已核实资格被撤回'}])
    assert r.status_code==200,r.text
    assert r.json()['change_review']['state']=='pending'
    assert r.json()['status']=='done'


def test_condition_change_keeps_past_receipt_and_blocks_current_authority(env):
    c=account(env);_,ids=setup_tasks(c);root,child=ids
    condition={'id':'approval','text':'已获立项','state':'met','note':'已核对名单'}
    assert workflow(c,root,conditions=[condition]).status_code==200
    assert workflow(c,root,stage='accepted',prepared_materials=['申请表'],receipt='历史回执',outcome='已受理').status_code==200
    assert finish(c,root).status_code==200
    assert workflow(c,child,dependencies=[root]).status_code==200
    r=workflow(c,root,conditions=[{**condition,'text':'已获本批次立项'}])
    assert r.status_code==200,r.text;t=r.json()
    assert t['workflow']['data']['conditions'][0]['state']=='unknown'
    assert t['workflow']['data']['receipt']=='历史回执' and t['workflow']['data']['stage']=='accepted'
    assert c.get('/api/tasks/'+child+'/workflow').json()['task']['workflow']['blocked']
    candidates=c.get('/api/tasks/'+child+'/workflow').json()['candidates']
    assert next(candidate for candidate in candidates if candidate['id']==root)['conditions_blocked']
    review=t['change_review']
    assert c.post('/api/tasks/'+root+'/change-review',json={'version':review['version'],'task_version':t['version'],'decision':'keep','note':'仍用旧回执'}).status_code==422
    assert c.post('/api/tasks/'+root+'/change-review',json={'version':review['version'],'task_version':t['version'],'decision':'reopen','note':'先核实本批次立项'}).status_code==200


def test_conditional_calendar_changes_are_versioned_and_unknown_gates_block_export(env):
    c=account(env);_,ids=setup_tasks(c);tid=ids[0]
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}}).status_code==200
    condition={'id':'approval','text':'已获得立项资格','state':'unknown','note':''}
    changed=workflow(c,tid,conditions=[condition]).json()
    assert changed['version']==2 and changed['needs_calendar_sync']
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:1}}).status_code==409
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:2}}).status_code==422
    verified=workflow(c,tid,conditions=[{**condition,'state':'met','note':'核对正式名单'}]).json()
    assert verified['version']==3
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:3}}).status_code==200
    # Updating the explanation alone does not invalidate an unchanged calendar snapshot.
    updated=workflow(c,tid,conditions=[{**condition,'state':'met','note':'已核对正式名单及负责人姓名'}]).json()
    assert updated['version']==3


def test_json_import_retains_condition_history_but_requires_reverification(env):
    source=account(env);_,ids=setup_tasks(source)
    condition={'id':'approval','text':'已获正式立项','state':'met','note':'导出前已核实名单'}
    assert workflow(source,ids[0],conditions=[condition]).status_code==200
    other=account(env,'reader');assert import_file(other,source.get('/api/export').json()).status_code==200
    imported=next(t for t in other.get('/api/tasks').json() if t['data']['title']=='准备申请表')
    saved=imported['workflow']['data']['conditions'][0]
    assert saved['state']=='unknown' and saved['note']==condition['note']
    assert finish(other,imported['id']).status_code==422


def test_replacement_requires_current_workflow_version_and_preserves_old_progress(env):
    c=account(env);n,ids=setup_tasks(c);tid=ids[0]
    assert workflow(c,tid,stage='accepted',prepared_materials=['申请表'],receipt='原回执',outcome='已受理').status_code==200
    n=manual(c,c.get('/api/notices/'+n['id']).json())
    current=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    payload={'version':n['version'],'reviewed':True,'tasks':[task(n,title='更新准备事项')],
             'replacements':{'0':tid},'target_versions':{tid:current['version']},
             'plans':{'0':{'action_kind':'required','conditions':['新批次已立项'],'workflow_version':0}}}
    assert c.post('/api/notices/'+n['id']+'/confirm',json=payload).status_code==409
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['version']==current['version']
    payload['plans']['0']['workflow_version']=current['workflow']['version']
    r=c.post('/api/notices/'+n['id']+'/confirm',json=payload);assert r.status_code==200,r.text
    after=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    assert after['workflow']['data']['receipt']=='原回执' and after['workflow']['data']['stage']=='accepted'
    assert after['workflow']['data']['conditions'][0]['state']=='unknown'
    assert after['change_review']['state']=='pending'


def test_model_can_propose_a_plan_but_cannot_supply_a_participation_decision(env):
    from app.ai import validate_extraction,FACT_KEYS
    c=account(env);n=notice(c)
    source=n['sources'][0];section=source['sections'][0]
    item=task(n,evidence=[{'source_id':source['id'],'locator':section['locator'],'quote':section['text']}])
    raw={'title':'准备','summary':'核对','applicability':'needs_review','applicability_reason':'本人核对','facts':{k:{} for k in FACT_KEYS},
         'tasks':[item],'plans':{'0':{'action_kind':'optional','conditions':['已获立项']}}}
    assert validate_extraction(raw,n['sources'],None)['plans'][0]['conditions']==['已获立项']
    raw['plans']['0']['participation']='joined'
    with pytest.raises(ValueError):validate_extraction(raw,n['sources'],None)


def test_condition_change_invalidates_answer_context_and_is_visible_as_unresolved(env):
    from app.context_snapshot import capture,assert_current
    from app.ai import AIError
    from app.grounding import retrieve
    from test_change_review import conversation
    c=account(env);_,ids=setup_tasks(c);chat=conversation(c);uid=c.get('/api/session').json()['user']['id'];db=env[0].state.db
    with db.connect() as conn:snapshot=capture(conn,uid,chat['id'],{'schedule':True})
    assert workflow(c,ids[0],conditions=[{'id':'approval','text':'已获立项','state':'unknown'}]).status_code==200
    with db.connect() as conn:
        with pytest.raises(AIError):assert_current(conn,uid,chat['id'],snapshot)
    sources,_=retrieve(db,uid,chat['id'],[],[{'role':'user','content':'准备申请表可以提交了吗？'}],{},['准备申请表'])
    value=json.loads(next(s for s in sources if s['id']=='task-'+ids[0])['sections'][0]['text'])
    assert value['execution_issues'][0]['code']=='condition'
    assert '不能把旧完成' in value['execution_warning']


def test_optional_declined_is_excluded_from_due_work_but_remains_in_history(env):
    c=account(env);_,ids=setup_tasks(c)
    result=workflow(c,ids[0],action_kind='optional',participation='declined',followup_at='2020-01-01T08:00:00+08:00').json()
    assert result['action_excluded'] and not result['overdue'] and not result['due_soon'] and not result['followup_due']
    assert any(t['id']==ids[0] for t in c.get('/api/tasks').json())
    assert not workflow(c,ids[0],participation='joined').json()['action_excluded']


def test_known_advisory_alias_is_preserved_without_accepting_unknown_ai_fields():
    from copy import deepcopy
    from app.ai import validate_extraction,FACT_KEYS
    raw={'title':'测试通知','summary':'核实资格','applicability':'needs_review','applicability_reason':'资格待核实',
         'facts':{k:{} for k in FACT_KEYS},'tasks':[],'warnings':['待公布名单'],'uncertainties':['待公布名单','具体地点待定']}
    original=deepcopy(raw)
    assert validate_extraction(raw,[],None)['warnings']==['待公布名单','具体地点待定']
    assert raw==original
    for value in ['字符串',{'approval':True},[{'text':'无来源'}],['a'*501]]:
        with pytest.raises(ValueError):validate_extraction({**raw,'uncertainties':value},[],None)
    with pytest.raises(ValueError):validate_extraction({**raw,'approval':True},[],None)
    with pytest.raises(ValueError):validate_extraction({**raw,'warnings':[str(i) for i in range(30)]},[],None)


def test_inline_and_legacy_proposals_preserve_constraints_and_reject_conflicts():
    from app.action_plans import normalize_proposals
    from app.models import Extraction
    from app.notice_references import output_schema
    raw={'tasks':[{'title':'提交','conditions':['已获立项']}],'plans':{'0':{'action_kind':'required','conditions':['已获立项']}}}
    normalized=normalize_proposals(raw)
    assert normalized['tasks']==[{'title':'提交'}] and normalized['plans']==raw['plans']
    assert raw['tasks'][0]['conditions']==['已获立项']
    assert normalize_proposals({'tasks':raw['tasks']})['plans'][0]['conditions']==['已获立项']
    with pytest.raises(ValueError,match='冲突'):normalize_proposals({**raw,'plans':{'0':{'conditions':['不同立项']}}})
    schema=output_schema(Extraction.model_json_schema())
    assert 'plans' not in schema['properties'] and 'DraftPlan' not in schema['$defs']
    assert {'action_kind','depends_on','conditions'}<=set(schema['$defs']['TaskData']['properties'])


def test_workflow_one_migrates_without_losing_history_and_two_restores_conditions(env,tmp_path):
    from app.db import Database,dumps
    from app.backups import restore_database
    c=account(env);_,ids=setup_tasks(c);tid=ids[0];db=env[0].state.db
    assert workflow(c,tid,receipt='迁移前历史回执',next_step='继续核实').status_code==200
    with db.connect(write=True) as conn:
        saved=json.loads(conn.execute('SELECT data FROM task_workflows WHERE task_id=?',(tid,)).fetchone()[0]);saved.pop('conditions')
        conn.execute('UPDATE task_workflows SET data=? WHERE task_id=?',(dumps(saved),tid))
        conn.execute("UPDATE meta SET value='1' WHERE key='workflow_schema_version'")
    migrated=Database(env[1].data_dir/'campus.sqlite3')
    for _ in range(2):
        with migrated.connect() as conn:assert conn.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone()[0]=='2'
        migrated=Database(env[1].data_dir/'campus.sqlite3')
    current=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    assert current['workflow']['data']['conditions']==[] and current['workflow']['data']['receipt']=='迁移前历史回执'
    condition={'id':'approval','text':'本人已获正式立项','state':'met','note':'已核对实际名单'}
    assert workflow(c,tid,conditions=[condition]).status_code==200
    destination=tmp_path/'restored'/'campus.sqlite3';restore_database(env[1].data_dir/'campus.sqlite3',destination)
    restored=Database(destination)
    with restored.connect() as conn:
        value=json.loads(conn.execute('SELECT data FROM task_workflows WHERE task_id=?',(tid,)).fetchone()[0])
        assert value['conditions']==[condition] and value['receipt']=='迁移前历史回执'
        assert conn.execute('PRAGMA foreign_key_check').fetchone() is None
