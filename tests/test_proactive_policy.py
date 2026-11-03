from datetime import datetime,timezone,timedelta
import json
import pytest
from pydantic import ValidationError
from app.models import NotificationPreferences
from app.proactive_policy import assess,delivery_slot,outside_quiet_hours,preferences
from app import push_delivery as push
from app.notice_automation import mark_profile
from tests.test_workflow import account,env,notice
from tests.test_push_delivery import external_receipt,owner,subscribe,captured,jobs

CST=timezone(timedelta(hours=8))
def stamp(value):return int(datetime.fromisoformat(value).replace(tzinfo=CST).timestamp())
def record(*,quality='passed',relevance='matches_known',tasks=None,plans=None):
    return {'title':'GIS 实习申请','draft':{'applicability':relevance,'quality':{'status':quality},
        'summary':'GIS 实习机会','tasks':[{'scope':'personal','title':'准备申请'}] if tasks is None else tasks,'plans':plans or {}}}

def test_quality_relevance_interest_and_priority_are_independent():
    assert assess(record(),current_draft=True)['priority']=='P1'
    optional=record(plans={'0':{'action_kind':'optional'}})
    assert assess(optional,current_draft=True)['priority']=='P2'
    assert assess(optional,current_draft=True)['delivery']=='opportunity_digest'
    interested=assess(optional,current_draft=True,pref=NotificationPreferences(interest_terms=['GIS']))
    assert interested['priority']=='P2' and interested['delivery']=='near_term'
    assert assess(record(tasks=[]),current_draft=True)['priority']=='P3'
    for quality in ['needs_review','unavailable','unverified']:
        decision=assess(record(quality=quality),current_draft=True,pref=NotificationPreferences(interest_terms=['GIS']))
        assert decision['priority']=='R' and decision['requires_review']
    assert assess(record(),current_draft=False)['priority']=='R'
    assert assess(record(relevance='not_matching'),current_draft=True)['delivery']=='silent'
    rejected=assess(record(relevance='not_matching',quality='needs_review'),current_draft=True)
    assert rejected['relevance']=='needs_review' and rejected['delivery']!='silent'

def test_personal_actions_survive_muting_and_other_peoples_tasks_do_not_make_priority():
    pref=NotificationPreferences(muted_terms=['GIS'])
    assert assess(record(),current_draft=True,pref=pref)['delivery']=='near_term'
    assert assess(record(tasks=[]),current_draft=True,pref=pref)['delivery']=='silent'
    assert assess(record(tasks=[{'scope':'other'}]),current_draft=True)['priority']=='P3'
    malformed={'title':'anything','draft':{'tasks':None,'quality':None}}
    assert assess(malformed,current_draft=True)['priority']=='R'

def test_fixed_digest_windows_and_cross_midnight_quiet_hours_do_not_slide_with_polling():
    pref=NotificationPreferences(quiet_start='22:00',quiet_end='08:00',digest_hour=18)
    assert outside_quiet_hours(stamp('2026-11-02T23:30'),pref)==stamp('2026-11-03T08:00')
    assert outside_quiet_hours(stamp('2026-11-03T03:00'),pref)==stamp('2026-11-03T08:00')
    assert outside_quiet_hours(stamp('2026-11-03T08:00'),pref)==stamp('2026-11-03T08:00')
    daily=assess(record(tasks=[]),current_draft=True,pref=pref)
    key,due=delivery_slot(stamp('2026-11-02T10:00'),daily,pref)
    assert due==stamp('2026-11-02T18:00')
    assert delivery_slot(stamp('2026-11-02T17:00'),daily,pref)==(key,due)
    assert delivery_slot(stamp('2026-11-02T18:00'),daily,pref)[1]==stamp('2026-11-03T18:00')
    optional=assess(record(plans={'0':{'action_kind':'optional'}}),current_draft=True,pref=pref)
    assert delivery_slot(stamp('2026-11-02T13:00'),optional,pref)[1]==stamp('2026-11-02T18:00')

@pytest.mark.parametrize('data',[{'quiet_start':'22:00'},{'quiet_start':'22:00','quiet_end':'22:00'},
    {'quiet_start':'99:00','quiet_end':'08:00'},{'digest_hour':24},{'digest_hour':True},{'interest_terms':['x'*41]}])
def test_bad_preferences_are_rejected(data):
    with pytest.raises(ValidationError):NotificationPreferences(**data)
    assert preferences({'notification_preferences':data}).mode=='digest'

