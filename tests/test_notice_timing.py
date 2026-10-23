"""Activity intervals travel with notice evidence, never invented deadlines."""
from copy import deepcopy
from datetime import datetime

from icalendar import Calendar
import pytest

from app.ai import FACT_KEYS, validate_extraction
from app.documents import text_source
from app.insights import build_reminders
from app.models import ScheduledTime
from tests.test_workflow import env, account, notice, manual, task, confirm


TEXT='工程测试：2027年10月20日14:00至16:00参加讲座。2027年10月18日17:00前报名。'


def slot(**changes):
    return {'kind':'event','start_date':'2027-10-20','start_time':'14:00','end_date':'2027-10-20',
            'end_time':'16:00','confirmed':True,'evidence':[],**changes}


def activity(c,**changes):
    n=manual(c,notice(c,text=TEXT));source=n['sources'][0]
    evidence={'source_id':source['id'],'locator':source['sections'][0]['locator'],'quote':TEXT}
    data=task(n,due_date=None,due_time=None,deadline_text='',deadline_confirmed=False,materials=[],
              scheduled=slot(evidence=[evidence]),**changes)
    return confirm(c,n,data),n


def export(c,tid):
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    return c.post('/api/calendar/export',json={'task_ids':[tid],'versions':{tid:t['version']}})


def test_legacy_task_without_scheduled_field_remains_editable(env):
    import json
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n,task(n))
    with env[0].state.db.connect(write=True) as conn:
        data=json.loads(conn.execute('SELECT data FROM tasks WHERE id=?',(tid,)).fetchone()['data'])
        data.pop('scheduled',None)
        conn.execute('UPDATE tasks SET data=? WHERE id=?',(json.dumps(data),tid))
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    result=c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'pending','data':t['data'],'reason':'核对旧记录'})
    assert result.status_code==200,result.text
    assert result.json()['data']['scheduled'] is None


def test_activity_exports_real_duration_without_fake_deadline_and_unconfirmed_cannot_export(env):
    c=account(env);tid,n=activity(c)
    r=export(c,tid);assert r.status_code==200,r.text
    events=Calendar.from_ical(r.content).walk('VEVENT');assert len(events)==1
    event=events[0];assert event['dtstart'].dt.isoformat()=='2027-10-20T06:00:00+00:00'
    assert event['dtend'].dt.isoformat()=='2027-10-20T08:00:00+00:00'
    assert str(event['uid'])==tid+'-scheduled@campus-notice.local'
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task'];data=deepcopy(t['data']);data['scheduled']['confirmed']=False
    assert c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'pending','data':data,'reason':'重新核对活动时间'}).status_code==200
    assert export(c,tid).status_code==422


def test_deadline_and_activity_have_distinct_stable_events_and_only_one_explicit_alarm(env):
    c=account(env);tid,n=activity(c)
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task'];data={**t['data'],'due_date':'2027-10-18','due_time':'17:00',
        'deadline_confirmed':True,'reminder_at':'2027-10-18T08:00:00+08:00'}
    assert c.put('/api/tasks/'+tid,json={'version':t['version'],'status':'pending','data':data,'reason':'补充本人已核对的报名截止时间'}).status_code==200
    assert export(c,tid).status_code==422
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    review=c.post('/api/tasks/'+tid+'/change-review',json={'task_version':t['version'],'version':t['change_review']['version'],
        'decision':'keep','note':'已对照原文分别核对报名截止与讲座时间，提醒仍在报名截止前'})
    assert review.status_code==200,review.text
    result=export(c,tid);assert result.status_code==200,result.text
    events=Calendar.from_ical(result.content).walk('VEVENT')
    assert len(events)==2 and len({str(e['uid']) for e in events})==2
    assert sum(len(e.walk('VALARM')) for e in events)==1
    assert events[0]['dtstart'].dt.day==18 and events[1]['dtstart'].dt.day==20


@pytest.mark.parametrize('changes,expected_end',[
    ({'end_date':None,'end_time':None},None),
    ({'start_time':None,'end_time':None,'end_date':'2027-10-22'},'2027-10-23'),
    ({'end_time':None},None),
])
def test_unknown_activity_end_is_never_filled_and_date_ranges_end_exclusively(changes,expected_end):
    from app.calendar_export import build_calendar
    data=task(None,due_date=None,due_time=None,deadline_confirmed=False,scheduled=slot(**changes))
    e=Calendar.from_ical(build_calendar([{'id':'t','version':1,'updated_at':1,'status':'pending','data':data}])).walk('VEVENT')[0]
    assert (e['dtend'].dt.isoformat() if 'dtend' in e else None)==expected_end


@pytest.mark.parametrize('changes',[{'end_date':'2027-10-19'},{'end_time':'13:00'},{'end_date':None},
                                    {'start_time':'24:00'},{'start_date':'2027-02-30'},{'end_date':'2029-10-20'}])
def test_activity_interval_rejects_impossible_or_ambiguous_values(changes):
    with pytest.raises(ValueError):ScheduledTime.model_validate(slot(**changes))


def test_extraction_requires_exact_time_evidence_and_never_accepts_model_confirmation():
    source=text_source(TEXT);e={'source_id':source['id'],'locator':source['sections'][0]['locator'],'quote':TEXT}
    raw={'title':'讲座通知','summary':'参加讲座','applicability':'needs_review','applicability_reason':'本人核对',
         'facts':{k:{} for k in FACT_KEYS},'warnings':[],
         'tasks':[{'title':'参加讲座','evidence':[e],'scheduled':slot(evidence=[e])}]}
    data=validate_extraction(raw,[source],None)['tasks'][0]
    assert data['due_date'] is None and data['scheduled']['start_time']=='14:00' and data['scheduled']['end_time']=='16:00'
    assert data['scheduled']['confirmed'] is False
    raw['tasks'][0]['scheduled']['end_time']='18:00'
    assert validate_extraction(raw,[source],None)['tasks'][0]['scheduled']['end_time'] is None
    raw['tasks'][0]['scheduled']['end_date']='2027-10-23'
    assert validate_extraction(raw,[source],None)['tasks'][0]['scheduled'] is None


def test_activity_reminders_are_separate_from_overdue_tasks_and_unconfirmed_times_do_not_auto_notify():
    t={'id':'t','status':'pending','data':task(None,due_date=None,due_time=None,scheduled=slot())}
    now=datetime.fromisoformat('2027-10-20T13:00:00+08:00')
    result=build_reminders([t],[],[],now)
    assert [i['kind'] for i in result['items']]==['notice_event']
    assert result['upcoming'][0]['at']=='2027-10-20T13:45:00+08:00'
    t['data']['scheduled']['confirmed']=False
    assert not build_reminders([t],[],[],now)['upcoming']
    assert not build_reminders([t],[],[],datetime.fromisoformat('2027-10-21T13:00:00+08:00'))['items']


def test_transfer_remaps_activity_evidence_and_requires_new_confirmation(env):
    c=account(env);tid,n=activity(c);other=account(env,'other')
    data=c.get('/api/export').json();preview=other.post('/api/import',json={'data':data})
    assert preview.status_code==200,preview.text
    r=other.post('/api/import',json={'data':data,'confirm':True,'digest':preview.json()['digest']});assert r.status_code==200,r.text
    imported=other.get('/api/tasks').json()[0];newslot=imported['data']['scheduled']
    assert newslot['confirmed'] is False and newslot['start_date']=='2027-10-20'
    assert newslot['evidence'][0]['source_id']!=n['sources'][0]['id']
    assert export(other,imported['id']).status_code==422
