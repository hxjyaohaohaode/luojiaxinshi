from copy import deepcopy
import sqlite3

import pytest

from app.db import Database
from tests.test_workflow import env, account, notice, manual, confirm, task


def receive(c,title,body=None):
    response=c.post('/api/notices',data={'title':title,'body':body or title,'materials_complete':'true','source_label':'学院官网'})
    assert response.status_code==200,response.text
    return response.json()


def preview(c,a,b):
    response=c.post(f"/api/notices/{a['id']}/matter/preview",json={'other_id':b['id']})
    assert response.status_code==200,response.text
    return response.json()


def join(c,a,b,title='奖学金申请'):
    view=preview(c,a,b)
    response=c.post(f"/api/notices/{a['id']}/matter",json={'other_id':b['id'],'token':view['token'],'title':title})
    assert response.status_code==200,response.text
    return response.json()


def related(c,n):return c.get(f"/api/notices/{n['id']}/matter").json()


def test_suggestion_conservative_rounds_and_never_merges_automatically(env):
    c=account(env)
    a=receive(c,'2026年研究生国家奖学金申报通知')
    b=receive(c,'关于2026年研究生国家奖学金申报的补充通知')
    other=receive(c,'2025年研究生国家奖学金申报通知')
    lecture=receive(c,'珞珈讲坛第549讲预告')
    next_lecture=receive(c,'珞珈讲坛第550讲预告')
    state=related(c,a)
    assert state['group'] is None
    assert b['id'] in {n['id'] for n in state['suggestions']}
    assert other['id'] not in {n['id'] for n in state['suggestions']}
    assert next_lecture['id'] not in {n['id'] for n in related(c,lecture)['suggestions']}
    assert len(c.get('/api/notices').json())==5


def test_group_preserves_independent_requirements_deadlines_and_personal_plans(env):
    c=account(env)
    a=manual(c,receive(c,'2026年奖学金申报通知'))
    b=manual(c,receive(c,'2026年奖学金申报延期通知'))
    ta=confirm(c,a,task(a,notes='本人预约老师签字'))
    tb=confirm(c,b,task(b,materials=['补充证明'],submission='交学院办公室',due_date='2027-10-23',deadline_text='2027年10月23日17:00前'))
    before=[c.get('/api/tasks/'+tid+'/workflow').json() for tid in [ta,tb]]
    result=join(c,a,b)
    assert len(result['members'])==2
    assert [c.get('/api/tasks/'+tid+'/workflow').json() for tid in [ta,tb]]==before
    state=related(c,a)
    assert {t['id'] for n in state['group']['members'] for t in n['tasks']}=={ta,tb}
    deadlines={t['id']:t['due_date'] for n in state['group']['members'] for t in n['tasks']}
    assert deadlines=={ta:'2027-10-20',tb:'2027-10-23'}
    assert all(t['deadline_confirmed'] for n in state['group']['members'] for t in n['tasks'])
    records=c.get('/api/notices').json()
    assert len({n['matter']['id'] for n in records})==1
    assert all(n['matter']['member_count']==2 for n in records)


def test_preview_includes_both_existing_groups_and_stale_membership_rejected(env):
    c=account(env)
    a,b,d,e,f=[receive(c,'同一项目通知 '+str(i)) for i in range(5)]
    join(c,a,b);join(c,d,e)
    old=preview(c,a,d)
    assert {n['id'] for n in old['members']}=={a['id'],b['id'],d['id'],e['id']}
    join(c,d,f)
    assert c.post(f"/api/notices/{a['id']}/matter",json={'other_id':d['id'],'token':old['token']}).status_code==409
    assert len(join(c,a,d)['members'])==5
    assert len(c.get('/api/export').json()['notice_matters'])==1


