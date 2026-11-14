"""Explicit per-category consent, valid windows and durable digest identities."""
from copy import deepcopy
from datetime import datetime
import json

from app.db import dumps
from app.models import NotificationPreferences
from app.notification_events import apply_policy,channel_events
from app.push_delivery import candidates,reconcile
from tests.test_workflow import env,account
from tests.test_push_delivery import owner,subscribe,jobs,captured
from tests.test_schedule import payload


def stamp(text):return int(datetime.fromisoformat(text+'+08:00').timestamp())


def preferences(c,**changes):
    current=c.get('/api/proactive/status').json()['preferences']
    result=c.patch('/api/profile',json={'changes':{'notification_preferences':{**current,**changes}},'expected':{'notification_preferences':current}})
    assert result.status_code==200,result.text


def event(at,expires,group='task'):
    return {'due_at':at,'expires_at':expires,'created_at':0,'category':group,
            'payload':{'user_id':'test','title':'私有测试','body':'','url':'/#tasks','tag':'task'}}


def test_quiet_window_does_not_send_after_official_window_and_urgent_bypass_is_opt_in():
    at=stamp('2027-10-20T23:00');end=stamp('2027-10-21T07:00')
    pref=NotificationPreferences(quiet_start='22:00',quiet_end='08:00')
    original={'deadline:a':event(at,end),'change:b':event(at,end)}
    assert apply_policy(deepcopy(original),pref,at)=={}
    plan=apply_policy(deepcopy(original),pref,at,include_suppressed=True)
    assert all(v['policy']['suppressed'] and '晚于' in v['policy']['reason'] for v in plan.values())
    pref.allow_urgent_during_quiet=True
    assert set(apply_policy(deepcopy(original),pref,at))=={'change:b'}
    assert apply_policy(deepcopy(original),pref,at)['change:b']['due_at']==at


def test_digest_combines_current_items_and_never_repeats_accepted_components():
    at=stamp('2027-10-20T12:00');end=stamp('2027-10-21T22:00')
    planned=apply_policy({'reminder:a':event(at,end),'reminder:b':event(at+60,end)},NotificationPreferences(task_delivery='digest'),at)
    group=channel_events(planned,set(),at-1)
    assert len(group)==1
    key,value=next(iter(group.items()))
    assert key.startswith('digest:task:') and value['payload']['event_refs']==['reminder:a','reminder:b']
    assert '2项' in value['payload']['title'] and '私有测试' not in value['payload']['body']
    assert channel_events(planned,{'reminder:a','reminder:b'},at-1)=={}
    # A new or withdrawn member must not cause the accepted remainder to ring.
    planned.pop('reminder:b')
    assert channel_events(planned,{'reminder:a'},at-1)=={}


def test_arrangement_explicit_opt_in_stable_note_edits_and_new_device_baseline(env):
    c=account(env);db=env[0].state.db;uid=owner(db)
    at=stamp('2027-10-20T13:45');args=payload(start_date='2027-10-20',end_date='2027-10-20',start_time='14:00',end_time='15:00')
    item=c.post('/api/arrangements',json=args).json()
    with db.connect() as conn:assert not candidates(conn,uid,at)
    result=c.put('/api/arrangements/'+item['id'],json={'version':item['version'],'data':{**item['data'],'reminder_minutes':15}})
    assert result.status_code==200,result.text
    item=result.json()
    with db.connect() as conn:before=candidates(conn,uid,at)
    assert len(before)==1 and next(iter(before)).startswith('arrangement:')
    result=c.put('/api/arrangements/'+item['id'],json={'version':item['version'],'data':{**item['data'],'notes':'修改私人笔记不重复触发'}})
    with db.connect() as conn:assert set(candidates(conn,uid,at))==set(before)
    assert channel_events(before,set(),at+1)=={}
    assert len(channel_events(before,set(),at-1))==1
    changed=result.json()
    c.put('/api/arrangements/'+item['id'],json={'version':changed['version'],'data':{**changed['data'],'start_time':'14:30'}}).raise_for_status()
    with db.connect() as conn:assert not set(candidates(conn,uid,at)).intersection(before)


