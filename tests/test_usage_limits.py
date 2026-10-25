from dataclasses import replace

import pytest

from app.usage_limits import UsageLimits, check_storage
from app.notice_ingest import ingest_notice
from app.documents import text_source
from tests.test_workflow import env,account,notice,manual,task,confirm


def test_campus_defaults_and_private_usage_endpoint(env):
    c=account(env);notice(c)
    usage=c.get('/api/account/usage').json()
    assert usage['limits']['notices']==10000
    assert usage['limits']['conversations']==2000
    assert usage['limits']['storage_bytes']==10*1024**3
    assert usage['limits']['ai_daily']==1000
    assert usage['used']['notices']==1
    other=account(env,'other')
    assert other.get('/api/account/usage').json()['used']['notices']==0


@pytest.mark.parametrize('raw',['[]','{"unknown":1}','{"notices":false}','{"storage_bytes":0}','{"notices":-1}','{"automation_daily_max":1}'])
def test_capacity_configuration_rejects_ambiguous_values(raw):
    with pytest.raises(ValueError):UsageLimits.parse(raw)


def test_existing_account_can_cross_old_200_notice_limit_and_import_same_export(env):
    c=account(env);uid=c.get('/api/session').json()['user']['id'];db=env[0].state.db
    with db.connect(write=True) as conn:
        for i in range(201):ingest_notice(conn,uid,sources=[text_source('校园历史通知 '+str(i))])
    usage=c.get('/api/account/usage').json()
    assert usage['used']['notices']==201
    other=account(env,'receiver');archive=c.get('/api/export').json()
    preview=other.post('/api/import',json={'data':archive})
    assert preview.status_code==200,preview.text
    response=other.post('/api/import',json={'data':archive,'confirm':True,'digest':preview.json()['digest']})
    assert response.status_code==200,response.text
    assert len(other.get('/api/notices').json())==201


def test_configured_capacity_applies_to_manual_intake_import_and_duplicate_replay(env):
    c=account(env);db=env[0].state.db;db.usage_limits=replace(db.usage_limits,notices=2)
    a=notice(c,'same record');notice(c,'different record')
    assert c.post('/api/notices',data={'body':'third record'}).status_code==413
    assert c.post('/api/notices',data={'body':'same record'}).status_code==200
    other=account(env,'other');notice(other,'already there')
    exported=c.get('/api/export').json();preview=other.post('/api/import',json={'data':exported}).json()
    assert other.post('/api/import',json={'data':exported,'confirm':True,'digest':preview['digest']}).status_code==413
    assert len(other.get('/api/notices').json())==1


def test_conversation_capacity_covers_notice_promotion_and_existing_account(env):
    c=account(env);db=env[0].state.db;db.usage_limits=replace(db.usage_limits,conversations=1)
    response=c.post('/api/conversations',json={'title':'已有对话'})
    assert response.status_code==200,response.text
    n=notice(c)
    assert c.post('/api/notices/'+n['id']+'/conversation',json={'version':n['version']}).status_code==413
    assert c.post('/api/conversations',json={'title':'第二个'}).status_code==413


def test_automation_default_and_maximum_follow_deployment_policy(env):
    c=account(env);db=env[0].state.db;db.usage_limits=replace(db.usage_limits,automation_daily_default=75,automation_daily_max=300)
    before=c.get('/api/notice-automation').json()
    assert before['daily_limit']==75 and not before['enabled']
    assert before['daily_limit_max']==300
    denied=c.put('/api/notice-automation',json={'enabled':False,'daily_limit':301,'version':0})
    assert denied.status_code==422
    allowed=c.put('/api/notice-automation',json={'enabled':False,'daily_limit':300,'version':0})
    assert allowed.status_code==200


def test_storage_policy_is_shared_across_notices_and_conversation_copy(env):
    c=account(env);db=env[0].state.db;n=notice(c,'a source',files=[('files',('original.txt',b'original file','text/plain'))])
    used=c.get('/api/account/usage').json()['used']['storage_bytes']
    db.usage_limits=replace(db.usage_limits,storage_bytes=max(1,used))
    assert c.post('/api/notices/'+n['id']+'/conversation',json={'version':n['version']}).status_code==413


def test_search_query_count_does_not_grow_per_notice(env):
    c=account(env);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    from app.notice_ingest import search_notices
    with db.connect(write=True) as conn:
        for i in range(100):ingest_notice(conn,uid,sources=[text_source('稳定检索 '+str(i))])
        statements=[];conn.set_trace_callback(statements.append)
        records=search_notices(conn,uid,'稳定检索')
        conn.set_trace_callback(None)
    assert len(records)==100
    assert len([s for s in statements if s.lstrip().upper().startswith('SELECT')])<15
