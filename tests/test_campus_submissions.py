"""Durable cancellation of an uncertain publication, using real HTTP and SQLite.

Synthetic campus members only. Cancellation never withdraws an existing notice
and cannot grant publishing rights or silently replace the confirmed request.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3
from threading import Barrier, Event

from fastapi.testclient import TestClient
import pytest

from app import campus
from app.backups import restore_database
from app.db import Database
from app.main import create_app
from tests.test_campus_permissions import actors, assign, CLASS1, CLASS2, publication, publish
from tests.test_campus_sprint import ok, reviewed
from tests.test_workflow import env, ORIGIN, PASSWORD


def cancel(client, request_id):
    return client.post('/api/campus/submissions/' + request_id + '/cancel')


def draft_data(**changes):
    return {'version':0, **{k:v for k,v in publication().items() if k!='request_id'}, **changes}


def test_stale_draft_can_be_stopped_without_reusing_its_confirmed_request(env):
    _,_,counselor,student,_,_=actors(env)
    path='/api/campus/drafts/original-confirmed-draft'
    first=ok(counselor.put(path,json=draft_data()))
    original=reviewed(counselor,{**publication(), 'draft_id':first['id'],'draft_version':first['version']})
    # Another editor can legitimately save the server draft after this editor
    # has confirmed its version, before the original publication reaches SQLite.
    changed=ok(counselor.put(path,json=draft_data(version=first['version'],body='另一页保存的新正文。')))
    stale=counselor.post('/api/campus/publications',json=original)
    assert stale.status_code==409 and '草稿' in stale.json()['detail']
    stopped=cancel(counselor,original['request_id'])
    assert stopped.status_code==200,stopped.text
    assert stopped.json()=={'state':'cancelled'}
    late=counselor.post('/api/campus/publications',json=original)
    assert late.status_code==409 and late.json()['detail']['code']=='publication_cancelled'
    assert student.get('/api/notices').json()==[]
    # Only after the explicit cancellation is acknowledged does this caller
    # start a separately reviewed request, using the actual new draft version.
    fresh=reviewed(counselor,{**publication(request_id='separate-new-request',body=changed['body']),
                             'draft_id':changed['id'],'draft_version':changed['version']})
    sent=ok(counselor.post('/api/campus/publications',json=fresh))
    assert len(student.get('/api/notices').json())==1
    assert ok(counselor.get('/api/campus/publications/'+sent['id']))['body']==changed['body']
    assert cancel(counselor,original['request_id']).json()=={'state':'cancelled'}
    assert counselor.post('/api/campus/publications',json=original).status_code==409


def test_cancelling_an_already_published_request_only_returns_its_identity(env):
    _,_,counselor,student,_,_=actors(env)
    request=reviewed(counselor,publication());sent=ok(counselor.post('/api/campus/publications',json=request))
    before=ok(counselor.get('/api/campus/publications/'+sent['id']))
    received=student.get('/api/notices').json()
    def persisted():
        with env[0].state.db.connect() as conn:
            return {table:[dict(row) for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                    for table in ('campus_publications','campus_publication_versions','campus_materials',
                                  'campus_deliveries','notices','sources')}
    records=persisted()
    for _ in range(2):
        assert ok(cancel(counselor,request['request_id']))=={'state':'published','publication_id':sent['id']}
    assert ok(counselor.get('/api/campus/publications/'+sent['id']))==before
    # Projected assessments contain the live evaluation clock. Compare exact
    # persisted business data and recipient IDs rather than a clock snapshot.
    assert [row['id'] for row in student.get('/api/notices').json()]==[row['id'] for row in received]
    assert persisted()==records
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==0
    assert ok(counselor.post('/api/campus/publications',json=request))['id']==sent['id']


def test_cancellation_response_loss_and_restart_never_reopen_the_request(env):
    _,_,counselor,student,_,_=actors(env);request=reviewed(counselor,publication())
    # Ignore the first committed response, just as a disconnected client would.
    first=cancel(counselor,request['request_id']);assert first.status_code==200,first.text
    db=env[0].state.db;Database(db.path,db.usage_limits)
    assert ok(cancel(counselor,request['request_id']))=={'state':'cancelled'}
    assert counselor.post('/api/campus/publications',json=request).status_code==409
    assert student.get('/api/notices').json()==[]
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==1


def test_cancel_and_publish_have_one_atomic_outcome_under_competing_requests(env):
    _,_,counselor,student,_,_=actors(env);request=reviewed(counselor,publication())
    barrier=Barrier(2)
    def stop():barrier.wait(timeout=5);return cancel(counselor,request['request_id'])
    def send():barrier.wait(timeout=5);return counselor.post('/api/campus/publications',json=request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled=pool.submit(stop);published=pool.submit(send)
        stopped=cancelled.result(timeout=20);sent=published.result(timeout=20)
    assert stopped.status_code==200,stopped.text
    with env[0].state.db.connect() as conn:
        rows=conn.execute('SELECT id FROM campus_publications').fetchall()
        tombstones=conn.execute('SELECT request_id FROM campus_submission_cancellations').fetchall()
    if stopped.json()['state']=='cancelled':
        assert sent.status_code==409 and sent.json()['detail']['code']=='publication_cancelled'
        assert len(rows)==0 and len(tombstones)==1 and student.get('/api/notices').json()==[]
    else:
        assert sent.status_code==200,sent.text
        assert stopped.json()=={'state':'published','publication_id':sent.json()['id']}
        assert len(rows)==1 and len(tombstones)==0 and len(student.get('/api/notices').json())==1


def test_an_already_parsed_late_publication_cannot_bypass_committed_cancellation(env,monkeypatch):
    _,_,counselor,student,_,_=actors(env);request=reviewed(counselor,publication())
    entered,release=Event(),Event();original=campus.request_materials
    async def delayed(request,model):
        parsed=await original(request,model)
        if model is campus.Publication:
            entered.set();assert await asyncio.to_thread(release.wait,10)
        return parsed
    monkeypatch.setattr(campus,'request_materials',delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(lambda:counselor.post('/api/campus/publications',json=request))
        try:
            assert entered.wait(5)
            assert ok(cancel(counselor,request['request_id']))=={'state':'cancelled'}
        finally:release.set()
        result=pending.result(timeout=15)
    assert result.status_code==409 and result.json()['detail']['code']=='publication_cancelled'
    assert student.get('/api/notices').json()==[]


def test_cancellation_is_owner_scoped_and_preserves_current_publisher_authority(env):
    _,manager,counselor,student,_,_=actors(env);request=reviewed(counselor,publication())
    # The same opaque request ID in another account is an unrelated operation.
    assert ok(cancel(manager,request['request_id']))=={'state':'cancelled'}
    sent=ok(counselor.post('/api/campus/publications',json=request))
    assert ok(cancel(manager,request['request_id']))=={'state':'cancelled'}
    assert cancel(student,request['request_id']).status_code==403
    assert TestClient(env[0],base_url=ORIGIN).post('/api/campus/submissions/'+request['request_id']+'/cancel',
        headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'}).status_code==401
    # The minimal receipt belongs to this request's owner. It can release the
    # uncertain editor intent without granting access to old scoped contents.
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    assert ok(cancel(counselor,request['request_id']))=={'state':'published','publication_id':sent['id']}
    assert counselor.get('/api/campus/publications/'+sent['id']).status_code==403
    assert counselor.post('/api/campus/publications',json=request).status_code==403
    assert ok(manager.get('/api/campus/publications/'+sent['id']))['state']=='published'
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==1


def test_cross_college_reassignment_keeps_only_the_owners_minimal_submission_receipt(env):
    site,_,counselor,_,_,_=actors(env);request=reviewed(counselor,publication())
    sent=ok(counselor.post('/api/campus/publications',json=request))
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO campus_colleges VALUES('new-college','合成新学院',0)")
    assert assign(site,'counselor','college_admin',version=1,college='new-college').status_code==200
    # Replaying an old POST must not become an alternate endpoint for reading
    # the previous college's text, immutable originals or recipient receipts.
    denied=counselor.post('/api/campus/publications',json=request)
    assert denied.status_code==404,denied.text
    assert counselor.get('/api/campus/publications/'+sent['id']).status_code==404
    assert ok(cancel(counselor,request['request_id']))=={'state':'published','publication_id':sent['id']}
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==0
        assert conn.execute('SELECT state FROM campus_publications WHERE id=?',(sent['id'],)).fetchone()[0]=='published'


@pytest.mark.parametrize('request_id',['short','x'*81,'invalid request-id'])
def test_cancellation_request_identifiers_are_bounded(env,request_id):
    _,_,counselor,_,_,_=actors(env)
    assert cancel(counselor,request_id).status_code==422


def test_pending_attachment_names_survive_legacy_saves_and_block_publication(env):
    _,manager,counselor,student,_,_=actors(env);path='/api/campus/drafts/missing-original-files'
    first=ok(counselor.put(path,json=draft_data(pending_attachment_names=['原申请表.docx','证明材料.pdf'])))
    assert first['pending_attachment_names']==['原申请表.docx','证明材料.pdf'] and first['attachments']==[]
    assert ok(counselor.get(path))['pending_attachment_names']==first['pending_attachment_names']
    assert manager.get(path).status_code==404
    assert student.get(path).status_code==403
    # An older client omits this new field. Saving only text must not assert
    # that the original attachments were uploaded or explicitly abandoned.
    second=ok(counselor.put(path,json=draft_data(version=first['version'],body='正文另存，附件仍待本人处理。')))
    assert second['pending_attachment_names']==first['pending_attachment_names'] and second['attachments']==[]
    request=reviewed(counselor,{**publication(), 'draft_id':second['id'],'draft_version':second['version']})
    denied=counselor.post('/api/campus/publications',json=request)
    assert denied.status_code==409 and denied.json()['detail']['code']=='publication_attachments_pending'
    assert student.get('/api/notices').json()==[]
    resolved=ok(counselor.put(path,json=draft_data(version=second['version'],pending_attachment_names=[])))
    assert resolved['pending_attachment_names']==[] and resolved['attachments']==[]
    sent=ok(publish(counselor,{**publication(request_id='resolved-attachment-request'),
                             'draft_id':resolved['id'],'draft_version':resolved['version']}))
    assert sent['attachments']==[] and len(student.get('/api/notices').json())==1


@pytest.mark.parametrize('names',[[''],[' '],['x'*256],['a','b','c','d'],[7]])
def test_pending_attachment_names_are_only_bounded_metadata(env,names):
    _,_,counselor,_,_,_=actors(env)
    assert counselor.put('/api/campus/drafts/invalid-missing-files',json=draft_data(pending_attachment_names=names)).status_code==422


def test_cancel_tombstones_survive_backup_restore_without_restoring_authority(env,tmp_path):
    _,_,counselor,_,_,_=actors(env);request=reviewed(counselor,publication())
    assert ok(cancel(counselor,request['request_id']))=={'state':'cancelled'}
    db=env[0].state.db;backup=tmp_path/'snapshot.sqlite3';db.backup(backup)
    target=tmp_path/'restored'/'campus.sqlite3';restore_database(backup,target)
    restored=create_app(replace(env[1],data_dir=target.parent))
    def login(name):
        client=TestClient(restored,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
        ok(client.post('/api/auth/login',json={'username':name,'password':PASSWORD}))
        client.headers['X-CSRF-Token']=ok(client.get('/api/session'))['csrf'];return client
    old=login('counselor');assert cancel(old,request['request_id']).status_code==403
    site=login('site-admin');manager=login('college-admin')
    assert assign(site,'college-admin','college_admin').status_code==200
    assert assign(manager,'counselor','counselor',scopes=[CLASS1]).status_code==200
    assert ok(cancel(old,request['request_id']))=={'state':'cancelled'}
    blocked=old.post('/api/campus/publications',json=request)
    assert blocked.status_code==409 and blocked.json()['detail']['code']=='publication_cancelled'
    with restored.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==1
        assert not conn.execute('PRAGMA foreign_key_check').fetchone()


@pytest.mark.parametrize('damage',['missing_table','future_marker'])
def test_cancellation_schema_damage_cannot_be_silently_recreated_or_restored(tmp_path,damage):
    source=tmp_path/'damaged.sqlite3';Database(source)
    with sqlite3.connect(source) as conn:
        if damage=='missing_table':conn.execute('DROP TABLE campus_submission_cancellations')
        else:conn.execute("UPDATE meta SET value='999' WHERE key='campus_submission_schema_version'")
    with pytest.raises(RuntimeError,match='campus_submission_schema_version'):Database(source)
    target=tmp_path/'must-not-exist.sqlite3'
    with pytest.raises(ValueError,match='campus_submission_schema_version'):restore_database(source,target)
    assert not target.exists()


def test_pre_extension_database_migrates_to_empty_cancellation_ledger(tmp_path):
    source=tmp_path/'legacy.sqlite3';Database(source)
    with sqlite3.connect(source) as conn:
        conn.execute('DROP TABLE campus_submission_cancellations')
        conn.execute("DELETE FROM meta WHERE key='campus_submission_schema_version'")
    db=Database(source)
    with db.connect() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='campus_submission_schema_version'").fetchone()[0]=='1'
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==0


def test_cancelled_submission_is_exported_but_cascades_on_account_deletion(env):
    _,manager,counselor,_,_,_=actors(env);uid=ok(counselor.get('/api/session'))['user']['id']
    assert ok(cancel(counselor,'own-cancelled-request'))=={'state':'cancelled'}
    assert ok(cancel(manager,'other-cancelled-request'))=={'state':'cancelled'}
    exported=ok(counselor.get('/api/export'))
    entries=exported['account_records']['campus_submission_cancellations']
    assert len(entries)==1 and entries[0]['request_id']=='own-cancelled-request'
    assert entries[0]['cancelled_at']>0
    preview=ok(manager.post('/api/import',json={'data':exported}))
    ok(manager.post('/api/import',json={'data':exported,'confirm':True,'digest':preview['digest']}))
    manager_entries=ok(manager.get('/api/export'))['account_records']['campus_submission_cancellations']
    assert [entry['request_id'] for entry in manager_entries]==['other-cancelled-request']
    impact=ok(counselor.get('/api/account/deletion-impact'))
    assert impact['deleted']['publication_cancellations']==1
    ok(counselor.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations WHERE user_id=?',(uid,)).fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM campus_submission_cancellations').fetchone()[0]==1
        assert not conn.execute('PRAGMA foreign_key_check').fetchone()
