"""Local evidence, deduplicated incidents, acknowledgement and recovery."""
from datetime import datetime,timezone,timedelta
import json
from types import SimpleNamespace
import time

from app.backups import restore_database
from app.db import Database,dumps,ident
from app import operations_monitor as monitor
from tests.test_workflow import env,account


def healthy_storage(env,monkeypatch):
    monkeypatch.setattr(monitor.shutil,'disk_usage',lambda _:SimpleNamespace(free=10**12))
    path=env[1].data_dir/'backups'/'auto-engineering.sqlite3'
    path.parent.mkdir(exist_ok=True)
    env[0].state.db.backup(path)


def measurement(state,at=1000):
    return {'evaluated_at':at,'settings':{},'measurements':{'disk:free':{'state':state,'title':'合成磁盘信号','observed_at':at}}}


def test_incident_dedup_acknowledge_recovery_and_recurrence_are_independent(env):
    c=account(env,'admin',role='admin');db=env[0].state.db
    with db.connect(write=True) as conn:
        monitor.reconcile(conn,measurement('problem'))
        monitor.reconcile(conn,measurement('problem',1001))
    data=c.get('/api/admin/monitor').json()
    assert len(data['incidents'])==1 and len(data['events'])==1 and data['unread_events']==1
    rid=data['incidents'][0]['id']
    for _ in range(2):
        result=c.post('/api/admin/monitor/incidents/'+rid+'/acknowledge')
        assert result.status_code==200 and result.json()['state']=='open'
    with db.connect(write=True) as conn:
        monitor.reconcile(conn,measurement('unknown',1002))
    data=c.get('/api/admin/monitor').json()
    assert data['incidents'][0]['state']=='open' and len(data['events'])==2
    with db.connect(write=True) as conn:
        monitor.reconcile(conn,measurement('healthy',1003))
        monitor.reconcile(conn,measurement('healthy',1004))
    data=c.get('/api/admin/monitor').json()
    assert data['incidents'][0]['state']=='resolved' and len(data['events'])==3
    maximum=max(item['id'] for item in data['events'])
    c.post('/api/admin/monitor/seen',json={'through_event_id':maximum}).raise_for_status()
    assert c.get('/api/admin/monitor').json()['unread_events']==0
    with db.connect(write=True) as conn:monitor.reconcile(conn,measurement('problem',1005))
    data=c.get('/api/admin/monitor').json()
    assert len(data['incidents'])==2 and data['unread_events']==1
    assert next(item for item in data['incidents'] if item['state']=='open')['id']!=rid


def test_admin_only_unknown_configuration_and_no_student_delivery(env,monkeypatch):
    c=account(env);admin=account(env,'admin',role='admin');healthy_storage(env,monkeypatch)
    for path in ['/api/admin/monitor','/api/admin/readiness']:
        assert c.get(path).status_code==403
    assert c.post('/api/admin/monitor/scan').status_code==403
    assert c.put('/api/admin/monitor/settings',json={}).status_code==403
    assert c.post('/api/admin/monitor/incidents/x/acknowledge').status_code==403
    assert c.post('/api/admin/monitor/seen',json={'through_event_id':0}).status_code==403
    response=admin.post('/api/admin/monitor/scan')
    assert response.status_code==200,response.text
    data=response.json()['measurements']
    assert data['credentials:coverage']['state']=='unknown'
    assert data['budget:quota']['state']=='unknown'
    assert data['disk:free']['state']=='healthy'
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM push_outbox').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM mail_outbox').fetchone()[0]==0


