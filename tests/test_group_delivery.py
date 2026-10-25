"""Signed synthetic callbacks; no platform traffic or real credentials."""
import time

from fastapi import HTTPException

from app import group_delivery
from tests.test_source_subscriptions import group_event
from tests.test_integrations import configured
from tests.test_workflow import env,account


def members(env):
    a,b=account(env),account(env,'bob');external=configured(env);cfg=env[1]
    command=a.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()['authorize_command']
    assert group_event(external,cfg,command).status_code==200
    command=b.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()['command']
    assert group_event(external,cfg,command,member='bob-member',role='member').status_code==200
    return a,b,external,cfg


def test_failed_recipient_is_preserved_without_blocking_others_and_retry_is_idempotent(env,monkeypatch):
    a,b,external,cfg=members(env);db=env[0].state.db
    uid=a.get('/api/session').json()['user']['id'];real=group_delivery.ingest_notice
    def quota(conn,owner,**kwargs):
        if owner==uid:raise HTTPException(413,'通知已达 200 条上限')
        return real(conn,owner,**kwargs)
    monkeypatch.setattr(group_delivery,'ingest_notice',quota)
    for _ in range(2):assert group_event(external,cfg,'全群通知：十月提交申请',mid='quota-message').status_code==200
    assert not a.get('/api/notices').json() and len(b.get('/api/notices').json())==1
    pending=a.get('/api/integrations').json()['qq']['pending_deliveries']
    assert len(pending)==1 and pending[0]['attempts']==1 and '200' in pending[0]['error']
    assert b.post('/api/integrations/qq/deliveries/'+pending[0]['id']+'/retry').status_code==404
    monkeypatch.setattr(group_delivery,'ingest_notice',real)
    retried=a.post('/api/integrations/qq/deliveries/'+pending[0]['id']+'/retry')
    assert retried.status_code==200 and retried.json()['ok']
    assert len(a.get('/api/notices').json())==1 and len(b.get('/api/notices').json())==1
    assert a.get('/api/integrations').json()['qq']['pending_deliveries']==[]
    assert group_event(external,cfg,'全群通知：十月提交申请',mid='quota-message').status_code==200
    assert len(a.get('/api/notices').json())==1


def test_retry_is_bounded_and_unsubscribing_revokes_undelivered_payload(env,monkeypatch):
    a,b,external,cfg=members(env);db=env[0].state.db
    def failed(*args,**kwargs):raise HTTPException(413,'空间已满')
    monkeypatch.setattr(group_delivery,'ingest_notice',failed)
    assert group_event(external,cfg,'待恢复收件原文',mid='failed-message').status_code==200
    now=int(time.time())
    for i in range(1,7):group_delivery.tick(db,cfg.qq_bot_app_id,now+i*7200)
    pending=a.get('/api/integrations').json()['qq']['pending_deliveries']
    assert len(pending)==1 and pending[0]['attempts']==5 and pending[0]['state']=='failed'
    assert a.delete('/api/integrations/qq/groups/private-group').status_code==200
    assert a.get('/api/integrations').json()['qq']['pending_deliveries']==[]
    assert a.post('/api/integrations/qq/deliveries/'+pending[0]['id']+'/retry').status_code==404
    assert len(b.get('/api/integrations').json()['qq']['pending_deliveries'])==1
    assert b.delete('/api/integrations/qq/groups/private-group').status_code==200
    with db.connect() as conn:assert conn.execute('SELECT count(*) FROM qq_group_deliveries').fetchone()[0]==0
