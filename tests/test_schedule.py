"""Engineering fixtures for persistent schedules, ownership and civil time exports."""
import uuid
import pytest

from icalendar import Calendar
from test_workflow import env, account


def payload(**overrides):
    return {'data': {'title': '【工程测试】校园课程', 'category': 'course', 'start_date': '2026-10-13', 'end_date': '2026-10-13', 'start_time': '14:05', 'end_time': '16:30', **overrides}, 'request_id': uuid.uuid4().hex}


def test_arrangement_persistence_idempotency_isolation_and_versions(env):
    c=account(env);other=account(env,'bob');data=payload(repeat='biweekly',repeat_until='2027-01-12')
    r=c.post('/api/arrangements',json=data);assert r.status_code==200,r.text
    record=r.json();eid=record['id']
    assert c.post('/api/arrangements',json=data).json()['id']==eid
    conflict=c.post('/api/arrangements',json={**data,'data':{**data['data'],'title':'修改过的重试草稿'}})
    assert conflict.status_code==409
    assert '草稿已保留' in conflict.json()['detail']
    assert c.get('/api/arrangements').json()[0]['data']['title']==data['data']['title']
    assert len(c.get('/api/arrangements').json())==1
    assert other.get('/api/arrangements').json()==[]
    update={'data':{**record['data'],'location':'工程测试教室'},'version':record['version']}
    assert other.put('/api/arrangements/'+eid,json=update).status_code==404
    changed=c.put('/api/arrangements/'+eid,json=update);assert changed.status_code==200
    assert c.put('/api/arrangements/'+eid,json=update).status_code==409
    assert c.request('DELETE','/api/arrangements/'+eid,json={'version':1}).status_code==409
    exported=c.get('/api/export').json();assert exported['arrangements'][0]['data']['location']=='工程测试教室'
    assert other.request('DELETE','/api/arrangements/'+eid,json={'version':2}).status_code==404
    assert c.request('DELETE','/api/arrangements/'+eid,json={'version':2}).status_code==200
    assert c.get('/api/arrangements').json()==[]


def test_arrangement_validation_before_storage(env):
    c=account(env)
    bad=[{'end_time':'13:00'},{'start_date':'2026-02-30'},{'end_date':'2026-10-12'},{'end_date':'2027-10-13'},
         {'start_time':None},{'repeat':'weekly'},{'repeat':'weekly','repeat_until':'2029-10-13'},
         {'repeat':'weekly','repeat_until':'2026-11-13','end_date':'2026-10-14'},{'repeat_until':'2026-11-13'},
         {'start_time':'9:00'},{'category':'official'},{'title':'   '}]
    for changes in bad:
        r=c.post('/api/arrangements',json=payload(**changes));assert r.status_code==422,(changes,r.text)
    assert c.get('/api/arrangements').json()==[]


def test_arrangement_calendar_exports_recurrence_timezone_and_all_day(env):
    c=account(env);a=c.post('/api/arrangements',json=payload(repeat='biweekly',repeat_until='2027-01-12',notes='逗号,分号;换行\n第二行')).json()
    b=c.post('/api/arrangements',json=payload(title='跨天安排',start_date='2026-12-31',end_date='2027-01-02',start_time=None,end_time=None)).json()
    body={'ids':[a['id'],b['id']], 'versions':{a['id']:1,b['id']:1}}
    r=c.post('/api/arrangements/export',json=body);assert r.status_code==200,r.text
    events=Calendar.from_ical(r.content).walk('VEVENT');assert len(events)==2
    assert events[0]['dtstart'].dt.hour==6 and events[0]['dtstart'].dt.minute==5
    assert events[0]['rrule']['INTERVAL']==[2] and events[0]['rrule']['UNTIL'][0].hour==15
    assert '第二行' in str(events[0]['description'])
    assert events[1]['dtend'].dt.isoformat()=='2027-01-03'
    assert str(events[0]['uid']).startswith(a['id'])
    body['versions'][a['id']]=99;assert c.post('/api/arrangements/export',json=body).status_code==409
    body['versions']={};assert c.post('/api/arrangements/export',json=body).status_code==422


def test_arrangement_backup_restores_data(env,tmp_path):
    from app.backups import restore_database
    from app.db import Database
    c=account(env);a=c.post('/api/arrangements',json=payload()).json()
    backup=tmp_path/'backup.sqlite3';env[0].state.db.backup(backup)
    restored=tmp_path/'restored.sqlite3';restore_database(backup,restored)
    with Database(restored).connect() as db:
        assert db.execute('SELECT id FROM arrangements').fetchone()[0]==a['id']
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_arrangement_drafts_are_owner_scoped_and_reject_stale_versions(env):
    c=account(env);other=account(env,'bob');a=c.post('/api/arrangements',json=payload()).json()
    key='arrangement:'+a['id']+':1';url='/api/edit-cache/'+key
    draft={'revision':0,'payload':{'data':a['data'],'request_id':uuid.uuid4().hex}}
    assert c.put('/api/edit-cache/arrangement-new',json=draft).status_code==200
    assert other.get('/api/edit-cache/arrangement-new').json()['payload'] is None
    assert c.put(url,json=draft).status_code==200
    assert other.get(url).status_code==404
    assert c.put('/api/arrangements/'+a['id'],json={'version':1,'data':{**a['data'],'title':'Changed'}}).status_code==200
    assert c.get(url).status_code==409
    assert c.put(url,json={'revision':1,'payload':None}).status_code==200
    c.request('DELETE','/api/arrangements/'+a['id'],json={'version':2})
    with env[0].state.db.connect() as db:
        assert db.execute('SELECT count(*) FROM edit_caches WHERE cache_key=?',(key,)).fetchone()[0]==0


