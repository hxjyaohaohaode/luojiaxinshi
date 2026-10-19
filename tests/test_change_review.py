"""Changed official requirements must not silently reuse obsolete completion."""
import json
import sqlite3
from copy import deepcopy

import pytest

from app.backups import restore_database
from app.db import Database
from app.context_snapshot import capture,assert_current
from app.ai import AIError
from test_workflow import env,account,notice,manual,task,confirm
from test_action_workflow import setup_tasks,workflow,proposal,propose,decide
from test_workflow_migration import import_file,separate_steps
from test_workspace import conversation


def current(c,tid):
    return c.get('/api/tasks/'+tid+'/workflow').json()['task']


def edit(c,tid,**values):
    t=current(c,tid)
    return c.put('/api/tasks/'+tid,json={'version':t['version'],'data':{**t['data'],**values},'status':t['status'],'reason':'本人核对个人安排'})


def review(c,tid,decision='keep',**overrides):
    t=current(c,tid)
    payload={'version':t['change_review']['version'],'task_version':t['version'],'decision':decision,'note':'已对照当前要求核实本人的办理影响',**overrides}
    return c.post('/api/tasks/'+tid+'/change-review',json=payload)


def changed_completed(c):
    n,ids=setup_tasks(c);root,child=ids
    workflow(c,child,dependencies=[root]);t=current(c,root)
    c.put('/api/tasks/'+root,json={'version':t['version'],'data':t['data'],'status':'done','reason':'本人已完成旧要求'})
    assert edit(c,root,materials=['申请表','新增签字页']).status_code==200
    return n,ids


def test_completed_predecessor_changed_requirements_needs_review_before_reuse(env):
    c=account(env);n,ids=setup_tasks(c);root,child=ids
    assert workflow(c,child,dependencies=[root]).status_code==200
    t=current(c,root)
    assert c.put('/api/tasks/'+root,json={'version':t['version'],'data':t['data'],'status':'done','reason':'本人已完成旧要求'}).status_code==200
    p=proposal(n,root,kind='supplement')
    p['targets'][0].update(version=2,patch={'materials':['申请表','新增签字页']})
    change=propose(c,n,p);assert decide(c,n,change).status_code==200
    changed=current(c,root)
    assert changed['status']=='done' and changed['data']['notes']=='保留我的备注'
    assert changed['change_review']['state']=='pending'
    assert current(c,child)['workflow']['blocked']
    assert workflow(c,child,stage='submitted',prepared_materials=['申请表'],receipt='旧前提已不够').status_code==422


def test_official_date_becoming_unknown_can_be_saved_without_destroying_personal_reminder(env):
    c=account(env);n,ids=setup_tasks(c);tid=ids[0]
    reminder='2027-10-19T09:00:00+08:00'
    assert edit(c,tid,reminder_at=reminder).status_code==200
    p=proposal(n,tid,text='正式更正：原截止日期作废，新的提交时间另行通知。')
    p['targets'][0].update(version=2,patch={'due_date':None,'due_time':None,'deadline_text':'新的提交时间另行通知'})
    change=propose(c,n,p)
    response=decide(c,n,change)
    assert response.status_code==200,response.text
    t=current(c,tid)
    assert t['data']['due_date'] is None and t['data']['reminder_at']==reminder
    assert t['change_review']['state']=='pending'
    assert c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:t['version']}}).status_code==422
    assert review(c,tid).status_code==422
    assert edit(c,tid,reminder_at=None,planned_at='2027-10-19T10:00:00+08:00').status_code==200
    assert review(c,tid).status_code==200


def test_review_order_reopen_history_and_repeat_resolution(env):
    c=account(env);n,(root,child)=changed_completed(c)
    assert review(c,child).status_code==422
    t=current(c,root);payload={'version':t['change_review']['version'],'task_version':t['version'],
                              'decision':'reopen','note':'新增签字页确实适用于本人，需要补办'}
    first=c.post('/api/tasks/'+root+'/change-review',json=payload)
    assert first.status_code==200,first.text
    assert first.json()['status']=='pending' and first.json()['data']['notes']=='保留我的备注'
    assert c.post('/api/tasks/'+root+'/change-review',json=payload).json()['version']==first.json()['version']
    assert review(c,child).status_code==200
    assert current(c,child)['workflow']['blocked']  # parent is now genuinely incomplete
    history=c.get('/api/tasks/'+root+'/workflow').json()['history']
    assert any(h['action']=='change_reviewed' and json.loads(h['after_json'])['task_status_before']=='done' for h in history)