def test_arrangement_delivery_rechecks_deleted_records_and_deduplicates_after_restart(env,monkeypatch):
    from app import push_delivery
    from app.db import Database
    c=account(env);db=env[0].state.db;uid=owner(db);device,_=subscribe(c)
    at=stamp('2027-10-20T13:45')
    item=c.post('/api/arrangements',json=payload(start_date='2027-10-20',end_date='2027-10-20',start_time='14:00',end_time='15:00',reminder_minutes=15)).json()
    with db.connect(write=True) as conn:
        conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(at-60,device));reconcile(conn,uid,at)
    assert len(jobs(db))==1
    calls=captured(monkeypatch)
    push_delivery.tick(Database(db.path),at);push_delivery.tick(db,at+1)
    assert len(calls)==1 and jobs(db)[0]['state']=='accepted'
    preferences(c,arrangement_delivery='digest')
    with db.connect(write=True) as conn:reconcile(conn,uid,at+2)
    assert len(jobs(db))==1
    c.request('DELETE','/api/arrangements/'+item['id'],json={'version':1}).raise_for_status()
    with db.connect() as conn:assert candidates(conn,uid,at)=={}


def test_category_off_disables_in_app_but_in_app_only_preserves_it(env):
    c=account(env)
    from datetime import timedelta
    from app.schedule import CST
    date=(datetime.now(CST)+timedelta(days=1)).date().isoformat()
    c.post('/api/arrangements',json=payload(start_date=date,end_date=date)).raise_for_status()
    preferences(c,arrangement_delivery='off')
    assert not any(item.get('arrangement_id') for item in c.get('/api/reminders').json()['items'])
    preferences(c,arrangement_delivery='in_app')
    assert any(item.get('arrangement_id') for item in c.get('/api/reminders').json()['items'])


def test_portable_import_never_restores_arrangement_or_category_delivery_consent(env):
    c=account(env);other=account(env,'other')
    c.post('/api/arrangements',json=payload(reminder_minutes=15)).raise_for_status()
    preferences(c,collaboration_delivery='immediate',allow_urgent_during_quiet=True)
    backup=c.get('/api/export').json();preview=other.post('/api/import',json={'data':backup})
    assert preview.status_code==200,preview.text
    response=other.post('/api/import',json={'data':backup,'confirm':True,'digest':preview.json()['digest'],'apply_profile':True})
    assert response.status_code==200,response.text
    assert other.get('/api/arrangements').json()[0]['data']['reminder_minutes'] is None
    pref=other.get('/api/proactive/status').json()['preferences']
    assert pref['collaboration_delivery']=='in_app' and not pref['allow_urgent_during_quiet']


def test_matrix_and_plan_are_authenticated_owner_scoped_and_do_not_claim_device_display(env):
    c=account(env);other=account(env,'other')
    c.post('/api/arrangements',json=payload(title='仅自己可见',start_date='2099-10-20',end_date='2099-10-20',reminder_minutes=15)).raise_for_status()
    matrix=c.get('/api/notifications/matrix').json()
    assert matrix['preferences']['collaboration_delivery']=='in_app'
    assert '未知' in matrix['receipt_meanings']['accepted']
    assert other.get('/api/notifications/plan').json()['total']==0
    assert c.get('/api/notifications/plan?limit=101').status_code==422
    assert 'endpoint' not in json.dumps(matrix)


def test_explicit_all_enabled_devices_policy_deduplicates_per_device(env,monkeypatch):
    from app import push_delivery
    c=account(env);db=env[0].state.db
    a,_=subscribe(c);b,binding=subscribe(c)
    at=stamp('2027-10-20T13:45')
    c.post('/api/arrangements',json=payload(start_date='2027-10-20',end_date='2027-10-20',start_time='14:00',end_time='15:00',reminder_minutes=15)).raise_for_status()
    with db.connect(write=True) as conn:conn.execute('UPDATE push_devices SET created_at=?',(at-60,))
    calls=captured(monkeypatch)
    push_delivery.tick(db,at);push_delivery.tick(db,at+1)
    assert {call['device']['id'] for call in calls}=={a,b} and len(calls)==2
    status=c.get('/api/push/status').json()
    assert status['device_policy']=='all_enabled_devices'
    c.request('DELETE','/api/push/subscriptions',json={'endpoint':binding['endpoint']}).raise_for_status()
    assert {item['id'] for item in c.get('/api/push/status').json()['devices']}=={a}
