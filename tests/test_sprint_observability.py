"""Evidence levels, instance-bound verification and owner request traces."""
from datetime import datetime,timezone
import json
import re

from app.backups import restore_database
from app.db import Database,dumps,ident
from app.notification_routing import notice_modes
from app.proactive_policy import preferences
from tests.test_workflow import env,account,notice,manual,task,confirm
from tests.test_sprint_notifications import preferences as set_preferences


def test_readiness_is_admin_only_and_presence_never_claims_end_to_end(env):
    c=account(env);admin=account(env,'admin',role='admin')
    assert c.get('/api/admin/readiness').status_code==403
    assert c.post('/api/admin/readiness/evidence',json={}).status_code==403
    result=admin.get('/api/admin/readiness')
    assert result.status_code==200,result.text
    data=result.json()
    assert data['services']['model']['configured'] is False
    assert data['services']['model']['connection_state']=='not_observed'
    assert all(v['end_to_end'] is None for v in data['services'].values())
    assert not any(key in result.text for key in ['api_key','access_key_secret','destination','password','digest'])


def test_operator_evidence_is_labeled_and_not_inherited_by_restored_environment(env,tmp_path):
    admin=account(env,'admin',role='admin');db=env[0].state.db
    payload={'kind':'push_device','result':'passed','environment':'工程测试设备记录',
             'evidence':'明确标记为合成测试，未表示实际手机已经验收。','observed_at':datetime.now(timezone.utc).isoformat()}
    result=admin.post('/api/admin/readiness/evidence',json=payload)
    assert result.status_code==200 and result.json()['provenance']=='operator_recorded'
    data=admin.get('/api/admin/readiness').json()
    assert data['services']['push_device']['end_to_end']['evidence']==payload['evidence']
    assert data['services']['push_device']['last_recorded_acceptance'] is None
    bad=admin.post('/api/admin/readiness/evidence',json={**payload,'observed_at':'2099-01-01T00:00:00+00:00'})
    assert bad.status_code==422
    backup=tmp_path/'observability.sqlite3';db.backup(backup)
    target=tmp_path/'restored.sqlite3';restore_database(backup,target)
    with Database(target).connect() as conn:
        instance=conn.execute("SELECT value FROM meta WHERE key='deployment_instance_id'").fetchone()[0]
        assert conn.execute('SELECT COUNT(*) FROM deployment_checks WHERE instance_id=?',(instance,)).fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM deployment_checks').fetchone()[0]==1


def test_request_id_is_server_generated_links_real_audit_and_never_crosses_owner(env):
    c=account(env);other=account(env,'other')
    c.headers['X-Request-ID']='client-controlled-value'
    result=c.post('/api/notices',data={'body':'工程追踪通知：请保存原件后核对本人事项。'})
    assert result.status_code==200,result.text
    rid=result.headers['x-request-id'];assert re.fullmatch('[0-9a-f]{32}',rid)
    nid=result.json()['id'];trace=c.get('/api/notices/'+nid+'/trace')
    assert trace.status_code==200,trace.text
    assert rid in {item['request_id'] for item in trace.json()['actions']}
    assert other.get('/api/notices/'+nid+'/trace').status_code==404
    assert trace.headers['x-request-id']!=rid
    assert 'destination' not in trace.text and 'client-controlled-value' not in trace.text


def test_trace_links_digest_task_components_without_disclosing_other_component_content(env):
    c=account(env);db=env[0].state.db;n=manual(c,notice(c));tid=confirm(c,n,task(n))
    uid=c.get('/api/session').json()['user']['id'];jid=ident()
    with db.connect(write=True) as conn:
        payload={'url':'/#tasks','title':'摘要','event_refs':['reminder:'+tid+':123','reminder:another-private-task:123']}
        conn.execute('INSERT INTO mail_outbox(id,user_id,event_key,payload,destination,state,due_at,created_at) VALUES(?,?,?,?,?,?,?,?)',
                     (jid,uid,'digest:task:123',dumps(payload),'synthetic@example.invalid','accepted',123,123))
    trace=c.get('/api/notices/'+n['id']+'/trace')
    assert trace.status_code==200,trace.text
    assert jid in {item['id'] for item in trace.json()['deliveries']}
    assert 'another-private-task' not in trace.text and 'synthetic@example.invalid' not in trace.text