def test_keep_preserves_verified_history_and_unblocks_after_each_review(env):
    c=account(env);_,(root,child)=changed_completed(c)
    assert review(c,root,note='已向发布方核实，新要求仅适用于未提交者，本人原办理仍有效').json()['status']=='done'
    assert workflow(c,child,stage='submitted',prepared_materials=['申请表'],receipt='本人提交').status_code==422
    assert review(c,child).status_code==200
    assert workflow(c,child,stage='submitted',prepared_materials=['申请表'],receipt='本人提交').status_code==200


def test_newer_change_stale_form_foreign_account_and_blank_decision_are_rejected(env):
    c=account(env);_,(root,_)=changed_completed(c);old=current(c,root);other=account(env,'bob')
    assert other.post('/api/tasks/'+root+'/change-review',json={'version':1,'task_version':3,'decision':'keep','note':'其他账号'}).status_code==404
    assert review(c,root,note='  ').status_code==422
    assert edit(c,root,submission='新的正式提交入口').status_code==200
    assert review(c,root,version=old['change_review']['version'],task_version=old['version']).status_code==409
    causes=current(c,root)['change_review']['data']['causes']
    assert len(causes)==1 and {'materials','submission'}.issubset(causes[0]['fields'])


def test_simple_unstarted_date_change_does_not_require_duplicate_confirmation(env):
    c=account(env);n,ids=setup_tasks(c)
    change=propose(c,n,proposal(n,ids[0]));assert decide(c,n,change).status_code==200
    assert current(c,ids[0])['change_review'] is None


def test_transitive_preview_and_cancelled_predecessor_do_not_change_unrelated_tasks(env):
    c=account(env);n,ids=setup_tasks(c);root,child=ids
    workflow(c,child,dependencies=[root])
    p=proposal(n,root,kind='cancellation');p['targets'][0].update(action='cancel',patch={})
    change=propose(c,n,p)
    assert [t['id'] for t in change['impact'][0]['affected_steps']]==[child]
    assert decide(c,n,change).status_code==200
    assert current(c,child)['change_review']['state']=='pending'
    assert current(c,root)['change_review'] is None


def test_personal_reminder_after_advanced_deadline_requires_repair(env):
    c=account(env);n,ids=setup_tasks(c);tid=ids[0]
    assert edit(c,tid,reminder_at='2027-10-19T09:00:00+08:00').status_code==200
    p=proposal(n,tid);p['targets'][0].update(version=2,patch={'due_date':'2027-10-18'})
    change=propose(c,n,p);assert decide(c,n,change).status_code==200
    assert review(c,tid).status_code==422
    assert current(c,tid)['schedule_issues'][0]['code']=='reminder_at_after_deadline'
    assert edit(c,tid,reminder_at='2027-10-17T09:00:00+08:00').status_code==200
    assert review(c,tid).status_code==200


@pytest.mark.parametrize('parent_first',[True,False])
def test_pending_reviews_survive_split_json_import_and_bind_only_new_owner(env,parent_first):
    c=account(env);notice_ids,ids,_=separate_steps(c);root,child=ids
    t=current(c,root);c.put('/api/tasks/'+root,json={'version':t['version'],'data':t['data'],'status':'done','reason':'已完成旧要求'})
    edit(c,root,materials=['申请表','新增签字页']);export=c.get('/api/export').json();other=account(env,'bob')
    for index in ([0,1] if parent_first else [1,0]):
        part=deepcopy(export);part['notices']=[n for n in export['notices'] if n['id']==notice_ids[index]]
        response=import_file(other,part);assert response.status_code==200,response.text
    imported=other.get('/api/tasks').json();new_root=next(t for t in imported if t['data']['title'].endswith('0'));new_child=next(t for t in imported if t['data']['title'].endswith('1'))
    assert new_child['change_review']['state']=='pending' and new_child['workflow']['blocked']
    assert new_child['change_review']['data']['causes'][0]['source_id']==new_root['id']
    assert new_child['id']!=child and new_root['id']!=root


