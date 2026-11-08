"""A campus pilot journey through real API writes and independent sessions."""
import json
import uuid

from fastapi.testclient import TestClient
import pytest

from tests.test_campus_permissions import actors, assign, CLASS1, CLASS2, COLLEGE
from tests.test_workflow import account, confirm, env, manual, notice, PASSWORD, ORIGIN


HEADERS={'X-Workspace-Revision':'1'}


def domains(client):
    return client.get('/api/proactive/revision',headers=HEADERS).json()['domains']


def ok(response):
    assert response.status_code==200,response.text
    return response.json()


def test_domain_revisions_are_transactional_and_owner_scoped(env):
    a=account(env);b=account(env,'bob')
    uid=ok(a.get('/api/session'))['user']['id']
    old=domains(a);other=domains(b)
    with pytest.raises(RuntimeError,match='abort'):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute("UPDATE users SET display_name='not committed' WHERE id=?",(uid,))
            raise RuntimeError('abort')
    assert domains(a)['account']==old['account']
    row=notice(a)
    changed=domains(a)
    assert changed['notices']>old.get('notices',0)
    assert changed['account']==old['account']
    assert {k:v for k,v in domains(b).items() if k!='clock'}=={k:v for k,v in other.items() if k!='clock'}
    assert row['title'] not in a.get('/api/proactive/revision',headers=HEADERS).text


