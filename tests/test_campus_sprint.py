"""Regression for the sprint's demonstrated campus boundary failures.

Synthetic recipients/attachments; no school account, mail or push provider.
"""
import hashlib
import io
import json
import os
import uuid

from PIL import Image

from app import campus
from app.db import ident
from tests.test_campus_permissions import actors, assign, CLASS1, CLASS2, publication, publish
from tests.test_workflow import account, confirm, env, manual, notice, PASSWORD


def ok(response):
    assert response.status_code==200,response.text
    return response.json()


def reviewed(client,payload):
    review=ok(client.post('/api/campus/audience-review',json={key:payload[key] for key in ('audience','grade','class_name')}))
    return {**payload,'audience_review':review['review']}


def make_case(env,with_file=False):
    site,manager,counselor,student,other,_=actors(env)
    tid=confirm(student,manual(student,notice(student)))
    task=ok(student.get(f'/api/tasks/{tid}/workflow'))['task']
    if with_file:
        ok(student.post(f'/api/tasks/{tid}/materials',data={'request_id':uuid.uuid4().hex,'requirement':'申请表',
            'task_version':task['version'],'workflow_version':task['workflow']['version']},
            files={'file':('本人申请.txt',b'owned private material','text/plain')}))
    options=ok(student.get(f'/api/collaboration/tasks/{tid}/options'))
    payload={'task_id':tid,'task_version':options['version'],'recipient_id':ok(counselor.get('/api/session'))['user']['id'],
             'note':'本人需要核对材料','request_id':uuid.uuid4().hex,'files':[
                 {k:f[k] for k in ('material_id','version')} for f in options['files']]}
    result=ok(student.post('/api/collaboration',json=payload))
    return site,manager,counselor,student,other,result


def test_missing_expired_review_rejected_but_committed_retry_is_returned(env):
    _,_,counselor,student,_,_=actors(env)
    payload=publication()
    assert counselor.post('/api/campus/publications',json=payload).status_code==409
    reviewed_payload=reviewed(counselor,payload)
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE campus_audience_reviews SET expires_at=0')
    assert counselor.post('/api/campus/publications',json=reviewed_payload).status_code==409
    assert student.get('/api/notices').json()==[]
    fresh=reviewed(counselor,payload)
    sent=ok(counselor.post('/api/campus/publications',json=fresh))
    # A lost response can be recovered after the review expires, including a
    # retry client that no longer has the original review token.
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('DELETE FROM campus_audience_reviews')
    assert ok(counselor.post('/api/campus/publications',json=payload))['id']==sent['id']
    assert len(student.get('/api/notices').json())==1


def test_review_changes_when_same_identity_is_reauthorized(env):
    _,manager,counselor,_,_,_=actors(env)
    payload=reviewed(counselor,publication())
    # Same members, same count, but a new explicit grant invalidates the review.
    assert assign(manager,'student-one','student',version=1,**CLASS1).status_code==200
    assert counselor.post('/api/campus/publications',json=payload).status_code==409