def test_preview_invalidated_by_task_or_workflow_change(env):
    c=account(env);a=manual(c,receive(c,'项目申请通知'));b=receive(c,'项目申请延期通知')
    tid=confirm(c,a,task(a));view=preview(c,a,b)
    with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE tasks SET version=version+1 WHERE id=?',(tid,))
    assert c.post(f"/api/notices/{a['id']}/matter",json={'other_id':b['id'],'token':view['token']}).status_code==409


def test_dismiss_is_versioned_and_owner_scoped(env):
    c=account(env);a=receive(c,'2026年国家奖学金申报通知');b=receive(c,'2026年国家奖学金申报补充通知')
    view=preview(c,a,b)
    assert c.post(f"/api/notices/{a['id']}/matter/dismiss",json={'other_id':b['id'],'token':view['token']}).status_code==200
    assert related(c,a)['suggestions']==[]
    with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE notices SET version=version+1 WHERE id=?',(b['id'],))
    assert related(c,a)['suggestions'][0]['id']==b['id']
    stranger=account(env,'other');foreign=receive(stranger,'2026年国家奖学金申报通知')
    assert stranger.get(f"/api/notices/{a['id']}/matter").status_code==404
    assert c.post(f"/api/notices/{a['id']}/matter/preview",json={'other_id':foreign['id']}).status_code==404
    assert foreign['id'] not in {n['id'] for n in related(c,a)['suggestions']}


def test_detach_and_delete_do_not_leave_single_member_groups(env):
    c=account(env);a,b,d=[receive(c,'测试事项 '+str(i)) for i in range(3)]
    join(c,a,b);join(c,a,d)
    state=related(c,d)
    assert c.request('DELETE',f"/api/notices/{d['id']}/matter",json={'token':state['token']}).status_code==200
    assert related(c,d)['group'] is None
    assert len(related(c,a)['group']['members'])==2
    latest=c.get('/api/notices/'+a['id']).json()
    assert c.request('DELETE','/api/notices/'+a['id'],json={'version':latest['version']}).status_code==200
    assert related(c,b)['group'] is None
    assert c.get('/api/notices/'+b['id']).status_code==200


def test_portable_group_import_is_atomic_repeatable_and_keeps_independent_notices(env):
    c=account(env);a,b=[receive(c,'完整归组样例 '+str(i)) for i in range(2)];join(c,a,b,'完整事项名称')
    exported=c.get('/api/export').json();other=account(env,'receiver')
    pre=other.post('/api/import',json={'data':exported})
    assert pre.status_code==200,pre.text
    assert pre.json()['matter_count']==1
    response=other.post('/api/import',json={'data':exported,'confirm':True,'digest':pre.json()['digest']})
    assert response.status_code==200,response.text
    copied=other.get('/api/notices').json()
    assert len(copied)==2 and copied[0]['matter']['title']=='完整事项名称'
    assert {n['id'] for n in copied}.isdisjoint({a['id'],b['id']})
    assert other.post('/api/import',json={'data':exported,'confirm':True,'digest':pre.json()['digest']}).status_code==200
    assert len(other.get('/api/notices').json())==2
    broken=deepcopy(exported);broken['notice_matters'][0]['notice_ids'][1]='missing-notice'
    third=account(env,'third');pre=third.post('/api/import',json={'data':broken}).json()
    assert third.post('/api/import',json={'data':broken,'confirm':True,'digest':pre['digest']}).status_code==422
    assert third.get('/api/notices').json()==[]


def test_group_backup_and_schema_validation(env,tmp_path):
    c=account(env);a,b=[receive(c,'备份事项 '+str(i)) for i in range(2)];join(c,a,b)
    destination=tmp_path/'matter-backup.sqlite3';env[0].state.db.backup(destination)
    db=Database(destination)
    with db.connect() as conn:assert conn.execute('SELECT count(*) FROM notice_matter_members').fetchone()[0]==2
    with sqlite3.connect(destination) as conn:conn.execute('DROP TABLE notice_relation_dismissals')
    with pytest.raises(ValueError,match='事项归组'):Database(destination)