def test_independent_sessions_and_disjoint_display_settings(env):
    a=account(env)
    b=TestClient(env[0],base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    session=ok(b.post('/api/auth/login',json={'username':'alice','password':PASSWORD}))['session']
    b.headers['X-CSRF-Token']=session['csrf']
    assert session['user']['id']==ok(a.get('/api/session'))['user']['id']
    old=domains(b)
    ok(a.patch('/api/profile',json={'changes':{'calendar_view':'week','motion_enabled':False},
                                   'expected':{'calendar_view':None,'motion_enabled':None}}))
    ok(b.patch('/api/profile',json={'changes':{'task_view':'board'},'expected':{'task_view':None}}))
    response=a.patch('/api/profile',json={'changes':{'calendar_view':'day'},'expected':{'calendar_view':None}})
    assert response.status_code==409
    assert response.json()['detail']['fields']==['calendar_view']
    for client in (a,b):
        saved=ok(client.get('/api/session'))['user']['profile']
        assert (saved['calendar_view'],saved['task_view'],saved['motion_enabled'])==('week','board',False)
    assert domains(b)['account']>old['account']


def test_read_cannot_cross_accounts_after_cookie_switch(env):
    a=account(env);b=account(env,'bob')
    alice=ok(a.get('/api/session'))['user']['id']
    notice(b)
    denied=b.get('/api/notices',headers={'X-Workspace-Owner':alice})
    assert denied.status_code==401
    assert denied.json()['detail']['code']=='account_changed'
    assert '自动化测试通知' not in denied.text


def test_conditional_projection_uses_current_owner_and_does_not_scan_unchanged_rows(env):
    a=account(env);b=account(env,'bob')
    initial=a.get('/api/notices')
    cache={'If-None-Match':initial.headers['etag']}
    same=a.get('/api/notices',headers=cache)
    assert same.status_code==304 and not same.content
    assert b.get('/api/notices',headers=cache).status_code==200
    created=notice(a)
    latest=a.get('/api/notices',headers=cache)
    assert latest.status_code==200 and latest.headers['etag']!=initial.headers['etag']
    assert latest.json()[0]['id']==created['id']


def test_collaboration_uses_real_authority_versions_receipts_and_original_bytes(env):
    site,manager,counselor,one,two,three=actors(env)
    task_id=confirm(one,manual(one,notice(one)))
    task=ok(one.get(f'/api/tasks/{task_id}/workflow'))['task']
    upload=one.post(f'/api/tasks/{task_id}/materials',data={'request_id':uuid.uuid4().hex,'requirement':'申请表',
                    'task_version':task['version'],'workflow_version':task['workflow']['version']},
                    files={'file':('申请表.txt',b'first reviewed version','text/plain')})
    assert upload.status_code==200,upload.text
    options=ok(one.get(f'/api/collaboration/tasks/{task_id}/options'))
    recipient=ok(counselor.get('/api/session'))['user']['id']
    assert recipient in {x['id'] for x in options['recipients']}
    outside=ok(two.get('/api/session'))['user']['id']
    payload={'task_id':task_id,'task_version':options['version'],'recipient_id':recipient,
             'note':'请协助核对签字页','request_id':uuid.uuid4().hex,
             'files':[{k:options['files'][0][k] for k in ('material_id','version')}]}
    assert one.post('/api/collaboration',json={**payload,'recipient_id':outside}).status_code==403
    before=domains(counselor)
    created=ok(one.post('/api/collaboration',json=payload))
    path='/api/collaboration/'+created['id']
    assert domains(counselor)['collaboration']>before.get('collaboration',0)
    assert ok(one.post('/api/collaboration',json=payload))['id']==created['id']
    assert two.get(path).status_code==404 and site.get(path).status_code==404
    assert counselor.get('/api/tasks/'+task_id+'/workflow').status_code==404
    assert ok(counselor.get(path))['task_id'] is None
    assert any(item.get('case_id')==created['id'] for item in ok(counselor.get('/api/reminders'))['items'])
    file_url=created['events'][0]['files'][0]['download_url']
    assert counselor.get(file_url).content==b'first reviewed version'
    assert two.get(file_url).status_code==404

    def act(client,action,version,note='',request=None):
        return client.post(path+'/actions',json={'version':version,'action':action,'note':note,
                                                'request_id':request or uuid.uuid4().hex})

    assert act(one,'accept',1).status_code==403
    accepted=ok(act(counselor,'accept',1))
    assert accepted['state']=='accepted'
    assert act(counselor,'resolve',1,'旧请求').status_code==409
    assert act(counselor,'request_supplement',2).status_code==422
    request=uuid.uuid4().hex
    supplement=ok(act(counselor,'request_supplement',2,'补上签字页',request))
    assert supplement['version']==3
    assert ok(act(counselor,'request_supplement',2,'补上签字页',request))['version']==3
    assert len(ok(one.get(path))['events'])==3
    assert ok(act(one,'resubmit',3,'已补交签字页'))['state']=='resubmitted'
    assert ok(act(counselor,'accept',4))['state']=='accepted'
    complete=ok(act(counselor,'resolve',5,'已核对签字页，站内协作结束'))
    assert complete['state']=='resolved' and complete['events'][-1]['note'].startswith('已核对')
    assert ok(one.get('/api/tasks/'+task_id+'/workflow'))['task']['status']=='pending'
    # Scope changes revoke private file access immediately, even to an old link.
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    assert counselor.get(path).status_code==404 and counselor.get(file_url).status_code==404
    assert not ok(one.get(path))['recipient_available']


def test_exact_chat_count_works_without_external_consent_or_a_model(env):
    a=account(env);b=account(env,'bob')
    confirm(a,manual(a,notice(a)));confirm(b,manual(b,notice(b)))
    cfg=env[1];cfg.ai_api_key='not-a-provider-credential'
    chat=ok(a.post('/api/conversations',json={'title':'本账号待办统计'}))
    payload={'version':chat['version'],'request_id':uuid.uuid4().hex,'content':'我的待办一共有几条？',
             'allow_external_processing':False}
    response=a.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload)
    assert response.status_code==200,response.text
    packet=next(json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: '))
    message=packet['conversation']['messages'][-1]
    assert message['status']=='complete' and '1 条待办记录' in message['content']
    assert message['grounding']['planning_mode']=='host_workspace_count'
    assert message['grounding']['usage']=={'input_tokens':0,'output_tokens':0}
    assert ok(a.get('/api/conversations/'+chat['id']))['messages'][-1]['id']==message['id']
    replay=a.post('/api/conversations/'+chat['id']+'/messages/stream',json=payload)
    assert replay.status_code==200 and '"replayed":true' in replay.text
    scoped=a.post('/api/conversations/'+chat['id']+'/messages/stream',
                  json={**payload,'request_id':uuid.uuid4().hex,'version':packet['conversation']['version'],
                        'content':'我的待办一共有几条？结合上次附件解释优先级。'})
    assert scoped.status_code==422
