"""Exercise a real isolated Uvicorn process; never load real accounts or call AI.

Run from the project: .venv/Scripts/python.exe scripts/verify_local_runtime.py
The JSON report is synthetic engineering evidence, not a user study or a capacity limit.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
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

USERS=5
NOTICES_PER_USER=20


def main():
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
    invitations=[new_invite(database) for _ in range(USERS)]
    password='Runtime-test-'+secrets.token_urlsafe(20)
    clients=[]
    metrics=[]
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
        if response.status_code!=expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:500]}')
        return response

    def stop():
        nonlocal worker,log
        if worker is not None:
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
        environment={**os.environ,'PYTHONUTF8':'1','DATA_DIR':str(data_dir),'APP_ENV':'local',
                     'APP_HOST':'127.0.0.1','APP_PORT':str(port),'APP_ORIGIN':origin,'AI_API_KEY':''}
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

    def user_flow(index):
        client=clients[index]
        request(client,'POST','/api/auth/register',json={
            'invite':invitations[index],'username':f'runtime_{index}',
            'display_name':f'并发测试账号 {index}','password':password})
        session(client)
        day=(datetime.now(timezone.utc)+timedelta(days=7)).date().isoformat()
        first_notice=None
        first_task=None
        for number in range(NOTICES_PER_USER):
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
        assert len(notices)==NOTICES_PER_USER
        pending=[task for task in current if task['status']=='pending']
        calendar=request(client,'POST','/api/calendar/export',json={
            'task_ids':[task['id'] for task in pending],
            'versions':{task['id']:task['version'] for task in pending}})
        assert len(Calendar.from_ical(calendar.content).walk('VEVENT'))==NOTICES_PER_USER
        return first_notice,first_task,tasks[0]

    try:
        start(temporary/'data')
        clients=[httpx.Client(base_url=origin,timeout=20,trust_env=False,
                             headers={'Origin':origin,'X-Requested-With':'campus-notice'})
                 for _ in range(USERS)]
        print('Running five isolated users against the real HTTP service...',flush=True)
        workload_started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=USERS) as pool:
            results=list(pool.map(user_flow,range(USERS)))
        workload_seconds=time.perf_counter()-workload_started
        for index,client in enumerate(clients):
            other_notice,other_task,task_data=results[(index+1)%USERS]
            request(client,'GET','/api/notices/'+other_notice,expected=404)
            request(client,'PUT','/api/tasks/'+other_task,expected=404,
                    json={'version':2,'data':task_data,'status':'done','reason':'隔离性验证'})
        print('Concurrency, idempotency, stale writes, calendar exports and isolation passed.',flush=True)
        backup=temporary/'snapshot.sqlite3'
        database.backup(backup)
        stop()
        start(temporary/'data')
        for client in clients:
            assert len(request(client,'GET','/api/tasks').json())==NOTICES_PER_USER*2
        print('Forced process stop and restart preserved all confirmed tasks.',flush=True)
        stop()
        recovered=temporary/'recovered'/'campus.sqlite3'
        restore_database(backup,recovered)
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
            assert len(saved)==NOTICES_PER_USER*2
            assert sum(task['status']=='done' for task in saved)==NOTICES_PER_USER
            assert request(client,'GET','/api/edit-cache/new-notice').json()['revision']==NOTICES_PER_USER
        timings=sorted(elapsed for elapsed,_ in metrics)
        status_counts={str(code):sum(status==code for _,status in metrics) for code in sorted({code for _,code in metrics})}
        report={'verified_at':datetime.now(timezone.utc).isoformat(),'result':'passed',
                'synthetic_test':True,'live_model_calls':0,'concurrent_users':USERS,
                'notices_saved':USERS*NOTICES_PER_USER,'tasks_saved':USERS*NOTICES_PER_USER*2,
                'http_requests':len(metrics),'response_status_counts':status_counts,
                'workload_seconds':round(workload_seconds,2),
                'request_latency_ms':{'median':round(timings[len(timings)//2],1),
                                      'p95':round(timings[int((len(timings)-1)*.95)],1),
                                      'max':round(timings[-1],1)},
                'restart_preserved_tasks':True,'restore_preserved_tasks_and_edit_caches':True,
                'restored_old_sessions_rejected':True,'cross_account_access_rejected':True,
                'stale_updates_rejected':True,'idempotent_replays_passed':True,
                'elapsed_seconds':round(time.perf_counter()-started,2),
                'scope':'Local real HTTP process; synthetic text notices; not a load ceiling, phone acceptance or user study.'}
        (artifact_root/'runtime-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        stop()
        for client in clients:
            client.close()
        if Path(scratch.name).resolve().parent!=artifact_root:
            raise RuntimeError('Refusing cleanup outside the acceptance directory')
        scratch.cleanup()


if __name__=='__main__':
    main()