def test_shared_immutable_attachment_batches_survive_restart_and_keep_owner_boundary(env):
    _,manager,counselor,student,outsider,_=actors(env)
    db=env[0].state.db
    with db.connect(write=True) as conn:
        for i in range(60):
            uid=ident()
            conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',(uid,f'synthetic-batch-{i}','unusable-password',f'样本{i}','user','{}',0))
            conn.execute('INSERT INTO campus_members VALUES(?,?,?,?,?,1,0,0)',(uid,'sres','student',CLASS1['grade'],CLASS1['class_name']))
    pixels=Image.frombytes('RGB',(600,600),os.urandom(600*600*3))
    out=io.BytesIO();pixels.save(out,format='PNG');original=out.getvalue()
    assert len(original)*63>50*1024*1024  # Previously rejected by recipients × bytes.
    sent=ok(publish(counselor,publication(),files=[('files',('合成附件.png',original,'image/png'))]))
    assert sent['delivery']['pending']>0 and sent['delivery']['delivered']<=campus.DELIVERY_BATCH_SIZE
    from app.db import Database
    recovered=Database(db.path,db.usage_limits)
    while campus.drain_publications(recovered)['processed']:
        pass
    latest=ok(counselor.get('/api/campus/publications/'+sent['id']))
    assert latest['delivery']['pending']==0 and latest['delivery']['failed']==0
    assert latest['delivery']['delivered']==63
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_material_refs').fetchone()[0]==63
        assert conn.execute('SELECT sum(length(content)) FROM sources').fetchone()[0] is None
        assert conn.execute('SELECT sum(length(content)) FROM campus_materials').fetchone()[0]==len(original)
        from app.notice_ingest import personal_storage_bytes
        uid=ok(student.get('/api/session'))['user']['id']
        assert personal_storage_bytes(conn,uid)==len(original)
    detail=ok(student.get('/api/notices/'+student.get('/api/notices').json()[0]['id']))
    source=next(s for s in detail['sources'] if s['kind']=='png')
    url=f"/api/notices/{detail['id']}/sources/{source['id']}/download"
    assert student.get(url).content==original
    assert outsider.get(url).status_code==404
    changed=ok(counselor.post('/api/campus/publications/'+sent['id']+'/correct',json={
        'version':1,'title':'正式更正','body':'重新核对办理时间','keep_attachments':False}))
    campus.drain_publications(db,publication_id=sent['id'],limit=1000)
    assert student.get(url).content==original  # Historical own evidence is immutable.


def test_queued_delivery_rechecks_member_and_publisher_authority(env,monkeypatch):
    _,manager,counselor,student,_,_=actors(env)
    real=campus.drain_publications
    monkeypatch.setattr(campus,'drain_publications',lambda *args,**kwargs:{'processed':0})
    sent=ok(publish(counselor,publication()))
    assert sent['delivery']['pending']==3
    assert assign(manager,'student-one','student',version=1,**CLASS2).status_code==200
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    monkeypatch.setattr(campus,'drain_publications',real)
    real(env[0].state.db)
    assert student.get('/api/notices').json()==[]
    latest=ok(manager.get('/api/campus/publications/'+sent['id']))
    assert latest['delivery']['failed']==3
    retried=ok(manager.post('/api/campus/publications/'+sent['id']+'/retry'))
    assert retried['delivery']['out_of_scope']==2  # Former student and former counselor.
    assert retried['delivery']['delivered']==1


def test_server_draft_version_and_files_restore_then_publish_once(env):
    _,manager,counselor,student,_,_=actors(env)
    data={'version':0,**{k:v for k,v in publication().items() if k!='request_id'}}
    draft=ok(counselor.put('/api/campus/drafts/persistent-draft',data={'data':json.dumps(data)},
            files=[('files',('模板.txt',b'saved original','text/plain'))]))
    assert draft['state']=='draft' and draft['attachments'][0]['size']==14
    assert student.get('/api/notices').json()==[]
    assert manager.get('/api/campus/drafts/persistent-draft').status_code==404
    assert counselor.put('/api/campus/drafts/persistent-draft',json=data).status_code==409
    assert ok(counselor.get('/api/campus/drafts'))['items'][0]['id']=='persistent-draft'
    payload={**publication(),'draft_id':'persistent-draft','draft_version':draft['version']}
    sent=ok(publish(counselor,payload))
    assert sent['attachments'][0]['sha256']==hashlib.sha256(b'saved original').hexdigest()
    assert counselor.get('/api/campus/drafts/persistent-draft').status_code==404
    assert ok(counselor.post('/api/campus/publications',json=payload))['id']==sent['id']
    assert len(student.get('/api/notices').json())==1


