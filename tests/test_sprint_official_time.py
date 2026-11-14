"""Verified interval corrections propagate through evidence, dependencies and ICS."""
from copy import deepcopy
from icalendar import Calendar
import pytest

from tests.test_workflow import env,account,notice,manual,task,confirm
from tests.test_notice_timing import activity,slot,export
from tests.test_action_workflow import workflow,propose,decide


def correction(c,nid,tid,interval,text):
    n=c.get('/api/notices/'+nid).json();t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    return propose(c,n,{'notice_version':n['version'],'kind':'correction','text':text,'source_label':'正式更正测试',
        'targets':[{'task_id':tid,'version':t['version'],'action':'revise','patch':{'scheduled':interval}}]})


def test_official_cross_day_correction_preserves_personal_plan_rebinds_evidence_and_updates_calendar(env):
    c=account(env);tid,n=activity(c)
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    updated={**t['data'],'planned_at':'2027-10-20T10:00:00+08:00','reminder_at':'2027-10-20T09:00:00+08:00'}
    c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'pending','data':updated,'reason':'本人安排准备时间'}).raise_for_status()
    before=next(e for e in Calendar.from_ical(export(c,tid).content).walk('VEVENT') if '-scheduled@' in str(e['uid']))
    dependent=manual(c,notice(c,text='工程测试：活动后整理记录。'))
    child=confirm(c,dependent,task(dependent,due_date=None,due_time=None,deadline_confirmed=False,materials=[]))
    workflow(c,child,dependencies=[tid]).raise_for_status()
    interval=slot(start_date='2027-10-21',start_time='23:00',end_date='2027-10-22',end_time='01:00',confirmed=False)
    change=correction(c,n['id'],tid,interval,'正式更正：讲座改为2027年10月21日23:00开始，2027年10月22日01:00结束。')
    assert change['impact'][0]['diff']['scheduled']['before']['start_date']=='2027-10-20'
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['data']['scheduled']['start_date']=='2027-10-20'
    assert decide(c,n,change,verified=False).status_code==422
    result=decide(c,n,change);assert result.status_code==200,result.text
    assert decide(c,n,change).json()['replayed']
    changed=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    assert changed['data']['planned_at']==updated['planned_at'] and changed['data']['reminder_at']==updated['reminder_at']
    assert changed['data']['notes']==updated['notes']
    assert changed['data']['scheduled']['confirmed']
    assert changed['data']['scheduled']['evidence'][0]['source_id']!=n['sources'][0]['id']
    assert changed['needs_calendar_sync'] and changed['change_review']['state']=='pending'
    # The bounded projection must retain dependency impact without loading every task.
    page=c.get('/api/tasks/page',params={'ids':child}).json()
    assert page['items'][0]['change_review']['state']=='pending'
    assert export(c,tid).status_code==422
    c.post('/api/tasks/'+tid+'/change-review',json={'task_version':changed['version'],'version':changed['change_review']['version'],
        'decision':'keep','note':'已核对新时段、个人计划及提醒安排'}).raise_for_status()
    after=next(e for e in Calendar.from_ical(export(c,tid).content).walk('VEVENT') if '-scheduled@' in str(e['uid']))
    assert str(before['uid'])==str(after['uid']) and int(after['sequence'])>int(before['sequence'])
    assert after['dtstart'].dt.isoformat()=='2027-10-21T15:00:00+00:00'
    assert after['dtend'].dt.isoformat()=='2027-10-21T17:00:00+00:00'
    other=account(env,'other');archive=c.get('/api/export').json()
    preview=other.post('/api/import',json={'data':archive});assert preview.status_code==200,preview.text
    restored=other.post('/api/import',json={'data':archive,'confirm':True,'digest':preview.json()['digest']})
    assert restored.status_code==200,restored.text
    restored_task=next(t for t in other.get('/api/tasks').json() if t['data'].get('scheduled'))
    assert restored_task['data']['scheduled']['confirmed'] is False


@pytest.mark.parametrize('value,text',[
    (slot(end_date=None,end_time=None),'正式更正：2027年10月20日14:00开始讲座，结束时刻待通知。'),
    (None,'正式更正：原定讲座的活动时段撤回，新时段待正式公告。'),
])
def test_correction_can_withdraw_end_or_whole_interval_without_inventing_times(env,value,text):
    c=account(env);tid,n=activity(c);change=correction(c,n['id'],tid,value,text)
    response=decide(c,n,change);assert response.status_code==200,response.text
    data=c.get('/api/tasks/'+tid+'/workflow').json()['task']['data']
    assert data['scheduled'] is None if value is None else data['scheduled']['end_time'] is None
    assert data['due_date'] is None and data['due_time'] is None


def test_unsupported_official_time_and_foreign_decision_roll_back_all_changes(env):
    c=account(env);other=account(env,'other');tid,n=activity(c)
    bad=slot(start_date='2027-10-25',end_date='2027-10-25')
    change=correction(c,n['id'],tid,bad,'正式更正：讲座改为2027年10月21日14:00至16:00。')
    assert decide(other,n,change).status_code==404
    assert decide(c,n,change).status_code==422
    current=c.get('/api/notices/'+n['id']).json()
    assert len(current['sources'])==len(n['sources'])
    assert current['tasks'][0]['data']['scheduled']['start_date']=='2027-10-20'