def test_real_sensor_uses_overdue_age_not_future_schedule_and_stops_after_queue_clears(env,monkeypatch):
    c=account(env,'admin',role='admin');db=env[0].state.db;healthy_storage(env,monkeypatch)
    now=int(time.time());uid=c.get('/api/session').json()['user']['id']
    with db.connect(write=True) as conn:
        for key,due in [('future',now+10000),('old',now-1000)]:
            conn.execute('INSERT INTO mail_outbox(id,user_id,event_key,payload,destination,state,due_at,created_at) VALUES(?,?,?,?,?,?,?,?)',
                         (ident(),uid,key,'{}','test@example.invalid','pending',due,now-99999))
    first=monitor.tick(db,env[1],now)['measurements']['queue:email']
    assert first['state']=='problem' and first['pending']==1 and first['oldest_age_seconds']==1000
    with db.connect(write=True) as conn:conn.execute("UPDATE mail_outbox SET state='cancelled' WHERE event_key='old'")
    second=monitor.tick(db,env[1],now+1)['measurements']['queue:email']
    assert second['state']=='healthy' and second['pending']==0
    data=c.get('/api/admin/monitor').json()
    assert [item['kind'] for item in reversed(data['events']) if item['details'].get('title')=='邮件提醒队列']==['opened','resolved']


def test_source_requires_repeated_observed_failure_and_pause_records_end_of_monitoring(env,monkeypatch):
    c=account(env,'admin',role='admin');db=env[0].state.db;healthy_storage(env,monkeypatch)
    now=int(time.time());uid=c.get('/api/session').json()['user']['id'];sid=ident()
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,1,1)',(sid,uid,'{}'))
        conn.execute('INSERT INTO source_subscriptions(source_id,user_id,config,enabled,error) VALUES(?,?,?,1,?)',(sid,uid,'{}','工程失败，不含原文'))
        conn.execute('INSERT INTO source_acquisition_runs VALUES(?,?,?,?,?,?,?)',(ident(),sid,1,'hash',now-4000,now-3990,dumps({'state':'failed'})))
    assert monitor.collect(db,env[1],now)['measurements']['source:continuous']['state']=='healthy'
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO source_acquisition_runs VALUES(?,?,?,?,?,?,?)',(ident(),sid,1,'hash',now-2000,now-1990,dumps({'state':'partial'})))
    assert monitor.tick(db,env[1],now)['measurements']['source:continuous']['affected_sources']==1
    with db.connect(write=True) as conn:conn.execute('UPDATE source_subscriptions SET enabled=0 WHERE source_id=?',(sid,))
    assert monitor.tick(db,env[1],now+1)['measurements']['source:continuous']['state']=='healthy'
    data=c.get('/api/admin/monitor').json()
    assert sid not in json.dumps(data) and '工程失败' not in json.dumps(data)
    assert next(item for item in data['incidents'] if item['condition_key']=='source:continuous')['state']=='resolved'


def test_operator_expiry_budget_and_restore_are_bound_to_current_instance(env,tmp_path,monkeypatch):
    c=account(env,'admin',role='admin');db=env[0].state.db;healthy_storage(env,monkeypatch)
    now=datetime.now(timezone.utc)
    payload=monitor.MonitorSettings(credential_expiries={'工程邮件凭证':(now-timedelta(days=1)).isoformat()},quota_budget_units=1).model_dump()
    payload['expected_revision']=c.get('/api/admin/monitor').json()['settings_revision']
    result=c.put('/api/admin/monitor/settings',json=payload)
    assert result.status_code==200,result.text
    assert result.json()['measurements']['credential:工程邮件凭证']['state']=='problem'
    assert result.json()['measurements']['credential:工程邮件凭证']['provenance']=='operator_recorded'
    assert c.put('/api/admin/monitor/settings',json={**payload,'quota_budget_units':5}).status_code==409
    invalid=c.put('/api/admin/monitor/settings',json={**payload,'credential_expiries':{'bad':'2027-10-20'}})
    assert invalid.status_code==422
    backup=tmp_path/'old-monitor.sqlite3';target=tmp_path/'restored-monitor.sqlite3';db.backup(backup);restore_database(backup,target)
    restored=Database(target)
    with restored.connect() as conn:
        assert monitor.settings_for(conn).credential_expiries=={}
        iid=monitor.instance(conn)
        assert conn.execute('SELECT count(*) FROM deployment_incidents WHERE instance_id=?',(iid,)).fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM deployment_incidents').fetchone()[0]>=1
