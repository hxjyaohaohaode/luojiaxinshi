"""Synthetic, isolated personal-file and submission transaction tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import sqlite3
import io
import zipfile
from uuid import uuid4

import pytest

from app.db import Database
from app.task_materials import export_task_materials,personal_material_bytes
from tests.test_workflow import account,env,notice,manual,task,confirm


def setup_task(c,text='Synthetic personal material requirement',**overrides):
    n=manual(c,notice(c,text));tid=confirm(c,n,task(n,**overrides))
    return c.get('/api/notices/'+n['id']).json(),tid


def upload(c,tid,content=b'filled application',**fields):
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    data={'task_version':str(t['version']),'requirement':'申请表','request_id':uuid4().hex,**fields}
    return c.post('/api/tasks/'+tid+'/materials',data=data,files={'file':('application.txt',content,'text/plain')})


def submission(c,tid,files=None,**changes):
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    record={'request_id':uuid4().hex,'channel':'学院办公室','submitted_at':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),
        'receipt':'本人交给工作人员，收件编号 123','files':files or [],'confirmed':True,**changes}
    return {'version':t['workflow']['version'],'task_version':t['version'],'data':t['workflow']['data'],'submission':record}


def put_submission(c,tid,payload):return c.put('/api/tasks/'+tid+'/workflow',json=payload)


def file_ref(result,version=None):
    material=result.json()['materials'][0]
    return {'material_id':material['id'],'version':version or material['version']}


def test_personal_upload_does_not_become_notice_evidence_or_reset_it(env):
    c=account(env);n,tid=setup_task(c)
    response=upload(c,tid)
    assert response.status_code==200,response.text
    material=response.json()['materials'][0]
    assert material['requirement']=='申请表' and material['versions'][0]['preview']=='filled application'
    after=c.get('/api/notices/'+n['id']).json()
    assert (after['status'],after['version'],after['draft'],after['sources'])==(n['status'],n['version'],n['draft'],n['sources'])
    assert after['tasks'][0]['version']==n['tasks'][0]['version']
    version=material['versions'][0]
    download=c.get(version['download_url'])
    assert download.content==b'filled application'
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['x-content-type-options']=='nosniff'


def test_material_packages_keep_submitted_versions_and_account_scope(env):
    c=account(env);other=account(env,'other');n,tid=setup_task(c)
    first=upload(c,tid,b'original submitted file');ref=file_ref(first)
    assert put_submission(c,tid,submission(c,tid,[ref])).status_code==200
    sid=c.get('/api/tasks/'+tid+'/materials').json()['submissions'][0]['id']
    assert upload(c,tid,b'new preparation version',material_id=ref['material_id'],expected_version='1').status_code==200
    for suffix,content in [('',b'new preparation version'),('?submission_id='+sid,b'original submitted file')]:
        r=c.get('/api/tasks/'+tid+'/materials/package'+suffix)
        assert r.status_code==200 and r.headers['content-type']=='application/zip'
        with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
            names=archive.namelist();assert '材料说明.txt' in names
            actual=[archive.read(name) for name in names if name!='材料说明.txt']
            assert actual==[content]
            assert '未向学校提交' in archive.read('材料说明.txt').decode('utf-8-sig')
    assert other.get('/api/tasks/'+tid+'/materials/package?submission_id='+sid).status_code==404
    assert c.get('/api/tasks/'+tid+'/materials/package?submission_id=missing').status_code==404


def test_versions_and_submission_snapshot_remain_fixed_after_new_upload(env):
    c=account(env);n,tid=setup_task(c)
    first=upload(c,tid,b'original submitted file');ref=file_ref(first)
    payload=submission(c,tid,[ref]);saved=put_submission(c,tid,payload)
    assert saved.status_code==200,saved.text
    assert saved.json()['status']=='pending'
    assert saved.json()['workflow']['data']['stage']=='submitted'
    assert saved.json()['workflow']['data']['prepared_materials']==['申请表']
    second=upload(c,tid,b'later corrected file',material_id=ref['material_id'],expected_version='1')
    assert second.status_code==200,second.text
    record=second.json()['submissions'][0]
    assert record['data']['authority']=='self_reported'
    assert record['data']['files'][0]['version']==1
    assert record['workflow_version']==saved.json()['workflow']['version']
    assert c.get(record['data']['files'][0]['download_url']).content==b'original submitted file'
    assert second.json()['materials'][0]['version']==2
    assert c.get(second.json()['materials'][0]['versions'][0]['download_url']).content==b'later corrected file'


def test_upload_and_submission_retries_are_idempotent_but_changes_rejected(env):
    c=account(env);_,tid=setup_task(c);rid=uuid4().hex
    first=upload(c,tid,request_id=rid);again=upload(c,tid,request_id=rid)
    assert first.status_code==again.status_code==200
    assert len(again.json()['materials'])==1
    assert upload(c,tid,b'different bytes',request_id=rid).status_code==409
    payload=submission(c,tid,[file_ref(first)])
    assert put_submission(c,tid,payload).status_code==200
    replay=put_submission(c,tid,payload)
    assert replay.status_code==200,replay.text
    assert len(c.get('/api/tasks/'+tid+'/materials').json()['submissions'])==1
    changed=deepcopy(payload);changed['submission']['receipt']='另一份提交记录'
    assert put_submission(c,tid,changed).status_code==409


def test_uncovered_requirements_require_explicit_external_submission(env):
    c=account(env);_,tid=setup_task(c,materials=['申请表','成绩单'])
    material=upload(c,tid);payload=submission(c,tid,[file_ref(material)])
    failed=put_submission(c,tid,payload)
    assert failed.status_code==422 and '成绩单' in failed.text
    before=c.get('/api/tasks/'+tid+'/materials').json()
    assert before['submissions']==[]
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['workflow']['data']['stage']=='preparing'
    payload['submission']['external_requirements']=['成绩单']
    saved=put_submission(c,tid,payload)
    assert saved.status_code==200,saved.text
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions'][0]['data']['external_requirements']==['成绩单']


def test_other_account_and_other_task_files_cannot_be_submitted(env):
    c=account(env);n,tid=setup_task(c)
    other=account(env,'other');_,foreign_tid=setup_task(other)
    foreign=upload(other,foreign_tid);ref=file_ref(foreign)
    assert c.get('/api/tasks/'+foreign_tid+'/materials').status_code==404
    assert c.get(foreign.json()['materials'][0]['versions'][0]['download_url']).status_code==404
    assert put_submission(c,tid,submission(c,tid,[ref])).status_code==422
    _,second_tid=setup_task(c,'A second unrelated task')
    same_owner=upload(c,second_tid)
    assert put_submission(c,tid,submission(c,tid,[file_ref(same_owner)])).status_code==422
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions']==[]


def test_submission_checks_current_conditions_and_never_claims_accepted(env):
    c=account(env);_,tid=setup_task(c)
    material=upload(c,tid);payload=submission(c,tid,[file_ref(material)])
    payload['data']['conditions']=[{'id':'eligible','text':'本人具备申请资格','state':'unknown','note':''}]
    assert put_submission(c,tid,payload).status_code==422
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions']==[]
    payload['data']['conditions'][0].update(state='met',note='已核对本人成绩与规定')
    saved=put_submission(c,tid,payload)
    assert saved.status_code==200,saved.text
    assert saved.json()['workflow']['data']['stage']=='submitted'
    assert saved.json()['status']=='pending'
    next_payload=submission(c,tid,[file_ref(material)])
    next_payload['data']['conditions'][0]['text']='新增必须满足的资格'
    assert put_submission(c,tid,next_payload).status_code==422


def test_submission_and_completion_cannot_share_one_request(env):
    c=account(env);_,tid=setup_task(c);material=upload(c,tid)
    payload=submission(c,tid,[file_ref(material)]);payload['complete']=True
    assert put_submission(c,tid,payload).status_code==422
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions']==[]


def test_submission_honors_dependencies_and_rolls_back_snapshot(env):
    c=account(env);_,tid=setup_task(c);_,prior=setup_task(c,'必须先完成的独立事项',materials=[])
    material=upload(c,tid);payload=submission(c,tid,[file_ref(material)])
    payload['data']['dependencies']=[prior]
    denied=put_submission(c,tid,payload)
    assert denied.status_code==422 and '前置' in denied.text
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions']==[]
    assert c.get('/api/tasks/'+tid+'/workflow').json()['task']['workflow']['data']['stage']=='preparing'


def test_upload_uses_existing_csrf_and_authentication_controls(env):
    c=account(env);_,tid=setup_task(c)
    data={'task_version':'1','requirement':'申请表','request_id':uuid4().hex}
    response=c.post('/api/tasks/'+tid+'/materials',data=data,files={'file':('test.txt',b'private','text/plain')},headers={'X-CSRF-Token':'wrong'})
    assert response.status_code==403
    assert c.get('/api/tasks/'+tid+'/materials').json()['materials']==[]


def test_done_task_cannot_silently_acquire_a_new_pending_submission(env):
    c=account(env);_,tid=setup_task(c);first=upload(c,tid)
    app,_=env
    with app.state.db.connect(write=True) as conn:conn.execute("UPDATE tasks SET status='done' WHERE id=?",(tid,))
    response=put_submission(c,tid,submission(c,tid,[file_ref(first)]))
    assert response.status_code==422 and '恢复' in response.text
    assert c.get('/api/tasks/'+tid+'/materials').json()['submissions']==[]


def test_submission_requires_personal_confirmation_and_real_time(env):
    c=account(env);_,tid=setup_task(c);material=upload(c,tid)
    payload=submission(c,tid,[file_ref(material)],confirmed=False)
    assert put_submission(c,tid,payload).status_code==422
    payload=submission(c,tid,[file_ref(material)],submitted_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    assert put_submission(c,tid,payload).status_code==422


def test_stale_task_and_material_versions_do_not_overwrite_files(env):
    c=account(env);_,tid=setup_task(c);first=upload(c,tid);ref=file_ref(first)
    assert upload(c,tid,b'next',material_id=ref['material_id'],expected_version='1').status_code==200
    assert upload(c,tid,b'conflict',material_id=ref['material_id'],expected_version='1').status_code==409
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    assert upload(c,tid,task_version=str(t['version']+1)).status_code==409
    assert len(c.get('/api/tasks/'+tid+'/materials').json()['materials'][0]['versions'])==2


def test_file_limits_and_account_storage_include_all_versions(env,monkeypatch):
    c=account(env);_,tid=setup_task(c)
    assert upload(c,tid,b'').status_code==413
    assert upload(c,tid,b'x'*(5*1024*1024+1)).status_code==413
    first=upload(c,tid,b'first');ref=file_ref(first)
    from dataclasses import replace
    monkeypatch.setattr(env[0].state.db,'usage_limits',replace(env[0].state.db.usage_limits,storage_bytes=9))
    assert upload(c,tid,b'longer file',material_id=ref['material_id'],expected_version='1').status_code==413
    app,_=env
    with app.state.db.connect() as conn:
        uid=c.get('/api/session').json()['user']['id']
        assert personal_material_bytes(conn,uid)==5


def test_material_metadata_export_and_backup_preserve_snapshots(env,tmp_path):
    c=account(env);_,tid=setup_task(c);first=upload(c,tid,b'private personal output')
    assert put_submission(c,tid,submission(c,tid,[file_ref(first)])).status_code==200
    app,_=env;uid=c.get('/api/session').json()['user']['id']
    with app.state.db.connect() as conn:
        exported=export_task_materials(conn,uid)
    assert exported['includes_file_bytes'] is False and exported['restore_supported'] is False
    assert exported['tasks'][0]['submissions'][0]['data']['authority']=='self_reported'
    assert 'content' not in exported['tasks'][0]['materials'][0]['versions'][0]
    saved=tmp_path/'snapshot.sqlite3';app.state.db.backup(saved)
    restored=Database(saved)
    with restored.connect() as conn:
        assert conn.execute('SELECT content FROM task_material_versions').fetchone()[0]==b'private personal output'
        assert conn.execute('SELECT COUNT(*) FROM task_submission_records').fetchone()[0]==1


def test_corrupt_material_schema_is_rejected_without_silent_recreation(env):
    app,cfg=env
    with app.state.db.connect(write=True) as conn:conn.execute('DROP TABLE task_material_receipts')
    with pytest.raises(RuntimeError,match='本人材料'):
        Database(cfg.data_dir/'campus.sqlite3')


def test_task_deletion_cascades_personal_files_and_snapshots(env):
    c=account(env);n,tid=setup_task(c);first=upload(c,tid)
    assert put_submission(c,tid,submission(c,tid,[file_ref(first)])).status_code==200
    app,_=env
    with app.state.db.connect(write=True) as conn:conn.execute('DELETE FROM tasks WHERE id=?',(tid,))
    with app.state.db.connect() as conn:
        for table in ('task_materials','task_material_versions','task_material_receipts','task_submission_records'):
            assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