def test_semester_configuration_preserves_explicit_dates_without_moving_courses(env):
    c=account(env);a=c.post('/api/arrangements',json=payload()).json()
    assert c.put('/api/profile',json={'semester':'工程测试学期','semester_start':'2026-09-07'}).status_code==200
    assert c.get('/api/session').json()['user']['profile']['semester_start']=='2026-09-07'
    assert c.get('/api/arrangements').json()[0]['data']==a['data']
    assert c.put('/api/profile',json={'semester_start':'2026-02-30'}).status_code==422


def test_creation_receipt_survives_edits_and_deletion_without_recreating(env):
    c=account(env);other=account(env,'bob');request=payload()
    route='/api/arrangements/requests/'+request['request_id']
    assert c.get(route).json()=={'state':'missing','arrangement':None}
    saved=c.post('/api/arrangements',json=request).json()
    assert c.get(route).json()=={'state':'saved','arrangement':saved}
    assert other.get(route).json()=={'state':'missing','arrangement':None}
    changed=c.put('/api/arrangements/'+saved['id'],json={'version':1,'data':{**saved['data'],'title':'后来已经修改'}}).json()
    assert c.get(route).json()['arrangement']==changed
    assert c.request('DELETE','/api/arrangements/'+saved['id'],json={'version':2}).status_code==200
    assert c.get(route).json()=={'state':'deleted','arrangement':None}
    replay=c.post('/api/arrangements',json=request)
    assert replay.status_code==409
    assert '删除' in replay.json()['detail']
    assert c.get('/api/arrangements').json()==[]
    # The key is scoped to one account; a different owner can use the same key.
    assert other.post('/api/arrangements',json=request).status_code==200
    assert c.get(route).json()['state']=='deleted'


def test_deleted_arrangement_request_cannot_be_replayed(env):
    c=account(env);request=payload();saved=c.post('/api/arrangements',json=request).json()
    assert c.request('DELETE','/api/arrangements/'+saved['id'],json={'version':1}).status_code==200
    assert c.post('/api/arrangements',json=request).status_code==409
    assert c.get('/api/arrangements').json()==[]


def test_receipts_migrate_existing_arrangements_and_cover_imported_rows(env):
    from app.db import Database, dumps, ident
    c=account(env);request=payload();saved=c.post('/api/arrangements',json=request).json()
    db=env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute('DROP TRIGGER arrangements_remember_creation')
        conn.execute('DROP TABLE arrangement_receipts')
        conn.execute("DELETE FROM meta WHERE key='arrangement_receipt_schema_version'")
    Database(db.path);Database(db.path)
    assert c.get('/api/arrangements/requests/'+request['request_id']).json()['arrangement']['id']==saved['id']
    with db.connect(write=True) as conn:
        row=conn.execute('SELECT * FROM arrangements WHERE id=?',(saved['id'],)).fetchone()
        imported=ident();key='import_'+uuid.uuid4().hex
        conn.execute('INSERT INTO arrangements(id,user_id,request_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',(imported,row['user_id'],key,dumps(saved['data']),1,1))
        assert conn.execute('SELECT count(*) FROM arrangement_receipts').fetchone()[0]==2
    assert c.get('/api/arrangements/requests/'+key).json()['arrangement']['id']==imported


def test_receipt_tombstones_survive_backup_and_contain_no_deleted_text(env,tmp_path):
    from app.backups import restore_database
    from app.db import Database
    c=account(env);request=payload(notes='删除后的私人备注');saved=c.post('/api/arrangements',json=request).json()
    c.request('DELETE','/api/arrangements/'+saved['id'],json={'version':1})
    backup=tmp_path/'backup.sqlite3';env[0].state.db.backup(backup)
    restored=tmp_path/'restored.sqlite3';restore_database(backup,restored)
    with Database(restored).connect() as conn:
        receipt=dict(conn.execute('SELECT * FROM arrangement_receipts').fetchone())
        assert set(receipt)=={'user_id','request_id','arrangement_id','created_at'}
        assert receipt['request_id']==request['request_id']
        assert conn.execute('SELECT count(*) FROM arrangements').fetchone()[0]==0
        conn.execute('DELETE FROM users WHERE id=?',(receipt['user_id'],))
        assert conn.execute('SELECT count(*) FROM arrangement_receipts').fetchone()[0]==0


@pytest.mark.parametrize('damage',['future','missing'])
def test_incompatible_receipts_block_open_and_restore(tmp_path,damage):
    from app.backups import restore_database
    from app.db import Database
    import sqlite3
    path=tmp_path/'source.sqlite3';Database(path)
    with sqlite3.connect(path) as conn:
        if damage=='future':conn.execute("UPDATE meta SET value='999' WHERE key='arrangement_receipt_schema_version'")
        else:conn.execute('DROP TABLE arrangement_receipts')
    with pytest.raises(RuntimeError,match='安排提交记录'):Database(path)
    destination=tmp_path/'restored.sqlite3'
    with pytest.raises(ValueError,match='安排提交记录'):restore_database(path,destination)
    assert not destination.exists()


def test_receipt_request_id_validation(env):
    c=account(env)
    for key in ['short','a'*81,'a'*16+'!']:
        assert c.get('/api/arrangements/requests/'+key).status_code==422
