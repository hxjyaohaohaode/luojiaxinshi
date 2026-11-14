"""Independent campus-policy/collaboration integration audit; no real delivery."""
from datetime import datetime, timezone
import json
import time
import uuid

import pytest

from app import mail_delivery as mail, push_delivery as push
from app.db import dumps
from app.notification_events import channel_events
from app.proactive_policy import delivered_refs
from tests.test_campus_permissions import actors, assign, CLASS2, publication, publish
from tests.test_campus_sprint import make_case, ok
from tests.test_mail_delivery import enable
from tests.test_push_delivery import subscribe, captured
from tests.test_sprint_notifications import preferences
from tests.test_workflow import env, confirm, manual, PASSWORD
from verification_helpers import CapturedMessages


def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat(timespec='seconds')


def set_followup(client,case,at,version=0):
    return ok(client.put('/api/collaboration/'+case['id']+'/followup',json={
        'version':version,'due_at':iso(at) if at is not None else None,'request_id':uuid.uuid4().hex}))


def accept(counselor,case):
    return ok(counselor.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':case['version'],'action':'accept','note':'核对进展','request_id':uuid.uuid4().hex}))


def public_case(env,policy):
    site,manager,counselor,student,other,_=actors(env)
    sent=ok(publish(counselor,{**publication(),**policy}))
    first=student.get('/api/notices').json()[0]
    checked=ok(student.post('/api/notices/'+first['id']+'/materials',json={
        'version':first['version'],'complete':True}))
    tid=confirm(student,manual(student,checked))
    options=ok(student.get('/api/collaboration/tasks/'+tid+'/options'))
    case=ok(student.post('/api/collaboration',json={'task_id':tid,'task_version':options['version'],
        'recipient_id':ok(counselor.get('/api/session'))['user']['id'],
        'note':'本人主动请求核对具体材料','files':[],'request_id':uuid.uuid4().hex}))
    return site,manager,counselor,student,other,accept(counselor,case),first['id'],sent


def connected(env,client,baseline,mode='immediate'):
    preferences(client,collaboration_delivery=mode,quiet_start='',quiet_end='')
    _,cfg=enable(env,client)
    device,_=subscribe(client)
    uid=ok(client.get('/api/session'))['user']['id']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE mail_preferences SET consented_at=? WHERE user_id=?',(baseline,uid))
        conn.execute('UPDATE push_devices SET created_at=? WHERE id=?',(baseline,device))
    return uid,device,cfg


def reconcile_both(db,uid,now):
    with db.connect(write=True) as conn:
        push.reconcile(conn,uid,now)
        mail.reconcile(conn,uid,now)


def case_jobs(db,uid,case):
    result={}
    with db.connect() as conn:
        for table in ('push_outbox','mail_outbox'):
            result[table]=[dict(row) for row in conn.execute(
                'SELECT event_key,payload,state,due_at FROM '+table+' WHERE user_id=?',(uid,))
                if any('collaboration:'+case['id']+':' in ref for ref in json.loads(row['payload']).get('event_refs',[]))]
    return result


def assert_no_pending_case_jobs(jobs):
    assert {table:sum(row['state']=='pending' for row in rows) for table,rows in jobs.items()}=={
        'push_outbox':0,'mail_outbox':0}


@pytest.mark.parametrize('policy',[{'reference_only':True},{'valid_until':'2020-01-01T00:00:00+00:00'}])
def test_campus_reference_and_expired_policy_also_blocks_linked_collaboration_followups(env,policy):
    _,_,_,student,_,case,nid,_=public_case(env,policy)
    now=int(time.time());uid,_,_=connected(env,student,now-60)
    set_followup(student,case,now+300)
    reconcile_both(env[0].state.db,uid,now+300)
    jobs=case_jobs(env[0].state.db,uid,case)
    assert_no_pending_case_jobs(jobs)
    with env[0].state.db.connect() as conn:
        assert not any(key.startswith('collaboration:'+case['id']) for key in push.candidates(conn,uid,now+300))
    assert ok(student.get('/api/notices/'+nid))['publication_context']['external_notifications']=='suppressed'


def test_owner_notice_off_route_suppresses_own_collaboration_clock_but_cannot_target_other_owner(env):
    _,_,counselor,student,other,case,nid,_=public_case(env,{})
    now=int(time.time());uid,_,_=connected(env,student,now-60)
    preferences(student,notice_delivery={nid:'off'})
    set_followup(student,case,now+300)
    current=ok(other.get('/api/proactive/status'))['preferences']
    denied=other.patch('/api/profile',json={'changes':{'notification_preferences':{**current,'notice_delivery':{nid:'immediate'}}},
        'expected':{'notification_preferences':current}})
    assert denied.status_code==422
    assert other.get('/api/notifications/routes',params={'notice_id':nid}).status_code==404
    reconcile_both(env[0].state.db,uid,now+300)
    jobs=case_jobs(env[0].state.db,uid,case)
    assert_no_pending_case_jobs(jobs)
    case=ok(counselor.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':case['version'],'action':'request_supplement','note':'待补交的具体材料','request_id':uuid.uuid4().hex}))
    assert not any(item.get('case_id')==case['id'] for item in ok(student.get('/api/reminders'))['items'])
    case=ok(student.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':case['version'],'action':'resubmit','note':'已重新核对材料','request_id':uuid.uuid4().hex}))
    recipient_items=[item for item in ok(counselor.get('/api/reminders'))['items'] if item.get('case_id')==case['id']]
    assert len(recipient_items)==1 and 'notice_id' not in recipient_items[0]


@pytest.mark.parametrize('operation',['reschedule','cancel','close','revoke','delete'])
def test_pending_followup_ledgers_recheck_changes_before_any_provider_call(env,monkeypatch,operation):
    _,manager,counselor,student,_,case=make_case(env)
    case=accept(counselor,case)
    now=int(time.time());uid,_,cfg=connected(env,student,now-60)
    set_followup(student,case,now+300)
    db=env[0].state.db;reconcile_both(db,uid,now+300)
    queued=case_jobs(db,uid,case)
    assert all(len(rows)==1 and rows[0]['state']=='pending' for rows in queued.values()),queued
    if operation=='reschedule':set_followup(student,case,now+600,version=1)
    elif operation=='cancel':set_followup(student,case,None,version=1)
    elif operation=='close':
        ok(student.post('/api/collaboration/'+case['id']+'/actions',json={
            'version':case['version'],'action':'withdraw','note':'暂停本次协作','request_id':uuid.uuid4().hex}))
    elif operation=='revoke':assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    else:ok(counselor.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    push_calls=captured(monkeypatch);mail_provider=CapturedMessages()
    push.tick(db,now+301);mail.tick(db,cfg,mail_provider,now+301)
    assert push_calls==[] and mail_provider.mail==[]
    assert all(all(row['state']=='cancelled' for row in rows) for rows in case_jobs(db,uid,case).values())
    if operation=='reschedule':
        push.tick(db,now+600);mail.tick(db,cfg,mail_provider,now+600)
        assert len(push_calls)==len(mail_provider.mail)==1
        push.tick(db,now+601);mail.tick(db,cfg,mail_provider,now+601)
        assert len(push_calls)==len(mail_provider.mail)==1


def test_accepted_or_uncertain_followup_is_not_replayed_when_digest_mode_changes(env,monkeypatch):
    _,_,counselor,student,_,case=make_case(env)
    case=accept(counselor,case)
    now=int(time.time());uid,device,cfg=connected(env,student,now-60)
    set_followup(student,case,now+300)
    db=env[0].state.db
    push_calls=captured(monkeypatch);provider=CapturedMessages()
    def ambiguous(*args):raise TimeoutError('synthetic uncertain email submission')
    provider.send_mail=ambiguous
    push.tick(db,now+300);mail.tick(db,cfg,provider,now+300)
    before=case_jobs(db,uid,case)
    assert len(push_calls)==1 and before['push_outbox'][0]['state']=='accepted'
    assert before['mail_outbox'][0]['state']=='uncertain'
    preferences(student,collaboration_delivery='digest')
    with db.connect() as conn:
        wanted={key:value for key,value in push.candidates(conn,uid,now+301).items()
                if key.startswith('collaboration:'+case['id']+':')}
        assert channel_events(wanted,delivered_refs(conn,'push_outbox',uid,device),now-60)=={}
        assert channel_events(wanted,delivered_refs(conn,'mail_outbox',uid),now-60)=={}
    reconcile_both(db,uid,now+301)
    assert case_jobs(db,uid,case)==before


def test_sender_supplement_cannot_enqueue_external_after_recipient_authority_is_revoked(env):
    _,manager,counselor,student,_,case=make_case(env)
    case=accept(counselor,case)
    now=int(time.time());uid,_,_=connected(env,student,now-60)
    supplemented=ok(counselor.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':case['version'],'action':'request_supplement','note':'补一份具体表格','request_id':uuid.uuid4().hex}))
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    reconcile_both(env[0].state.db,uid,now+1)
    jobs=case_jobs(env[0].state.db,uid,case)
    assert_no_pending_case_jobs(jobs)
    # The student's existing receipt is still readable after scope withdrawal.
    assert ok(student.get('/api/collaboration/'+case['id']))['version']==supplemented['version']