def test_official_restore_has_new_evidence_and_does_not_reopen_personal_work(env):
    _,_,counselor,student,_,_=actors(env)
    sent=ok(publish(counselor,publication()))
    first=student.get('/api/notices').json()[0]
    nid=first['id']
    checked=ok(student.post('/api/notices/'+nid+'/materials',json={'version':first['version'],'complete':True}))
    tid=confirm(student,manual(student,checked))
    before=ok(student.get('/api/tasks/'+tid+'/workflow'))['task']
    ok(counselor.post('/api/campus/publications/'+sent['id']+'/withdraw',json={'version':1,'reason':'原场次取消'}))
    assert student.post('/api/campus/publications/'+sent['id']+'/restore',json={
        'version':2,'title':'恢复','body':'新场次','reason':'已重新确认'}).status_code==403
    assert counselor.post('/api/campus/publications/'+sent['id']+'/restore',json={
        'version':2,'title':'恢复','body':'新场次','reason':'   '}).status_code==422
    restored=ok(counselor.post('/api/campus/publications/'+sent['id']+'/restore',json={
        'version':2,'title':'恢复通知','body':'新场次以新原文为准','reason':'发布方已重新确认场次'}))
    assert (restored['state'],restored['version'])==('published',3)
    assert restored['version_context']['kind']=='restore'
    assert restored['version_context']['reason']=='发布方已重新确认场次'
    assert student.get('/api/notices').json()[0]['id']==nid
    after=ok(student.get('/api/tasks/'+tid+'/workflow'))['task']
    assert after['version']==before['version'] and after['data']==before['data']
    assert len(ok(counselor.get('/api/campus/publications/'+sent['id']))['history'])==3


