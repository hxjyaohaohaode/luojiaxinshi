"""Whole-account light views, clock-only derivation, cache fences and search."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import workspace_projection as projection
from app.db import dumps, ident
from app.models import TaskData
from app.notice_automation import mark_profile
from app.workflow import WorkflowData
from tests.test_sprint_lists import seed
from tests.test_campus_permissions import actors, publication, publish
from tests.test_workflow import env, account, notice, manual, confirm, task, PASSWORD, ORIGIN

CST = timezone(timedelta(hours=8))


def get(client, **params):
    response = client.get('/api/workspace/projection', params=params)
    assert response.status_code==200,response.text
    return response


def task_inventory(env, client, count=61):
    uid, nids = seed(env, client, count)
    tids = []
    with env[0].state.db.connect(write=True) as conn:
        for index,nid in enumerate(nids):
            tid = ident();tids.append(tid)
            value = TaskData(title='已确认事项'+str(index), due_date='2027-10-20', due_time='17:00',
                deadline_confirmed=True, details='仅在完整办理页读取的长说明。'*180,
                notes='PRIVATE_WORKSPACE_MARKER_'*110, materials=['附件项目'+str(n)+('细节'*100) for n in range(15)],
                planned_at='2027-10-19T11:00:00+08:00', location='课堂'+str(index),
                scheduled={'kind':'window','start_date':'2027-10-17','start_time':'08:00',
                           'end_date':'2027-10-20','end_time':'17:00','confirmed':True}).model_dump()
            conn.execute('INSERT INTO tasks(id,user_id,notice_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (tid,uid,nid,dumps(value),index+1,index+1))
            conn.execute("UPDATE notices SET status='confirmed' WHERE id=?",(nid,))
    return uid,nids,tids


def test_complete_projection_over_fifty_matches_inventory_dates_flags_and_reduces_payload(env):
    client=account(env);_,nids,tids=task_inventory(env,client)
    full_notices=client.get('/api/notices');full_tasks=client.get('/api/tasks')
    response=get(client);value=response.json()
    assert value['counts']=={'notices':61,'tasks':61}
    assert {n['id'] for n in value['notices']}==set(nids)
    assert {t['id'] for t in value['tasks']}==set(tids)
    originals={t['id']:t for t in full_tasks.json()}
    old_notices={n['id']:n for n in full_notices.json()}
    for record in value['notices']:
        original=old_notices[record['id']]
        for key in ('title','status','intent','recommended','task_count','disposition'):
            assert record[key]==original[key]
        assert not {'draft','text','sources','source_excerpt'}.intersection(record)
    for record in value['tasks']:
        original=originals[record['id']]
        for key in ('status','version','overdue','due_soon','followup_due','needs_calendar_sync','calendar_check_required'):
            assert record[key]==original[key]
        for key in ('due_date','due_time','planned_at','reminder_at','deadline_confirmed','scope','location'):
            assert record['data'][key]==original['data'][key]
        assert record['data']['scheduled']=={k:v for k,v in original['data']['scheduled'].items() if k!='evidence'}
        assert record['handling_state']['kind']==original['handling_state']['kind']
        assert record['material_count']==15 and record['projection']=='light'
        assert record['data']['materials']==[] and record['data']['details']==''
    assert 'PRIVATE_WORKSPACE_MARKER_' not in response.text
    assert len(response.content)<.35*(len(full_notices.content)+len(full_tasks.content))
    tasks_only=get(client,include='tasks').json()
    assert tasks_only['notices']==[] and len(tasks_only['tasks'])==61
    assert tasks_only['counts']==value['counts'] and tasks_only['revision']==value['revision']


def test_minute_refresh_recalculates_deadline_followup_and_notice_age_without_body_reads(env,monkeypatch):
    client=account(env);db=env[0].state.db;uid=client.get('/api/session').json()['user']['id']
    base=int(datetime(2030,1,1,23,59,30,tzinfo=CST).timestamp())
    opportunity=notice(client,'本人申请截止2030年1月1日，未给出具体时刻。')
    evidence={'source_id':opportunity['sources'][0]['id'],'locator':opportunity['sources'][0]['sections'][0]['locator'],
              'quote':'本人申请截止2030年1月1日，未给出具体时刻。'}
    draft={'summary':'PRIVATE_DRAFT_SUMMARY','quality':{'status':'passed'},'applicability':'matches_known',
           'tasks':[{'title':'本人申请','scope':'personal','due_date':'2030-01-01','deadline_evidence':[evidence]}],
           'plans':{'0':{'action_kind':'optional','execution_mode':'submission'}}}
    personal=manual(client,notice(client,'本人设置跟进计划，核查办理进展。'))
    tid=confirm(client,personal,task(personal,due_date='2030-01-01',due_time=None,materials=[]))
    with db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET draft=?,draft_version=version,status='draft' WHERE id=?",(dumps(draft),opportunity['id']))
        profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
        mark_profile(conn,opportunity['id'],uid,opportunity['version'],profile)
        progress=WorkflowData(next_step='核查本次受理结果',followup_at=datetime.fromtimestamp(base+20,timezone.utc).isoformat()).model_dump()
        conn.execute('INSERT INTO task_workflows(task_id,data,version,updated_at) VALUES(?,?,1,?) '
                     'ON CONFLICT(task_id) DO UPDATE SET data=excluded.data', (tid,dumps(progress),base))
    clock=[base];monkeypatch.setattr(projection,'time',SimpleNamespace(time=lambda:clock[0]))
    first=get(client).json()
    item=next(n for n in first['notices'] if n['id']==opportunity['id'])
    assert item['tracking']['state']=='active' and item['recommended']
    assert not first['tasks'][0]['overdue'] and not first['tasks'][0]['followup_due']
    assert 'PRIVATE_DRAFT_SUMMARY' not in dumps(first)
    statements=[];original=db.connect
    @contextmanager
    def traced(*args,**kwargs):
        with original(*args,**kwargs) as conn:
            conn.set_trace_callback(statements.append)
            yield conn
    monkeypatch.setattr(db,'connect',traced)
    def rebuild_forbidden(*args,**kwargs):raise AssertionError('clock refresh rebuilt stable entities')
    monkeypatch.setattr(projection,'build_snapshot',rebuild_forbidden)
    clock[0]+=60
    second=get(client,clock_only=1,revision=first['revision']).json()
    assert second['clock_only'] and second['revision']==first['revision'] and second['clock']==first['clock']+1
    changed=next(n for n in second['notices'] if n['id']==opportunity['id'])
    assert changed['intent']=='closed' and not changed['recommended'] and changed['tracking']['state']=='elapsed'
    assert second['tasks'][0]['overdue'] and second['tasks'][0]['followup_due']
    assert second['tasks'][0]['handling_state']['kind']=='followup'
    assert all('data' not in t and 'title' not in t for t in second['tasks'])
    assert not any('draft' in sql.lower() or 'sections' in sql.lower() or 't.*' in sql.lower() for sql in statements)


def test_stable_mutation_and_restore_instance_force_complete_light_snapshot(env):
    client=account(env);uid,nids,tids=task_inventory(env,client,2);db=env[0].state.db
    before=get(client).json()
    with db.connect(write=True) as conn:conn.execute("UPDATE tasks SET status='done',version=version+1 WHERE id=?",(tids[0],))
    changed=get(client,clock_only=1,revision=before['revision']).json()
    assert not changed['clock_only'] and changed['revision']!=before['revision']
    assert next(t for t in changed['tasks'] if t['id']==tids[0])['status']=='done'
    with db.connect(write=True) as conn:conn.execute("UPDATE meta SET value=? WHERE key='deployment_instance_id'",(ident(),))
    restored=get(client,clock_only=1,revision=changed['revision']).json()
    assert not restored['clock_only'] and restored['revision']!=changed['revision']
    try:
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM tasks WHERE id=?',(tids[1],))
            raise RuntimeError('rollback fixture')
    except RuntimeError:pass
    rolled=get(client,clock_only=1,revision=restored['revision']).json()
    assert rolled['clock_only'] and rolled['revision']==restored['revision'] and len(rolled['tasks'])==2


def test_private_cache_and_etags_never_cross_accounts_or_survive_deleted_auth(env):
    client,other=account(env),account(env,'other')
    _,nids,_=task_inventory(env,client,1);first=get(client)
    forbidden=other.get('/api/workspace/projection',params={'clock_only':1,'revision':first.json()['revision']},
                        headers={'If-None-Match':first.headers['etag']})
    assert forbidden.status_code==200 and forbidden.json()['counts']=={'notices':0,'tasks':0}
    assert nids[0] not in forbidden.text and forbidden.json()['revision']!=first.json()['revision']
    assert client.get('/api/workspace/projection',headers={'If-None-Match':first.headers['etag']}).status_code==304
    assert TestClient(env[0],base_url=ORIGIN).get('/api/workspace/projection').status_code==401
    assert client.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}).status_code==200
    removed_notice=first.json()['notices'][0]['id']
    assert all(not any(row['id']==removed_notice for row in entry['value']['notices'])
               for entry in env[0].state.workspace_projection_cache.entries.values())
    assert client.get('/api/workspace/projection',params={'clock_only':1,'revision':first.json()['revision']}).status_code==401


def test_cache_expiry_eviction_and_oversize_never_return_stale_partial_inventory(env,monkeypatch):
    client=account(env);task_inventory(env,client,1);cache=env[0].state.workspace_projection_cache
    first=get(client).json()
    with cache.lock:
        for entry in cache.entries.values():entry['expires']=0
    expired=get(client,clock_only=1,revision=first['revision']).json()
    assert not expired['clock_only'] and expired['counts']==first['counts']
    cache.max_bytes=1
    with cache.lock:
        for entry in cache.entries.values():entry['expires']=0
    uncached=get(client,clock_only=1,revision=expired['revision']).json()
    assert not uncached['clock_only'] and len(uncached['tasks'])==1 and cache.bytes==0 and not cache.entries
    bounded=projection.ProjectionCache(max_bytes=10000,max_entries=1,ttl=10)
    bounded.put(('db','alice'),'r',{'safe':1},100)
    bounded.put(('db','bob'),'r',{'safe':2},100)
    assert bounded.get(('db','alice'),'r',100) is None
    assert bounded.get(('db','bob'),'r',111) is None and bounded.bytes==0


def test_calendar_text_search_keeps_full_owner_inventory_without_returning_text(env):
    client,other=account(env),account(env,'calendar-other')
    uid,_,tids=task_inventory(env,client,61);task_inventory(env,other,1)
    with env[0].state.db.connect(write=True) as conn:
        row=conn.execute('SELECT data FROM tasks WHERE id=?',(tids[-1],)).fetchone()
        data=json.loads(row[0]);data['details']='特定 备注关键词 ÉCOLE'
        conn.execute('UPDATE tasks SET data=? WHERE id=?',(dumps(data),tids[-1]))
    for query in (' 特定 备注关键词 ','école','课堂60'):
        response=client.get('/api/workspace/calendar-search',params={'q':query})
        assert response.status_code==200,response.text
        assert response.json()['task_ids']==[tids[-1]] and response.json()['query']==query.strip()
        assert set(response.json())=={'query','revision','task_ids'}
    assert len(client.get('/api/workspace/calendar-search',params={'q':'事项'}).json()['task_ids'])==61
    assert other.get('/api/workspace/calendar-search',params={'q':'特定 备注关键词'}).json()['task_ids']==[]
    assert client.get('/api/workspace/calendar-search',params={'q':'x'*501}).status_code==422
    assert client.get('/api/workspace/projection',params={'include':'sources'}).status_code==422


def test_received_publication_validity_rechecks_clock_without_changing_stable_revision(env,monkeypatch):
    _,_,counselor,student,_,_=actors(env)
    base=int(datetime(2030,1,1,12,0,tzinfo=CST).timestamp())
    sent=publish(counselor,{**publication(),'valid_until':datetime.fromtimestamp(base+30,timezone.utc).isoformat()})
    assert sent.status_code==200,sent.text
    clock=[base];monkeypatch.setattr(projection,'time',SimpleNamespace(time=lambda:clock[0]))
    first=get(student).json();context=first['notices'][0]['publication_context']
    assert not context['expired'] and context['external_notifications']=='eligible'
    clock[0]+=60
    second=get(student,clock_only=1,revision=first['revision']).json()
    context=second['notices'][0]['publication_context']
    assert second['clock_only'] and second['revision']==first['revision']
    assert context['expired'] and context['external_notifications']=='suppressed'
