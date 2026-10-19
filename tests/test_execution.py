import json
import sqlite3
import time

import pytest

from app.execution import Runtime,LEASE_SECONDS,recover
from app.db import ident,Database
from app.backups import restore_database
from app import chat_ai,ai
from test_workflow import env,account,notice
from test_workspace import conversation,send,fixture_answer,material
from test_memory_context import uid


def pending(env,c,kind='conversation',runtime=None):
    db=env[0].state.db;runtime=runtime or env[0].state.execution
    now=int(time.time());key=ident();token=ident();owner=uid(c)
    if kind=='conversation':
        target=conversation(c)['id']
        with db.connect(write=True) as conn:
            conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,created_at) VALUES(?,?,'assistant','processing',?)",(key,target,now))
            conn.execute('UPDATE conversations SET processing_token=?,processing_at=? WHERE id=?',(token,now,target))
            runtime.start(conn,key,owner,kind,target,token)
    else:
        target=notice(c)['id']
        with db.connect(write=True) as conn:
            conn.execute("UPDATE notices SET status='processing',processing_token=?,processing_at=? WHERE id=?",(token,now,target))
            conn.execute("INSERT INTO ai_calls(id,user_id,notice_id,model,status,created_at) VALUES(?,?,?,'synthetic','processing',?)",(key,owner,target,now))
            runtime.start(conn,key,owner,kind,target,token)
    return key,target,token


@pytest.mark.parametrize('kind',['conversation','notice'])
def test_expired_owner_is_interrupted_without_calling_provider(env,kind,monkeypatch):
    c=account(env);key,target,_=pending(env,c,kind);db=env[0].state.db
    def forbidden(*args):raise AssertionError('Recovery must never resubmit paid work')
    monkeypatch.setattr(chat_ai,'reply',forbidden);monkeypatch.setattr(ai,'generate',forbidden)
    with db.connect(write=True) as conn:
        conn.execute('UPDATE execution_owners SET expires_at=0')
    other=Runtime(db);assert other.tick()==1 and other.tick()==0
    with db.connect() as conn:
        run=conn.execute('SELECT * FROM executions WHERE id=?',(key,)).fetchone()
        assert run['status']=='interrupted' and run['stop_reason']=='process_lost'
        table='conversations' if kind=='conversation' else 'notices'
        assert conn.execute('SELECT processing_token FROM '+table+' WHERE id=?',(target,)).fetchone()[0] is None
        status=conn.execute('SELECT status FROM '+('conversation_messages' if kind=='conversation' else 'ai_calls')+' WHERE id=?',(key,)).fetchone()[0]
        assert status==('failed' if kind=='conversation' else 'interrupted')


def test_new_worker_does_not_take_over_another_live_workers_jobs(env):
    c=account(env);key,_,_=pending(env,c);db=env[0].state.db
    assert Runtime(db).tick()==0
    with db.connect() as conn:assert conn.execute('SELECT status FROM executions WHERE id=?',(key,)).fetchone()[0]=='running'


def test_slow_notice_with_live_owner_is_not_reported_interrupted_or_resubmitted(env,monkeypatch):
    c=account(env);key,nid,_=pending(env,c,'notice');db=env[0].state.db
    env[1].ai_api_key='synthetic-only'
    with db.connect(write=True) as conn:conn.execute('UPDATE notices SET processing_at=? WHERE id=?',(int(time.time())-600,nid))
    current=c.get('/api/notices/'+nid).json()
    assert current['status']=='processing' and current['error'] is None
    progress=c.get('/api/notices/'+nid+'/processing').json()
    assert progress['status']=='processing' and progress['execution']['status']=='running'
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('A live slow request must not be resubmitted'))
    r=c.post('/api/notices/'+nid+'/generate',json={'version':current['version'],'allow_external_processing':True})
    assert r.status_code==409,r.text
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM ai_calls WHERE notice_id=?',(nid,)).fetchone()[0]==1
        assert conn.execute('SELECT status FROM executions WHERE id=?',(key,)).fetchone()[0]=='running'


def test_notice_processing_rechecks_owner_inside_confirmation_transaction(env,monkeypatch):
    c=account(env);n=notice(c);db=env[0].state.db;env[1].ai_api_key='synthetic-only'
    original=ai.prepare_notice_input
    def competing(*args):
        result=original(*args);token=ident();key=ident()
        with db.connect(write=True) as conn:
            conn.execute("UPDATE notices SET status='processing',processing_token=?,processing_at=? WHERE id=?",(token,int(time.time())-600,n['id']))
            env[0].state.execution.start(conn,key,uid(c),'notice',n['id'],token)
        return result
    monkeypatch.setattr(ai,'prepare_notice_input',competing)
    monkeypatch.setattr(ai,'generate',lambda *args:pytest.fail('A competing live run owns this notice'))
    r=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert r.status_code==409,r.text