def test_recipient_deletion_preserves_students_minimal_receipt_and_revokes_files(env):
    site,manager,counselor,student,other,case=make_case(env,with_file=True)
    path='/api/collaboration/'+case['id']
    file_url=case['events'][0]['files'][0]['download_url']
    ok(counselor.post(path+'/actions',json={'version':1,'action':'accept','note':'受理方私密批注',
                                          'request_id':uuid.uuid4().hex}))
    impact=ok(counselor.get('/api/account/deletion-impact'))
    assert impact['retained_counterparty_receipts']==1
    deleted=ok(counselor.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    assert deleted['shared_file_access']=='revoked'
    retained=ok(student.get(path))
    assert retained['state']=='retained' and not retained['actions'] and not retained['recipient_available']
    assert retained['recipient']=='已注销账号' and '受理方私密批注' not in json.dumps(retained,ensure_ascii=False)
    assert '本人需要核对材料' in json.dumps(retained,ensure_ascii=False)
    assert student.get(file_url).status_code==404
    assert site.get(path).status_code==other.get(path).status_code==404
    assert ok(student.get('/api/collaboration',params={'side':'sender'}))['items'][0]['id']==case['id']
    assert ok(student.get('/api/tasks/'+case['task_id']+'/materials'))['materials']


def test_sender_deletion_anonymizes_staff_receipt_and_scope_is_still_enforced(env):
    site,manager,counselor,student,other,case=make_case(env,with_file=True)
    path='/api/collaboration/'+case['id']
    ok(student.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    retained=ok(counselor.get(path))
    assert retained['title']=='已注销账号的协作回执' and retained['sender']=='已注销账号'
    assert '本人需要核对材料' not in json.dumps(retained,ensure_ascii=False)
    assert '本人申请.txt' not in json.dumps(retained,ensure_ascii=False)
    assert retained['events'][0]['files']==[]
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    assert counselor.get(path).status_code==404
    assert ok(counselor.get('/api/collaboration'))['items']==[]


def test_decline_closes_only_collaboration_and_blocks_shared_download(env):
    _,_,counselor,student,_,case=make_case(env,with_file=True)
    path='/api/collaboration/'+case['id']
    payload={'version':1,'action':'decline','note':'','request_id':uuid.uuid4().hex}
    assert counselor.post(path+'/actions',json=payload).status_code==422
    declined=ok(counselor.post(path+'/actions',json={**payload,'note':'该事项已改由另一位负责人受理，请另行确认分享对象'}))
    assert declined['state']=='declined' and declined['actions']==[]
    assert counselor.get(case['events'][0]['files'][0]['download_url']).status_code==404
    assert ok(student.get('/api/tasks/'+case['task_id']+'/workflow'))['task']['status']=='pending'


def test_roster_preflight_normalizes_years_reports_every_error_and_replays_once(env):
    _,manager,_,_,_,_=actors(env)
    draft={'college_id':'sres','rows':[
        {'username':'student-one','role':'student','grade':'2026','class_name':' 一班 '},
        {'username':'student-one','role':'student','grade':'2026级','class_name':'一班'},
        {'username':'not-registered','role':'student','grade':'2026级','class_name':'一班'}]}
    preview=ok(manager.post('/api/campus/roster/preview',json=draft))
    assert preview['valid']==1 and preview['invalid']==2
    assert preview['items'][0]['normalized']['grade']=='2026级'
    assert preview['items'][1]['errors'] and preview['items'][2]['errors']
    request={'review':preview['review'],'indices':[0],'reviewed':True}
    result=ok(manager.post('/api/campus/roster/commit',json=request))
    assert result['changed']==0  # Reauthorizing identical state does not bump it.
    assert ok(manager.post('/api/campus/roster/commit',json=request))==result
    assert manager.post('/api/campus/roster/commit',json={**request,'indices':[1]}).status_code==409


def test_roster_preflight_rejects_membership_changes_and_cannot_self_escalate(env):
    _,manager,_,_,_,_=actors(env)
    preview=ok(manager.post('/api/campus/roster/preview',json={'college_id':'sres','rows':[
        {'username':'student-one','role':'student',**CLASS2},
        {'username':'college-admin','role':'student',**CLASS1}]}))
    assert preview['items'][1]['errors']
    assert assign(manager,'student-one','student',version=1,**CLASS1).status_code==200
    response=manager.post('/api/campus/roster/commit',json={'review':preview['review'],'indices':[0],'reviewed':True})
    assert response.status_code==409


def test_backup_restore_requires_new_grants_and_fresh_review_before_queue_retry(env,tmp_path,monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.backups import restore_database
    from app.main import create_app
    from tests.test_workflow import ORIGIN
    _,_,counselor,_,_,_=actors(env)
    old_payload=reviewed(counselor,publication())
    real=campus.drain_publications
    monkeypatch.setattr(campus,'drain_publications',lambda *args,**kwargs:{'processed':0})
    sent=ok(counselor.post('/api/campus/publications',json=old_payload))
    monkeypatch.setattr(campus,'drain_publications',real)
    assert sent['delivery']['pending']==3
    backup=tmp_path/'campus-original.sqlite3';env[0].state.db.backup(backup)
    restored_dir=tmp_path/'restored-campus';restore_database(backup,restored_dir/'campus.sqlite3')
    app=create_app(replace(env[1],data_dir=restored_dir))
    def login(name):
        client=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
        ok(client.post('/api/auth/login',json={'username':name,'password':PASSWORD}))
        client.headers['X-CSRF-Token']=ok(client.get('/api/session'))['csrf']
        return client
    site=login('site-admin');manager=login('college-admin');student=login('student-one')
    assert student.get('/api/notices').json()==[]
    assert assign(site,'college-admin','college_admin').status_code==200
    assert assign(manager,'counselor','counselor',scopes=[CLASS1]).status_code==200
    assert assign(manager,'student-one','student',**CLASS1).status_code==200
    endpoint='/api/campus/publications/'+sent['id']+'/retry'
    assert manager.post(endpoint).status_code==409
    assert manager.post(endpoint,json={'audience_review':old_payload['audience_review']}).status_code==409
    review=ok(manager.post('/api/campus/audience-review',json={'audience':'class',**CLASS1}))
    assert ok(manager.post(endpoint,json={'audience_review':review['review']}))['delivery']['delivered']==3
    assert len(student.get('/api/notices').json())==1


def test_transfer_requires_sender_reselection_and_never_copies_private_history(env):
    _,manager,counselor,student,_,case=make_case(env,with_file=True)
    path='/api/collaboration/'+case['id']
    manager_id=ok(manager.get('/api/session'))['user']['id']
    options=ok(student.get('/api/collaboration/tasks/'+case['task_id']+'/options'))
    payload={'version':case['version'],'task_version':options['version'],'recipient_id':manager_id,
             'note':'请核对新的办理对象','request_id':uuid.uuid4().hex,'files':[]}
    assert counselor.post(path+'/transfer',json=payload).status_code==403
    transferred=ok(student.post(path+'/transfer',json=payload))
    assert transferred['id']!=case['id'] and transferred['events'][0]['files']==[]
    assert transferred['recipient_id']==manager_id and transferred['previous_case_id']==case['id']
    assert ok(student.get(path))['state']=='withdrawn'
    assert counselor.get(case['events'][0]['files'][0]['download_url']).status_code==404
    new=ok(manager.get('/api/collaboration/'+transferred['id']))
    assert len(new['events'])==1 and '本人需要核对材料' not in json.dumps(new,ensure_ascii=False)
    assert ok(student.post(path+'/transfer',json=payload))['id']==transferred['id']
    assert student.post(path+'/transfer',json={**payload,'note':'重放改动'}).status_code==409


def test_publisher_deletion_keeps_already_received_original_and_anonymizes_author(env):
    _,manager,counselor,student,_,_=actors(env)
    sent=ok(publish(counselor,publication(),files=[('files',('正式模板.txt',b'immutable official original','text/plain'))]))
    item=student.get('/api/notices').json()[0]
    detail=ok(student.get('/api/notices/'+item['id']))
    source=next(s for s in detail['sources'] if s['kind']=='txt')
    url=f"/api/notices/{item['id']}/sources/{source['id']}/download"
    ok(counselor.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}))
    assert student.get(url).content==b'immutable official original'
    publication_view=ok(manager.get('/api/campus/publications/'+sent['id']))
    assert publication_view['publisher_name']=='已注销发布者'
    with env[0].state.db.connect() as conn:assert not conn.execute('PRAGMA foreign_key_check').fetchone()


def test_campus_audit_cursor_does_not_lose_or_repeat_rows(env):
    _,manager,_,_,_,_=actors(env)
    first=ok(manager.get('/api/campus/audit',params={'college_id':'sres','page_size':2}))
    second=ok(manager.get('/api/campus/audit',params={'college_id':'sres','page_size':2,'before_id':first['next_cursor']}))
    assert first['has_more'] and not {x['id'] for x in first['items']} & {x['id'] for x in second['items']}
    assert min(x['id'] for x in first['items'])>max(x['id'] for x in second['items'])
    denied=account(env,'ordinary-roster-reader')
    assert denied.get('/api/campus/audit',params={'college_id':'sres'}).status_code==403


def test_decline_reminder_is_an_owned_current_scope_event_not_a_school_result(env):
    import time
    from app.collaboration import reminders
    _,manager,counselor,student,other,case=make_case(env)
    ok(counselor.post('/api/collaboration/'+case['id']+'/actions',json={
        'version':1,'action':'decline','note':'我不再负责此事，请重新确认负责人','request_id':uuid.uuid4().hex}))
    uid=ok(student.get('/api/session'))['user']['id'];other_id=ok(other.get('/api/session'))['user']['id']
    with env[0].state.db.connect() as conn:
        result=reminders(conn,uid,int(time.time()))
        assert len(result)==1 and result[0]['id']==case['id'] and result[0]['state']=='declined'
        assert reminders(conn,other_id,int(time.time()))==[]
    assert assign(manager,'counselor','counselor',version=1,scopes=[CLASS2]).status_code==200
    with env[0].state.db.connect() as conn:assert reminders(conn,uid,int(time.time()))==[]


def test_normalization_preview_shows_exact_recipient_change_without_mutating_it(env):
    _,manager,counselor,student,_,_=actors(env)
    # Legacy non-canonical labels are kept until a manager reviews the move.
    assert assign(manager,'counselor','counselor',version=1,scopes=[{'grade':'2026','class_name':'一班'}]).status_code==200
    assert assign(manager,'student-one','student',version=1,grade='2026',class_name='一班').status_code==200
    sent=ok(publish(counselor,publication(grade='2026')))
    preview=ok(manager.post('/api/campus/roster/normalization-preview',json={'college_id':'sres'}))
    assert len(preview['items'])==2 and preview['valid']==2
    impact=next(item for item in preview['audience_impacts'] if item['grade']=='2026')
    assert set(impact['removed'])=={'counselor','student-one'}
    assert (impact['before_count'],impact['after_count'])==(3,1)
    # Merely opening the preview changes neither grants nor personal evidence.
    assert ok(student.get('/api/campus/context'))['membership']['grade']=='2026'
    assert len(student.get('/api/notices').json())==1
    saved=ok(manager.post('/api/campus/roster/commit',json={
        'review':preview['review'],'indices':[item['index'] for item in preview['items']],'reviewed':True}))
    assert saved['changed']==2 and saved['audience_impacts']==preview['audience_impacts']
    assert ok(student.get('/api/campus/context'))['membership']['grade']=='2026级'
    assert len(student.get('/api/notices').json())==1
    assert ok(manager.get('/api/campus/publications/'+sent['id']))['grade']=='2026'


def test_process_restart_invalidates_uncommitted_review_but_preserves_draft(env):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.test_workflow import ORIGIN
    _,_,counselor,_,_,_=actors(env)
    payload=reviewed(counselor,publication())
    ok(counselor.put('/api/campus/drafts/restart-draft',json={'version':0,'title':'尚未正式公告','body':'待核对正文'}))
    restarted=create_app(env[1])
    client=TestClient(restarted,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    ok(client.post('/api/auth/login',json={'username':'counselor','password':PASSWORD}))
    client.headers['X-CSRF-Token']=ok(client.get('/api/session'))['csrf']
    assert client.post('/api/campus/publications',json=payload).status_code==409
    assert ok(client.get('/api/campus/drafts/restart-draft'))['body']=='待核对正文'
    assert ok(publish(client,publication()))['delivery']['delivered']==3


def test_publication_rollback_keeps_all_versions_and_exact_immutable_originals(env):
    _,_,counselor,student,other,_=actors(env)
    sent=ok(publish(counselor,publication(),files=[('files',('原版模板.txt',b'original version','text/plain'))]))
    pid=sent['id'];nid=student.get('/api/notices').json()[0]['id']
    updated=ok(counselor.post('/api/campus/publications/'+pid+'/correct',json={
        'version':1,'title':'改错的标题','body':'改错的正文','keep_attachments':False}))
    assert updated['change_summary']['body_changed']
    assert updated['change_summary']['attachments_removed']==['原版模板.txt']
    rolled=ok(counselor.post('/api/campus/publications/'+pid+'/rollback',json={
        'version':2,'target_version':1,'reason':'发布者重新核对原文，恢复原模板'}))
    assert rolled['version']==3 and rolled['body']==publication()['body']
    assert rolled['version_context']['kind']=='rollback' and rolled['version_context']['target_version']==1
    detail=ok(counselor.get('/api/campus/publications/'+pid))
    assert len(detail['history'])==3 and detail['history'][1]['body']=='改错的正文'
    download=detail['history'][0]['attachments'][0]['download_url']
    assert counselor.get(download).content==b'original version'
    assert student.get(download).status_code==403 and other.get(download).status_code==403
    owned=ok(student.get('/api/notices/'+nid))
    old_source=next(source for source in owned['sources'] if source['kind']=='txt')
    assert old_source['active'] and student.get(f"/api/notices/{nid}/sources/{old_source['id']}/download").content==b'original version'
    assert counselor.post('/api/campus/publications/'+pid+'/rollback',json={
        'version':2,'target_version':1,'reason':'旧页面再点'}).status_code==409


def test_manager_corrections_charge_the_actual_version_author_without_losing_old_material(env):
    from dataclasses import replace
    _,manager,counselor,student,_,_=actors(env)
    sent=ok(publish(counselor,publication(),files=[('files',('原件.txt',b'12345678','text/plain'))]))
    db=env[0].state.db
    db.usage_limits=replace(db.usage_limits,storage_bytes=12)
    path='/api/campus/publications/'+sent['id']
    corrected=ok(manager.post(path+'/correct',json={
        'version':1,'title':'管理者核对更正','body':'更新正文','keep_attachments':True}))
    assert corrected['version']==2
    # Retaining originals consumes storage once per immutable authored version;
    # repeatedly correcting someone else's publication cannot bypass this cap.
    rejected=manager.post(path+'/correct',json={
        'version':2,'title':'再次更正','body':'再次更新正文','keep_attachments':True})
    assert rejected.status_code==413
    detail=ok(manager.get(path))
    assert detail['version']==2 and len(detail['history'])==2
    nid=student.get('/api/notices').json()[0]['id']
    source=next(s for s in ok(student.get('/api/notices/'+nid))['sources'] if s['kind']=='txt')
    assert student.get(f"/api/notices/{nid}/sources/{source['id']}/download").content==b'12345678'