def test_owner_routes_override_categories_and_foreign_ids_are_rejected(env):
    c=account(env);other=account(env,'other');n=manual(c,notice(c));tid=confirm(c,n,task(n))
    foreign=notice(other);initial=c.get('/api/proactive/status').json()['preferences']
    bad=c.patch('/api/profile',json={'expected':{'notification_preferences':initial},'changes':{'notification_preferences':{**initial,'notice_delivery':{foreign['id']:'off'}}}})
    assert bad.status_code==422
    set_preferences(c,task_delivery='off',notice_delivery={n['id']:'immediate'})
    route=c.get('/api/notifications/routes',params={'notice_id':n['id']}).json()
    assert route['notice']['mode']=='immediate' and route['notice']['effective_mode']=='immediate'
    assert other.get('/api/notifications/routes',params={'notice_id':n['id']}).status_code==404
    c.request('DELETE','/api/notices/'+n['id'],json={'version':c.get('/api/notices/'+n['id']).json()['version']}).raise_for_status()
    set_preferences(c,task_delivery='digest')
    assert c.get('/api/proactive/status').json()['preferences']['notice_delivery']=={}


def test_multisource_route_uses_conservative_explicit_mode_and_notice_can_override(env):
    c=account(env);db=env[0].state.db;n=notice(c);uid=c.get('/api/session').json()['user']['id']
    sids=[ident(),ident()]
    with db.connect(write=True) as conn:
        for sid in sids:
            from app.workspace import CatalogItem
            conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,1,1)',(sid,uid,CatalogItem(name='合成来源',platform='website').model_dump_json()))
            conn.execute('INSERT INTO notice_ingest_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',(ident(),uid,n['id'],'website:'+sid+':https://example.invalid/a','hash','合成来源','','[]',1,1.0))
    set_preferences(c,source_delivery={sids[0]:'immediate',sids[1]:'in_app'})
    with db.connect() as conn:
        pref=preferences(conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0])
        assert notice_modes(conn,uid,pref)[n['id']]=='in_app'
    set_preferences(c,notice_delivery={n['id']:'digest'})
    assert c.get('/api/notifications/routes',params={'notice_id':n['id']}).json()['notice']['effective_mode']=='digest'


def test_owned_wechat_and_qq_receipts_have_stable_private_routes_without_unconnected_catalogs(env):
    c=account(env);other=account(env,'other');db=env[0].state.db;n=notice(c)
    uid=c.get('/api/session').json()['user']['id']
    with db.connect(write=True) as conn:
        for key in ['wechat:engineering-app:article:0','qq:engineering-app:message']:
            conn.execute('INSERT INTO notice_ingest_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',(ident(),uid,n['id'],key,'hash','合成渠道','','[]',1,1.0))
        from app.workspace import CatalogItem
        conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,1,1)',(ident(),uid,CatalogItem(name='仅登记的公众号',platform='wechat_public').model_dump_json()))
    routes=c.get('/api/notifications/routes').json()['sources']
    assert len(routes)==2 and all('engineering-app' not in json.dumps(route) for route in routes)
    assert other.get('/api/notifications/routes').json()['sources']==[]
    set_preferences(c,source_delivery={routes[0]['id']:'off'})
    assert c.get('/api/notifications/routes',params={'notice_id':n['id']}).json()['notice']['effective_mode']=='off'
    current=other.get('/api/proactive/status').json()['preferences']
    denied=other.patch('/api/profile',json={'expected':{'notification_preferences':current},'changes':{'notification_preferences':{**current,'source_delivery':{routes[0]['id']:'off'}}}})
    assert denied.status_code==422
