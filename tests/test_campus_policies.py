"""Explicit historical backfill, private follow-ups and measured delivery stages."""
from datetime import datetime, timezone
import json
import time
import uuid

from app import campus
from app.db import dumps, ident
from app.campus_policy import notice_publication_context, suppress_external_notice
from app.collaboration import reminders
from tests.test_campus_permissions import actors, assign, CLASS1, CLASS2, publication, publish
from tests.test_campus_sprint import make_case, ok
from tests.test_workflow import env, confirm, manual


def stamp(value):return datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='seconds')


def backfill_payload(client,version=1,reference=False):
    review=ok(client.post('/api/campus/audience-review',json={'audience':'class',**CLASS1}))
    return {'version':version,'audience_review':review['review'],'reference_confirmed':reference}


def test_expired_backfill_requires_version_audience_and_reference_confirmation(env):
    _,manager,counselor,student,new_student,_=actors(env)
    sent=ok(publish(counselor,{**publication(),'valid_until':'2025-01-01T09:00:00+08:00'}))
    assert sent['publication_policy']['expired'] and sent['publication_policy']['valid_until']=='2025-01-01T01:00:00+00:00'
    assert assign(manager,'student-two','student',version=1,**CLASS1).status_code==200
    path='/api/campus/publications/'+sent['id']+'/deliver-new'
    assert counselor.post(path).status_code==422
    assert counselor.post(path,json=backfill_payload(counselor)).status_code==409
    assert new_student.get('/api/notices').json()==[]
    payload=backfill_payload(counselor,reference=True)
    assert counselor.post(path,json={**payload,'version':2}).status_code==409
    result=ok(counselor.post(path,json=payload))
    assert result['delivery']['added']==1 and result['publication_policy']['external_notifications']=='suppressed'
    assert ok(counselor.post(path,json=payload))['delivery']['added']==0
    record=new_student.get('/api/notices').json()[0]
    detail=ok(new_student.get('/api/notices/'+record['id']))
    assert detail['publication_context']['expired']
    assert new_student.get('/api/tasks').json()==[]
    with env[0].state.db.connect() as conn:
        assert suppress_external_notice(conn,record['id'])
        assert notice_publication_context(conn,record['id'])['version']==1
    # A current member change invalidates a reviewed backfill even at equal count.
    assert assign(manager,'student-one','student',version=1,**CLASS2).status_code==200
    assert counselor.post(path,json=payload).status_code==409
    ok(counselor.post('/api/campus/publications/'+sent['id']+'/withdraw',json={'version':1,'reason':'已关闭'}))
    assert counselor.post(path,json=backfill_payload(counselor,version=2,reference=True)).status_code==409


def test_publication_policy_is_explicit_inherited_and_rollback_uses_selected_version(env):
    _,_,counselor,student,_,_=actors(env)
    invalid={**publication(),'valid_until':'2027-03-01T10:00:00'}
    assert publish(counselor,invalid).status_code==422
    saved=ok(counselor.put('/api/campus/drafts/validity-draft',json={
        'version':0,'valid_until':'2028-01-01T09:00:00+08:00','reference_only':True}))
    assert saved['reference_only'] and saved['valid_until']=='2028-01-01T01:00:00+00:00'
    sent=ok(publish(counselor,{**publication(),'valid_until':'2028-01-01T09:00:00+08:00','reference_only':True}))
    path='/api/campus/publications/'+sent['id']
    changed=ok(counselor.post(path+'/correct',json={'version':1,'title':'原文补充','body':'仍为历史参考'}))
    assert changed['publication_policy']['reference_only']
    assert changed['publication_policy']['valid_until']==sent['publication_policy']['valid_until']
    renewed=ok(counselor.post(path+'/correct',json={
        'version':2,'title':'重新明确范围','body':'这是当前正式通知','reference_only':False,'valid_until':None}))
    assert renewed['publication_policy']['valid_until'] is None and not renewed['publication_policy']['reference_only']
    rolled=ok(counselor.post(path+'/rollback',json={'version':3,'target_version':1,'reason':'核对后恢复原正式版本'}))
    assert rolled['publication_policy']==sent['publication_policy']
    history=ok(counselor.get(path))['history']
    assert len(history)==4 and history[1]['publication_policy']['valid_until'] is None
    # Compatibility with old official versions is explicit: no invented expiry.
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('DELETE FROM campus_publication_policy WHERE publication_id=? AND version=1',(sent['id'],))
        from app.campus_policy import stored_policy
        assert stored_policy(conn,sent['id'],1)=={'valid_until':None,'reference_only':False}