def test_preferences_are_owner_scoped_conflict_checked_and_persisted(env):
    c=account(env);other=account(env,'other')
    before=c.get('/api/proactive/status');assert before.status_code==200,before.text
    pref=before.json()['preferences'];changed={**pref,'mode':'digest','interest_terms':['GIS'],'quiet_start':'22:00','quiet_end':'08:00'}
    response=c.patch('/api/profile',json={'changes':{'notification_preferences':changed},'expected':{'notification_preferences':pref}})
    assert response.status_code==200,response.text
    assert c.get('/api/proactive/status').json()['preferences']==changed
    assert other.get('/api/proactive/status').json()['preferences']['interest_terms']==[]
    assert c.patch('/api/profile',json={'changes':{'notification_preferences':{**pref,'digest_hour':9}},'expected':{'notification_preferences':pref}}).status_code==409
    private=notice(c)
    assert other.get('/api/proactive/notices/'+private['id']).status_code==404
    explanation=c.get('/api/proactive/notices/'+private['id']).json()
    assert explanation['gates']['automatic_receipt'] is False
    assert explanation['assessment']['delivery']=='silent'
    assert other.get('/api/proactive/notices').json()['total']==0

def classify(db,uid,nid,at,*,tasks,plans=None):
    with db.connect(write=True) as conn:
        value=record(tasks=tasks,plans=plans)['draft']
        conn.execute("UPDATE notices SET draft=?,draft_version=version,status='draft',updated_at=? WHERE id=?",(json.dumps(value),at,nid))
        profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
        version=conn.execute('SELECT version FROM notices WHERE id=?',(nid,)).fetchone()[0]
        mark_profile(conn,nid,uid,version,profile)

def test_daily_digest_uses_real_candidate_and_outbox_without_replaying_after_preference_change(env,monkeypatch):
    c=account(env);db=env[0].state.db;uid=owner(db)
    at=stamp('2026-11-02T10:00');device,_=subscribe(c)
    with db.connect(write=True) as conn:conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(at-60,device))
    nid=external_receipt(db,c,uid,at);classify(db,uid,nid,at,tasks=[])
    with db.connect(write=True) as conn:push.reconcile(conn,uid,at+180)
    pending=jobs(db);assert len(pending)==1 and pending[0]['due_at']==stamp('2026-11-02T18:00')
    assert pending[0]['event_key'].startswith('received:daily:')
    sent=captured(monkeypatch);push.tick(db,stamp('2026-11-02T18:01'))
    assert len(sent)==1
    before=c.get('/api/proactive/status').json()['preferences']
    c.patch('/api/profile',json={'changes':{'notification_preferences':{**before,'mode':'all'}},'expected':{'notification_preferences':before}}).raise_for_status()
    push.tick(db,stamp('2026-11-02T18:02'))
    assert len(sent)==1

def test_changing_quiet_hours_reschedules_existing_pending_outbox(env):
    c=account(env);db=env[0].state.db;uid=owner(db);device,_=subscribe(c)
    at=stamp('2026-11-02T23:00');nid=external_receipt(db,c,uid,at)
    with db.connect(write=True) as conn:
        conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(at-60,device));push.reconcile(conn,uid,at)
    before=c.get('/api/proactive/status').json()['preferences']
    changed={**before,'quiet_start':'22:00','quiet_end':'08:00'}
    c.patch('/api/profile',json={'changes':{'notification_preferences':changed},'expected':{'notification_preferences':before}}).raise_for_status()
    with db.connect(write=True) as conn:push.reconcile(conn,uid,at+180)
    assert next(j for j in jobs(db) if j['state']=='pending')['due_at']==stamp('2026-11-03T08:00')

def test_successful_late_analysis_is_a_new_stage_but_does_not_replay_after_restart(env,monkeypatch):
    c=account(env);db=env[0].state.db;uid=owner(db);device,_=subscribe(c)
    at=stamp('2026-11-02T10:00')
    with db.connect(write=True) as conn:conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(at-60,device))
    nid=external_receipt(db,c,uid,at);sent=captured(monkeypatch)
    push.tick(db,at+180);assert len(sent)==1
    classify(db,uid,nid,at+600,tasks=[{'scope':'personal','title':'准备申请'}])
    push.tick(db,at+780);assert len(sent)==2
    push.tick(db,at+800);assert len(sent)==2

def test_daily_digest_delayed_by_quiet_hours_survives_the_next_day(env,monkeypatch):
    c=account(env);db=env[0].state.db;uid=owner(db);device,_=subscribe(c)
    at=stamp('2026-11-02T07:00')
    before=c.get('/api/proactive/status').json()['preferences']
    value={**before,'digest_hour':23,'quiet_start':'22:00','quiet_end':'08:00'}
    c.patch('/api/profile',json={'changes':{'notification_preferences':value},'expected':{'notification_preferences':before}}).raise_for_status()
    with db.connect(write=True) as conn:conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(at-60,device))
    nid=external_receipt(db,c,uid,at);classify(db,uid,nid,at,tasks=[])
    with db.connect(write=True) as conn:push.reconcile(conn,uid,at+180)
    assert jobs(db)[0]['due_at']==stamp('2026-11-03T08:00')
    sent=captured(monkeypatch);push.tick(db,stamp('2026-11-03T08:01'))
    assert len(sent)==1