def test_backup_migration_future_rejection_and_context_freshness(env,tmp_path):
    c=account(env);_,(root,_)=changed_completed(c);chat=conversation(c);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    with db.connect() as conn:snapshot=capture(conn,uid,chat['id'],{'schedule':True})
    backup=tmp_path/'backup.sqlite3';db.backup(backup);restored=tmp_path/'restored.sqlite3';restore_database(backup,restored)
    with Database(restored).connect() as conn:assert conn.execute('SELECT state FROM task_reviews WHERE task_id=?',(root,)).fetchone()[0]=='pending'
    assert review(c,root).status_code==200
    with db.connect() as conn:
        with pytest.raises(AIError):assert_current(conn,uid,chat['id'],snapshot)
    with sqlite3.connect(backup) as conn:conn.execute("UPDATE meta SET value='999' WHERE key='action_review_schema_version'")
    with pytest.raises(ValueError,match='办理复核'):restore_database(backup,tmp_path/'bad.sqlite3')
    with pytest.raises(RuntimeError,match='办理复核'):Database(backup)


def test_deleted_source_invalidates_transitive_completed_progress(env):
    c=account(env);notice_ids,ids,_=separate_steps(c);root,child=ids
    for tid in ids:
        t=current(c,tid)
        assert c.put('/api/tasks/'+tid,json={'version':t['version'],'data':t['data'],'status':'done','reason':'已按旧前提完成'}).status_code==200
    n=manual(c,notice(c));last=confirm(c,n,task(n,title='最后提交'))
    assert workflow(c,last,dependencies=[child]).status_code==200
    n=c.get('/api/notices/'+notice_ids[0]).json()
    assert c.request('DELETE','/api/notices/'+n['id'],json={'version':n['version']}).status_code==200
    t=current(c,child)
    assert t['status']=='done' and t['workflow']['blocked']
    assert t['change_review']['data']['causes'][0]['kind']=='deleted'
    assert current(c,last)['change_review']['state']=='pending'
    assert workflow(c,last,stage='submitted',prepared_materials=['申请表'],receipt='需要有效前提').status_code==422
    assert review(c,last).status_code==422
    # Explicitly verify historical work, then remove a genuinely obsolete dependency.
    assert workflow(c,child,dependencies=[]).status_code==200
    assert review(c,child,note='已核实本人原办理有效，此前置材料不再要求').status_code==200
    assert review(c,last).status_code==200
    assert workflow(c,last,stage='submitted',prepared_materials=['申请表'],receipt='已核实后提交').status_code==200


def test_change_apply_rollback_cannot_leave_partial_review_rows(env):
    c=account(env);n,ids=setup_tasks(c)
    for tid in ids:
        t=current(c,tid)
        assert c.put('/api/tasks/'+tid,json={'version':t['version'],'data':t['data'],'status':'done','reason':'已完成'}).status_code==200
    p=proposal(n,ids[0],kind='supplement')
    p['targets']=[{'task_id':tid,'version':2,'action':'revise','patch':{'materials':['申请表','新要求']}} for tid in ids]
    change=propose(c,n,p)
    edit(c,ids[1],notes='并发修改个人备注')
    assert decide(c,n,change).status_code==409
    assert all(current(c,tid)['change_review'] is None for tid in ids)
    assert all(current(c,tid)['data']['materials']==['申请表'] for tid in ids)


def test_reviewed_conclusion_survives_json_import(env):
    c=account(env);_,(root,_)=changed_completed(c)
    assert review(c,root,decision='reopen').status_code==200
    exported=c.get('/api/export').json();other=account(env,'bob')
    assert import_file(other,exported).status_code==200
    t=next(t for t in other.get('/api/tasks').json() if t['data']['title']=='准备申请表')
    assert t['status']=='pending' and t['change_review']['state']=='reviewed'
    assert t['change_review']['data']['decision']=='reopen'
    assert t['change_review']['note']=='已对照当前要求核实本人的办理影响'


@pytest.mark.parametrize('due_time,reminder,late',[
    (None,'2027-10-20T23:59:59+08:00',False),
    (None,'2027-10-20T16:00:00Z',True),
    ('17:00','2027-10-20T09:00:00Z',False),
    ('17:00','2027-10-20T09:00:01Z',True),
])
def test_schedule_review_respects_date_precision_and_timezones(due_time,reminder,late):
    from app.action_review import schedule_issues
    result=schedule_issues({'due_date':'2027-10-20','due_time':due_time,'reminder_at':reminder})
    assert any(i['blocking'] for i in result)==late