def test_notice_processing_uses_actual_terminal_or_expired_owner_and_legacy_fallback(env):
    from app.execution import notice_processing
    c=account(env);key,nid,_=pending(env,c,'notice');db=env[0].state.db;now=int(time.time())
    with db.connect(write=True) as conn:
        record=dict(conn.execute('SELECT * FROM notices WHERE id=?',(nid,)).fetchone())
        assert notice_processing(conn,record,180,now)
        conn.execute("UPDATE executions SET status='failed' WHERE id=?",(key,))
        assert not notice_processing(conn,record,180,now)
        conn.execute("UPDATE executions SET status='running' WHERE id=?",(key,))
        conn.execute('UPDATE execution_owners SET expires_at=?',(now-1,))
        assert not notice_processing(conn,record,180,now)
        conn.execute('DELETE FROM executions WHERE id=?',(key,))
        assert notice_processing(conn,record,180,now)
        assert not notice_processing(conn,{**record,'processing_at':now-600},180,now)


@pytest.mark.parametrize('kind',['conversation','notice'])
def test_expired_run_cannot_clear_a_newer_processing_token(env,kind):
    c=account(env);key,target,_=pending(env,c,kind);db=env[0].state.db
    table='conversations' if kind=='conversation' else 'notices'
    with db.connect(write=True) as conn:
        conn.execute('UPDATE execution_owners SET expires_at=0')
        conn.execute('UPDATE '+table+' SET processing_token=? WHERE id=?',('newer-fence',target))
    Runtime(db).tick()
    with db.connect() as conn:
        assert conn.execute('SELECT processing_token FROM '+table+' WHERE id=?',(target,)).fetchone()[0]=='newer-fence'
        record_table='conversation_messages' if kind=='conversation' else 'ai_calls'
        assert conn.execute('SELECT status FROM '+record_table+' WHERE id=?',(key,)).fetchone()[0]==('failed' if kind=='conversation' else 'interrupted')
        env[0].state.execution.finish(conn,key,'succeeded','late_response')
        assert conn.execute('SELECT status FROM executions WHERE id=?',(key,)).fetchone()[0]=='interrupted'


def test_complete_replay_is_one_execution_and_other_account_cannot_read_it(env,monkeypatch):
    c=account(env);other=account(env,'other');chat=material(c,conversation(c))
    monkeypatch.setattr(chat_ai,'reply',fixture_answer)
    saved,body=send(c,chat)
    assert c.post('/api/conversations/'+chat['id']+'/messages',json=body).status_code==200
    records=c.get('/api/executions').json()['items']
    assert len(records)==1 and records[0]['status']=='succeeded'
    assert other.get('/api/executions').json()['items']==[]
    assert not {'processing_token','owner_id','profile','content'}&records[0].keys()


def test_unexpected_sync_provider_failure_does_not_leave_processing_forever(env,monkeypatch):
    c=account(env);chat=conversation(c)
    def fail(*args):raise RuntimeError('synthetic crash')
    monkeypatch.setattr(chat_ai,'reply',fail)
    with pytest.raises(RuntimeError):send(c,chat)
    restored=c.get('/api/conversations/'+chat['id']).json()
    assert not restored['processing'] and restored['messages'][-1]['status']=='failed'
    assert c.get('/api/executions').json()['items'][0]['stop_reason']=='interrupted_request'


def test_notice_personal_profile_change_discards_old_draft(env,monkeypatch):
    c=account(env);n=notice(c);env[1].ai_api_key='synthetic';db=env[0].state.db
    def generate(*args):
        with db.connect(write=True) as conn:conn.execute("UPDATE users SET profile=? WHERE id=?",(json.dumps({'school':'不同学院'}),uid(c)))
        return {'title':'旧条件草稿'}, {'input_tokens':1,'output_tokens':1}
    monkeypatch.setattr(ai,'generate',generate)
    r=c.post('/api/notices/'+n['id']+'/generate',json={'version':n['version'],'allow_external_processing':True})
    assert r.status_code==409
    current=c.get('/api/notices/'+n['id']).json()
    assert current['status']=='failed' and current['draft'] is None
    assert c.get('/api/executions').json()['items'][0]['status']=='discarded'


def test_restore_marks_live_execution_interrupted_and_rejects_future_schema(env,tmp_path):
    c=account(env);key,_,_=pending(env,c);backup=tmp_path/'runs.sqlite3';env[0].state.db.backup(backup)
    dest=tmp_path/'restored.sqlite3';restore_database(backup,dest)
    db=Database(dest)
    with db.connect() as conn:
        run=conn.execute('SELECT * FROM executions WHERE id=?',(key,)).fetchone()
        assert run['status']=='interrupted' and run['stop_reason']=='backup_restored'
    with sqlite3.connect(backup) as conn:conn.execute("UPDATE meta SET value='999' WHERE key='execution_schema_version'")
    with pytest.raises(ValueError,match='执行'):restore_database(backup,tmp_path/'bad.sqlite3')
    with pytest.raises(RuntimeError,match='执行'):Database(backup)


def test_shutdown_releases_its_jobs_but_not_other_owners(env):
    c=account(env);mine,_,_=pending(env,c);other=Runtime(env[0].state.db);theirs,_,_=pending(env,c,runtime=other)
    env[0].state.execution.close()
    with env[0].state.db.connect() as conn:
        status={r['id']:r['status'] for r in conn.execute('SELECT * FROM executions')}
    assert status[mine]=='interrupted' and status[theirs]=='running'