def test_reference_notice_retains_owned_task_but_cannot_send_external_catchup(env):
    from app.push_delivery import candidates
    from tests.test_push_delivery import create_task,due_reminder
    _,_,counselor,student,_,_=actors(env)
    ok(publish(counselor,{**publication(),'reference_only':True}))
    first=student.get('/api/notices').json()[0]
    checked=ok(student.post('/api/notices/'+first['id']+'/materials',json={'version':first['version'],'complete':True}))
    historical_task=confirm(student,manual(student,checked))
    _,personal_task=create_task(student)
    now=int(time.time());db=env[0].state.db
    due_reminder(db,historical_task,now);due_reminder(db,personal_task,now)
    uid=ok(student.get('/api/session'))['user']['id']
    with db.connect() as conn:
        planned=candidates(conn,uid,now)
    assert any(personal_task in key for key in planned)
    assert not any(historical_task in key for key in planned)
    assert not any(item['id']==first['id'] for event in planned.values() for item in event.get('received_items',[]))
    assert ok(student.get('/api/tasks/'+historical_task+'/workflow'))['task']['status']=='pending'


def test_followups_are_private_versioned_clocks_not_case_or_task_deadlines(env):
    site,_,counselor,student,other,case=make_case(env)
    path='/api/collaboration/'+case['id']+'/followup';now=int(time.time())
    before_task=ok(student.get('/api/tasks/'+case['task_id']+'/workflow'))['task']
    assert site.get(path).status_code==other.get(path).status_code==404
    assert ok(student.get(path))['version']==ok(counselor.get(path))['version']==0
    data={'version':0,'due_at':stamp(now+600),'request_id':uuid.uuid4().hex}
    saved=ok(student.put(path,json=data))
    assert saved['version']==1 and saved['active'] and saved['private']
    assert ok(student.put(path,json=data))==saved
    assert student.put(path,json={**data,'due_at':stamp(now+1200)}).status_code==409
    assert student.put(path,json={**data,'request_id':uuid.uuid4().hex}).status_code==409
    teacher=ok(counselor.put(path,json={'version':0,'due_at':stamp(now+1200),'request_id':uuid.uuid4().hex}))
    assert teacher['due_at']!=saved['due_at'] and ok(student.get(path))['due_at']==saved['due_at']
    accepted=ok(counselor.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':1,'action':'accept','note':'准备核对','request_id':uuid.uuid4().hex}))
    assert accepted['version']==2 and ok(student.get(path))['version']==1
    uid=ok(student.get('/api/session'))['user']['id'];other_id=ok(other.get('/api/session'))['user']['id']
    with env[0].state.db.connect() as conn:
        assert not any(item['state']=='followup' for item in reminders(conn,uid,now+599))
        due=[item for item in reminders(conn,uid,now+600) if item['state']=='followup']
        assert due==[{'id':case['id'],'title':case['title'],'state':'followup','version':1,'updated_at':now+600}]
        assert reminders(conn,other_id,now+600)==[]
    after_task=ok(student.get('/api/tasks/'+case['task_id']+'/workflow'))['task']
    assert after_task['version']==before_task['version'] and after_task['data']==before_task['data']
    cleared=ok(student.put(path,json={'version':1,'due_at':None,'request_id':uuid.uuid4().hex}))
    assert cleared['version']==2 and not cleared['active']
    with env[0].state.db.connect() as conn:assert not any(item['state']=='followup' for item in reminders(conn,uid,now+600))
    ok(student.put(path,json={'version':2,'due_at':stamp(now+600),'request_id':uuid.uuid4().hex}))
    ok(student.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':2,'action':'withdraw','note':'暂不需要协助','request_id':uuid.uuid4().hex}))
    assert not ok(student.get(path))['active']
    assert student.put(path,json={'version':3,'due_at':stamp(now+1800),'request_id':uuid.uuid4().hex}).status_code==409
    with env[0].state.db.connect() as conn:assert reminders(conn,uid,now+1200)==[]


def test_followup_revocation_rechecks_both_sides_and_never_survives_case_deletion(env):
    from tests.test_workflow import PASSWORD
    _,manager,counselor,student,_,case=make_case(env)
    path='/api/collaboration/'+case['id']+'/followup';now=int(time.time())
    for person in (counselor,student):
        ok(person.put(path,json={'version':0,'due_at':stamp(now+300),'request_id':uuid.uuid4().hex}))
    uid=ok(student.get('/api/session'))['user']['id'];staff=ok(counselor.get('/api/session'))['user']['id']
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    assert counselor.get(path).status_code==404 and not ok(student.get(path))['active']
    with env[0].state.db.connect() as conn:
        assert reminders(conn,uid,now+300)==[] and reminders(conn,staff,now+300)==[]
    ok(counselor.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    assert ok(student.get('/api/collaboration/'+case['id']))['state']=='retained'
    assert student.get(path).status_code==404
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM collaboration_followups').fetchone()[0]==0


def test_publication_channel_metrics_only_count_linked_existing_ledger_evidence(env):
    _,manager,counselor,student,other,_=actors(env)
    sent=ok(publish(counselor,publication()));record=student.get('/api/notices').json()[0]
    uid=ok(student.get('/api/session'))['user']['id'];now=int(time.time());db=env[0].state.db
    with db.connect(write=True) as conn:
        for index in range(2):
            did=ident()
            conn.execute('INSERT INTO push_devices(id,user_id,endpoint,keys_json,created_at) VALUES(?,?,?,?,?)',
                (did,uid,'https://fcm.googleapis.com/synthetic-private-'+did,'{}',now))
            conn.execute('''INSERT INTO push_outbox(id,user_id,device_id,event_key,payload,due_at,created_at,state,finished_at)
                VALUES(?,?,?,?,?,?,?,'accepted',?)''',(ident(),uid,did,'received:'+str(index),dumps({
                    'receipt_refs':[record['id']+':1:profile:review'],'title':'私有标题不得进入管理统计'}),now,now,now))
        for refs,offset,state in (([record['id']+':1:profile:review'],0,'accepted'),
                                  ([record['id']+':1:profile:review'],0,'uncertain'),
                                  ([record['id']+':1:profile:review'],-31*86400,'accepted'),
                                  (['other-notice:1:profile:review'],0,'accepted'),([],0,'accepted')):
            conn.execute('''INSERT INTO mail_outbox(id,user_id,event_key,payload,destination,due_at,created_at,state,finished_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',(ident(),uid,'received:'+ident(),dumps({'receipt_refs':refs}),
                    'private-address@example.invalid',now+offset,now+offset,state,now+offset))
    result=ok(manager.get('/api/campus/publications/'+sent['id']))['delivery']['evidence']
    assert result['channels']['push']['accepted_events']==2 and result['channels']['push']['accepted_recipients']==1
    assert result['channels']['email']['accepted_events']==1 and result['channels']['email']['states']['uncertain']['events']==1
    assert result['opened']['count'] is None and result['explicit_receipt']['count'] is None
    serialized=json.dumps(result,ensure_ascii=False)
    assert 'private-address' not in serialized and 'synthetic-private' not in serialized and '私有标题' not in serialized and uid not in serialized
    assert student.get('/api/campus/publications/'+sent['id']).status_code==other.get('/api/campus/publications/'+sent['id']).status_code==403


def test_official_attachment_rename_keeps_source_citations_bytes_and_name_history(env):
    _,_,counselor,student,other,_=actors(env)
    original=b'unchanged official template'
    sent=ok(publish(counselor,publication(),files=[('files',('旧名称.txt',original,'text/plain'))]))
    pid=sent['id'];nid=student.get('/api/notices').json()[0]['id']
    source=next(s for s in ok(student.get('/api/notices/'+nid))['sources'] if s['kind']=='txt')
    changed=ok(counselor.post('/api/campus/publications/'+pid+'/correct',data={'data':json.dumps({
        'version':1,'title':sent['title'],'body':sent['body'],'keep_attachments':False})},
        files=[('files',('新名称.txt',original,'text/plain'))]))
    current=next(s for s in ok(student.get('/api/notices/'+nid))['sources'] if s['kind']=='txt')
    assert current['id']==source['id'] and current['sha256']==source['sha256'] and current['name']=='新名称.txt'
    assert '旧名称.txt' in current['warning'] and '第2版' in current['warning']
    url=f"/api/notices/{nid}/sources/{source['id']}/download"
    assert student.get(url).content==original and other.get(url).status_code==404
    with env[0].state.db.connect() as conn:
        history=conn.execute("SELECT before_json,after_json FROM audit WHERE notice_id=? AND action='campus_attachment_renamed'",(nid,)).fetchall()
        assert len(history)==1 and json.loads(history[0]['before_json'])['name']=='旧名称.txt'
        assert json.loads(history[0]['after_json'])['name']=='新名称.txt'
        assert conn.execute('SELECT name FROM campus_materials WHERE publication_id=? AND version=1',(pid,)).fetchone()[0]=='旧名称.txt'
    rolled=ok(counselor.post('/api/campus/publications/'+pid+'/rollback',json={'version':2,'target_version':1,'reason':'恢复原文件名'}))
    after=next(s for s in ok(student.get('/api/notices/'+nid))['sources'] if s['kind']=='txt')
    assert rolled['version']==3 and after['id']==source['id'] and after['name']=='旧名称.txt'
    assert after['warning'].count('原件内容一致')==1
    assert student.get(url).content==original
    changes=ok(student.get('/api/notices/'+nid+'/history'))
    rename=next(item for item in changes if item['action']=='campus_attachment_renamed')
    assert json.loads(rename['before_json'])['publication_version']==2
