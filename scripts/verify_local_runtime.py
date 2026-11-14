"""Exercise a real isolated Uvicorn process; never load real accounts or call AI.

Run from the project: .venv/Scripts/python.exe scripts/verify_local_runtime.py
The JSON report is synthetic engineering evidence, not a user study or a capacity limit.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import argparse
import json
import math
import os
import platform
import re
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

import httpx
from icalendar import Calendar
from app.backups import restore_database
from app.db import Database
from app.models import TaskData
from app.security import new_invite
from app.console import configure_text_output

DEFAULT_USERS=5
DEFAULT_NOTICES_PER_USER=20


def cleanup_fixture(scratch, artifact_root):
    # Windows can release inherited log/database handles just after taskkill
    # returns. Retry only that transient condition, keeping a bounded failure.
    for attempt in range(12):
        target=Path(scratch.name).resolve()
        if target.parent!=artifact_root.resolve() or not target.name.startswith('runtime-check-'):
            raise RuntimeError('Refusing cleanup outside the acceptance directory')
        try:
            scratch.cleanup()
            return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in {5,32,33} or attempt==11:
                raise
            time.sleep(min(.1*(attempt+1),1))


def main():
    configure_text_output()
    from audit_full_suite import fingerprint
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users',type=int,default=DEFAULT_USERS,choices=range(2,16))
    parser.add_argument('--notices-per-user',type=int,default=DEFAULT_NOTICES_PER_USER,choices=range(1,51))
    parser.add_argument('--output',default='artifacts/runtime-acceptance.json')
    args=parser.parse_args();users=args.users;notices_per_user=args.notices_per_user
    implementation_before=fingerprint()
    artifact_root=(ROOT/'artifacts').resolve()
    artifact_root.mkdir(exist_ok=True)
    scratch=tempfile.TemporaryDirectory(prefix='runtime-check-',dir=artifact_root)
    temporary=Path(scratch.name).resolve()
    if temporary.parent!=artifact_root:
        raise RuntimeError('Refusing a temporary path outside the acceptance directory')
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0))
        port=reserved.getsockname()[1]
    origin=f'http://127.0.0.1:{port}'
    database=Database(temporary/'data'/'campus.sqlite3')
    password='Runtime-test-'+secrets.token_urlsafe(20)
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    from synthetic_auth import verified_registration
    fixture_app=create_app(Settings(temporary/'data',origin=origin,ai_api_key=''))
    with TestClient(fixture_app,base_url=origin,headers={'Origin':origin,'X-Requested-With':'campus-notice'}) as fixture:
        for index in range(users):
            verified_registration(fixture,{'username':f'runtime_{index}','display_name':f'并发测试账号 {index}',
                'password':password,'accepted_terms':True,**({'invite':new_invite(database,'admin')} if index==0 else {})})
    clients=[]
    metrics=[]
    operation_metrics={}
    mutex=threading.Lock()
    worker=None
    log=None
    started=time.perf_counter()

    def request(client,method,path,expected=200,**kwargs):
        before=time.perf_counter()
        response=client.request(method,path,**kwargs)
        elapsed=(time.perf_counter()-before)*1000
        with mutex:
            metrics.append((elapsed,response.status_code))
            route=re.sub(r'(?<=/)[a-f0-9]{32}(?=/|$)','{id}',path)
            operation_metrics.setdefault((method,route,response.status_code),[]).append(elapsed)
        if response.status_code!=expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:500]}')
        return response

    def stop():
        nonlocal worker,log
        if worker is not None:
            if worker.poll() is None:
                if os.name=='nt':
                    # A Windows venv launcher can own a second Python process.
                    # Stop only this still-running Popen process and its children.
                    stopped=subprocess.run(['taskkill','/PID',str(worker.pid),'/T','/F'],
                                           capture_output=True,timeout=10,
                                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if stopped.returncode and worker.poll() is None:
                        raise RuntimeError('Could not stop the owned isolated process tree')
                else:
                    worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            worker=None
        if log is not None:
            log.close()
            log=None

    def start(data_dir):
        nonlocal worker,log
        log=open(temporary/'server.log','ab')
        # Test mode preserves the deliberately empty injected credential; local
        # desktop mode instead prefers the user's maintained .env credential.
        environment={**os.environ,'PYTHONUTF8':'1','DATA_DIR':str(data_dir),'APP_ENV':'test',
                     'APP_HOST':'127.0.0.1','APP_PORT':str(port),'APP_ORIGIN':origin,'MIMO_API_KEY':'',
                     'QQ_BOT_SECRET':'','WECHAT_PUBLISHER_SECRET':'','REGISTRATION_MODE':'invite',
                     'ALIYUN_ACCESS_KEY_ID':'','ALIYUN_ACCESS_KEY_SECRET':'','SMS_SIGN_NAME':'','MAIL_SENDER':''}
        worker=subprocess.Popen([sys.executable,str(ROOT/'manage.py'),'serve'],cwd=ROOT,
                                env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+30
        with httpx.Client(base_url=origin,timeout=2,trust_env=False) as probe:
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    raise RuntimeError('Isolated server exited during startup')
                try:
                    if probe.get('/api/health').status_code==200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
        raise RuntimeError('Isolated server did not become healthy')

    def session(client):
        data=request(client,'GET','/api/session').json()
        assert data['ai']['configured'] is False
        client.headers['X-CSRF-Token']=data['csrf']

    def task_snapshot(rows):
        # Stable business identity and content, excluding derived clock labels
        # and the export marker changed by the calendar check itself.
        return {row['id']:{key:row[key] for key in ('notice_id','status','version','data')} for row in rows}

    def user_flow(index):
        client=clients[index]
        request(client,'POST','/api/auth/login',json={'username':f'runtime_{index}','password':password})
        session(client)
        day=(datetime.now(timezone.utc)+timedelta(days=7)).date().isoformat()
        first_notice=None
        first_task=None
        confirmed_task_ids=set()
        for number in range(notices_per_user):
            marker=f'【虚构并发测试 {index}-{number}】'
            notice=request(client,'POST','/api/notices',data={
                'title':marker+'测试通知','body':marker+f' 请本人于 {day} 17:00 前核对申请材料。',
                'materials_complete':'true','source_label':'隔离工程验收数据'}).json()
            nid=notice['id']
            draft=request(client,'POST',f'/api/notices/{nid}/manual',json={'version':notice['version']}).json()
            tasks=[TaskData(title=marker+label,due_date=day,due_time='17:00',
                            deadline_confirmed=True,deadline_text=day+' 17:00 前').model_dump()
                   for label in ['核对材料','保存回执']]
            confirmation={'version':draft['version'],'reviewed':True,'tasks':tasks}
            saved=request(client,'POST',f'/api/notices/{nid}/confirm',json=confirmation).json()
            confirmed_task_ids.update(saved['task_ids'])
            if number==0:
                replay=request(client,'POST',f'/api/notices/{nid}/confirm',json=confirmation).json()
                assert replay['replayed'] and replay['task_ids']==saved['task_ids']
                first_notice=nid
                first_task=saved['task_ids'][0]
            update={'version':1,'data':tasks[0],'status':'done','reason':'并发验证已完成'}
            request(client,'PUT','/api/tasks/'+saved['task_ids'][0],json=update)
            request(client,'PUT','/api/tasks/'+saved['task_ids'][0],expected=409,json=update)
            cache=request(client,'PUT','/api/edit-cache/new-notice',json={
                'revision':number,'payload':{'title':marker,'body':'隔离草稿暂存'}}).json()
            assert cache['revision']==number+1
            current=request(client,'GET','/api/tasks').json()
            assert len(current)==2*(number+1)
            assert all(f'【虚构并发测试 {index}-' in task['data']['title'] for task in current)
        notices=request(client,'GET','/api/notices').json()
        assert len(notices)==notices_per_user
        pending=[task for task in current if task['status']=='pending']
        calendar=request(client,'POST','/api/calendar/export',json={
            'task_ids':[task['id'] for task in pending],
            'versions':{task['id']:task['version'] for task in pending}})
        assert len(Calendar.from_ical(calendar.content).walk('VEVENT'))==notices_per_user
        snapshot=task_snapshot(current)
        assert set(snapshot)==confirmed_task_ids
        return first_notice,first_task,tasks[0],snapshot

    try:
        start(temporary/'data')
        clients=[httpx.Client(base_url=origin,timeout=20,trust_env=False,
                             headers={'Origin':origin,'X-Requested-With':'campus-notice'})
                 for _ in range(users)]
        print(f'Running {users} isolated users against the real HTTP service...',flush=True)
        workload_started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=users) as pool:
            results=list(pool.map(user_flow,range(users)))
        workload_seconds=time.perf_counter()-workload_started
        for index,client in enumerate(clients):
            other_notice,other_task,task_data,_=results[(index+1)%users]
            request(client,'GET','/api/notices/'+other_notice,expected=404)
            request(client,'PUT','/api/tasks/'+other_task,expected=404,
                    json={'version':2,'data':task_data,'status':'done','reason':'隔离性验证'})
        print('Concurrency, idempotency, stale writes, calendar exports and isolation passed.',flush=True)
        lock_timings=request(clients[0],'GET','/api/admin/readiness').json()['database_locks']
        assert lock_timings['observed'] and lock_timings['failed_acquisitions']==0
        backup=temporary/'snapshot.sqlite3'
        backup_started=time.perf_counter();database.backup(backup)
        backup_seconds=time.perf_counter()-backup_started
        restart_started=time.perf_counter()
        stop()
        start(temporary/'data')
        for index,client in enumerate(clients):
            saved=request(client,'GET','/api/tasks').json()
            assert len(saved)==notices_per_user*2
            assert task_snapshot(saved)==results[index][3]
        restart_verified_seconds=time.perf_counter()-restart_started
        print('Process stop and restart preserved all confirmed task identities and business content.',flush=True)
        stop()
        recovered=temporary/'recovered'/'campus.sqlite3'
        restore_started=time.perf_counter();restore_database(backup,recovered)
        restore_file_seconds=time.perf_counter()-restore_started
        with closing(sqlite3.connect(recovered)) as checked:
            assert checked.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert checked.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
            assert checked.execute('SELECT COUNT(*) FROM invites').fetchone()[0]==0
        start(recovered.parent)
        for index,client in enumerate(clients):
            request(client,'GET','/api/tasks',expected=401)
            request(client,'POST','/api/auth/login',json={'username':f'runtime_{index}','password':password})
            session(client)
            saved=request(client,'GET','/api/tasks').json()
            assert len(saved)==notices_per_user*2
            assert task_snapshot(saved)==results[index][3]
            assert sum(task['status']=='done' for task in saved)==notices_per_user
            assert request(client,'GET','/api/edit-cache/new-notice').json()['revision']==notices_per_user
        restore_verified_seconds=time.perf_counter()-restore_started
        timings=sorted(elapsed for elapsed,_ in metrics)
        def rank(values,p):return values[max(0,math.ceil(len(values)*p)-1)]
        status_counts={str(code):sum(status==code for _,status in metrics) for code in sorted({code for _,code in metrics})}
        operations=[]
        for (method,route,status),samples in sorted(operation_metrics.items()):
            values=sorted(samples)
            operations.append({'method':method,'route':route,'status':status,'samples':len(values),
                               'p50_ms':round(rank(values,.5),1),
                               'p95_ms':round(rank(values,.95),1),
                               'max_ms':round(values[-1],1)})
        crud=sorted(value for (method,route,status),samples in operation_metrics.items()
                    if 200<=status<300 and route.startswith(('/api/notices','/api/tasks','/api/edit-cache'))
                    for value in samples)
        report={'verified_at':datetime.now(timezone.utc).isoformat(),'result':'passed',
                'environment':{'python':platform.python_version(),'platform':platform.platform()},
                'implementation_sha256':implementation_before,
                'synthetic_test':True,'live_model_calls':0,'concurrent_users':users,
                'notices_saved':users*notices_per_user,'tasks_saved':users*notices_per_user*2,
                'http_requests':len(metrics),'response_status_counts':status_counts,
                'operations':operations,'database_locks_before_restart':lock_timings,
                'percentile_method':'nearest_rank',
                'ordinary_crud_latency_ms':{'samples':len(crud),'p50':round(rank(crud,.5),1),'p95':round(rank(crud,.95),1),'max':round(crud[-1],1)},
                'engineering_targets':{
                    'scope':'Engineering proposal in docs/PILOT_RELEASE_GATES.md; separate from functional assertions and real campus acceptance.',
                    'ordinary_crud_p95':{'limit_ms_exclusive':1000,'passed':rank(crud,.95)<1000},
                    'write_total_wait_p95':{'limit_ms_exclusive':100,'passed':lock_timings['wait']['p95_ms']<100},
                    'write_acquisitions':{'allowed_failures':0,'passed':lock_timings['failed_acquisitions']==0}},
                'recovery_observations':{'backup_seconds':round(backup_seconds,3),'restart_verified_seconds':round(restart_verified_seconds,3),
                    'restore_file_seconds':round(restore_file_seconds,3),'restore_verified_seconds':round(restore_verified_seconds,3),
                    'confirmed_tasks_lost_in_fixture':0,'task_identity_and_business_content_equal':True,
                    'process_stop_method':'owned process tree taskkill /T /F' if os.name=='nt' else 'owned process SIGTERM; SIGKILL only if stop timeout',
                    'snapshot_scope':'All fixture business writes completed before the snapshot; no later business writes. This is not a production RPO or power-failure simulation.'},
                'workload_seconds':round(workload_seconds,2),
                'request_latency_ms':{'median':round(rank(timings,.5),1),
                                      'p95':round(rank(timings,.95),1),
                                      'max':round(timings[-1],1)},
                'restart_preserved_tasks':True,'restore_preserved_tasks_and_edit_caches':True,
                'restored_old_sessions_rejected':True,'cross_account_access_rejected':True,
                'stale_updates_rejected':True,'idempotent_replays_passed':True,
                'elapsed_seconds':round(time.perf_counter()-started,2),
                'scope':'Local real HTTP process; synthetic text notices; not a load ceiling, phone acceptance or user study.'}
    finally:
        stop()
        for client in clients:
            client.close()
        cleanup_fixture(scratch,artifact_root)
    report['elapsed_seconds']=round(time.perf_counter()-started,2)
    report['implementation_unchanged']=fingerprint()==implementation_before
    if not report['implementation_unchanged']:
        report['result']='invalidated_code_changed_during_run'
    report_path=(ROOT/args.output).resolve();report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['implementation_unchanged']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