def test_ai_evidence_does_not_treat_obsolete_completion_as_current_authority(env):
    from app.grounding import retrieve
    c=account(env);_,(root,_)=changed_completed(c);chat=conversation(c)
    assert workflow(c,root,next_step='复核新增签字页',receipt='原有提交回执').status_code==200
    uid=c.get('/api/session').json()['user']['id']
    sources,_=retrieve(env[0].state.db,uid,chat['id'],[],[{'role':'user','content':'请结合我的日程与待办，检查准备申请表是否完成以及能否提交材料。'}],{},['准备申请表','提交材料'])
    evidence=next(s for s in sources if s['id']=='task-'+root)
    value=json.loads(evidence['sections'][0]['text'])
    assert value['status']=='done' and value['change_review']['state']=='pending'
    assert '不能作为已满足前提' in value['completion_warning']
    assert value['workflow']['data']['receipt']=='原有提交回执' and '未经学校系统自动核验' in value['workflow_authority']
    scoped,_=retrieve(env[0].state.db,uid,chat['id'],[],[{'role':'user','content':'不要使用我的日程或待办，只根据本条消息说明复核流程。'}],{},['准备申请表'])
    assert all(s['id']!='task-'+root for s in scoped)


def test_review_draft_is_owner_scoped_and_invalidated_by_review_version(env):
    c=account(env);_,(root,_)=changed_completed(c);t=current(c,root)
    key=f"review:{root}:{t['version']}:{t['change_review']['version']}"
    payload={'revision':0,'payload':{'decision':'keep','note':'尚未保存的本人复核说明'}}
    assert c.put('/api/edit-cache/'+key,json=payload).status_code==200
    other=account(env,'bob');assert other.get('/api/edit-cache/'+key).status_code==404
    assert review(c,root).status_code==200
    assert c.put('/api/edit-cache/'+key,json={**payload,'revision':1}).status_code==409


@pytest.mark.parametrize('stage',['supplement','blocked','rejected'])
def test_adverse_result_after_completion_requires_review_before_reusing_progress(env,stage):
    c=account(env);_,ids=setup_tasks(c);root,child=ids
    assert workflow(c,root,stage='accepted',prepared_materials=['申请表'],receipt='本人旧版回执',outcome='已核实受理').status_code==200
    t=current(c,root)
    assert c.put('/api/tasks/'+root,json={'version':t['version'],'data':t['data'],'status':'done','reason':'原要求已完成'}).status_code==200
    assert workflow(c,child,dependencies=[root]).status_code==200
    assert workflow(c,root,stage=stage,outcome='收到新的退回或补正要求，需要核对下一步').status_code==200
    t=current(c,root)
    assert t['status']=='done' and t['change_review']['state']=='pending'
    assert t['workflow']['data']['receipt']=='本人旧版回执'
    assert current(c,child)['workflow']['blocked']
    assert workflow(c,child,stage='submitted',prepared_materials=['申请表'],receipt='尚未核对前提').status_code==422


def test_changing_prerequisites_of_completed_work_invalidates_dependents(env):
    c=account(env);n,ids=setup_tasks(c);root,child=ids
    t=current(c,root);c.put('/api/tasks/'+root,json={'version':t['version'],'data':t['data'],'status':'done','reason':'原要求已完成'})
    assert workflow(c,child,dependencies=[root]).status_code==200
    other=confirm(c,manual(c,notice(c,text='另一则不同的前置材料要求')))
    assert workflow(c,root,dependencies=[other]).status_code==200
    assert current(c,root)['change_review']['data']['causes'][0]['fields']==['dependencies']
    assert current(c,child)['change_review']['state']=='pending'


def test_unconfirmed_change_is_visible_without_overwriting_facts_and_invalidates_answer(env):
    from app.grounding import retrieve
    c=account(env);n,ids=setup_tasks(c);chat=conversation(c);uid=c.get('/api/session').json()['user']['id'];db=env[0].state.db
    with db.connect() as conn:snapshot=capture(conn,uid,chat['id'],{'schedule':True})
    p=proposal(n,ids[0],kind='unverified',targets=[],text='群内转述可能延期，尚未核实。')
    propose(c,n,p)
    with db.connect() as conn:
        with pytest.raises(AIError):assert_current(conn,uid,chat['id'],snapshot)
    sources,_=retrieve(db,uid,chat['id'],[],[{'role':'user','content':'核对我日程中的准备申请表期限。'}],{},['准备申请表'])
    value=json.loads(next(s for s in sources if s['id']=='task-'+ids[0])['sections'][0]['text'])
    assert value['values']['due_date']=='2027-10-20'
    assert value['pending_changes'][0]['kind']=='unverified' and '不把线索当作已生效事实' in value['pending_change_warning']
