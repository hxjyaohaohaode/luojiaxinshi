"""Authorization, scoped delivery and privacy, using isolated synthetic users."""
import json

from fastapi import HTTPException

from app import notice_ingest
from app.backups import restore_database
from app.db import Database
from tests.test_workflow import account, confirm, env, manual, notice


COLLEGE = 'sres'
CLASS1 = {'grade': '2026级', 'class_name': '一班'}
CLASS2 = {'grade': '2026级', 'class_name': '二班'}
OTHER = {'grade': '2027级', 'class_name': '一班'}


def assign(actor, username, role, *, version=0, college=COLLEGE, grade='', class_name='', scopes=None):
    return actor.put('/api/campus/members/' + username, json={'college_id': college, 'role': role,
        'grade': grade, 'class_name': class_name, 'scopes': scopes or [], 'version': version})


def actors(env):
    site = account(env, 'site-admin', 'admin')
    manager = account(env, 'college-admin')
    counselor = account(env, 'counselor')
    one = account(env, 'student-one')
    two = account(env, 'student-two')
    three = account(env, 'student-three')
    assert assign(site, 'college-admin', 'college_admin').status_code == 200
    assert assign(manager, 'counselor', 'counselor', scopes=[CLASS1]).status_code == 200
    assert assign(manager, 'student-one', 'student', **CLASS1).status_code == 200
    assert assign(manager, 'student-two', 'student', **CLASS2).status_code == 200
    assert assign(manager, 'student-three', 'student', **OTHER).status_code == 200
    return site, manager, counselor, one, two, three


def publication(audience='class', *, request_id='campus-request-0001', title='资环院课堂通知',
                body='请目标班级核对上课时间并完成登记。', grade='2026级', class_name='一班'):
    if audience == 'college': grade = class_name = ''
    if audience == 'grade': class_name = ''
    return {'audience': audience, 'grade': grade, 'class_name': class_name,
            'title': title, 'body': body, 'request_id': request_id}


def publish(client, payload, files=None):
    if files is None:
        return client.post('/api/campus/publications', json=payload)
    return client.post('/api/campus/publications', data={'data': json.dumps(payload, ensure_ascii=False)}, files=files)


def test_explicit_roles_and_scoped_roster_do_not_open_private_data(env):
    site, manager, counselor, one, two, three = actors(env)
    assert one.get('/api/campus/context').json()['membership']['role'] == 'student'
    assert manager.get('/api/session').json()['user']['campus_membership']['role'] == 'college_admin'
    assert counselor.get('/api/session').json()['user']['campus_membership']['role'] == 'counselor'
    assert one.get('/api/campus/members', params={'college_id': COLLEGE}).status_code == 403
    roster = counselor.get('/api/campus/members', params={'college_id': COLLEGE}).json()['members']
    assert [m['username'] for m in roster] == ['student-one']
    assert assign(counselor, 'student-two', 'student', **CLASS1).status_code == 403
    assert assign(one, 'student-one', 'college_admin').status_code == 403
    assert assign(manager, 'student-one', 'college_admin', version=1).status_code == 403
    assert assign(manager, 'college-admin', 'student', version=1, **CLASS1).status_code == 403
    assert assign(manager, 'student-one', 'student', version=0, **CLASS2).status_code == 409
    assert assign(manager, 'counselor', 'counselor', version=1, scopes=[{}]).status_code == 422
    # Self-reported campus profile is not an authorization grant.
    assert one.put('/api/profile', json={'campus_role': 'teacher', 'college': '武汉大学资源与环境科学学院'}).status_code == 200
    assert publish(one, publication()).status_code == 403
    assert counselor.post('/api/campus/audience-preview', json={'audience': 'college'}).status_code == 403
    assert counselor.post('/api/campus/audience-preview', json={'audience': 'grade', 'grade': '2026级'}).status_code == 403
    assert counselor.post('/api/campus/audience-preview', json={'audience': 'class', **CLASS2}).status_code == 403
    assert counselor.get('/api/campus/audit', params={'college_id': COLLEGE}).status_code == 403
    assert manager.get('/api/campus/audit', params={'college_id': COLLEGE}).status_code == 200
    private = notice(one)
    conversation = one.post('/api/conversations', json={'title': '学生私人对话'}).json()
    assert counselor.get('/api/notices/' + private['id']).status_code == 404
    assert manager.get('/api/notices/' + private['id']).status_code == 404
    assert site.get('/api/notices/' + private['id']).status_code == 404
    assert counselor.get('/api/conversations/' + conversation['id']).status_code == 404
    assert manager.get('/api/conversations/' + conversation['id']).status_code == 404


def test_all_college_counselor_scope_must_be_explicit(env):
    _, manager, counselor, _, _, _ = actors(env)
    assert assign(manager, 'counselor', 'counselor', version=1, scopes=[{'all_college': True}]).status_code == 200
    assert counselor.post('/api/campus/audience-preview', json={'audience': 'college'}).json()['students'] == 3
    assert assign(manager, 'counselor', 'counselor', version=2,
                  scopes=[{'all_college': True, 'grade':'2026级'}]).status_code == 422


def test_college_grade_class_and_attachments_reach_only_intended_students(env):
    _, manager, counselor, one, two, three = actors(env)
    payload = publication()
    # A private, identical prior notice must never merge with an official publication.
    prior = notice(one, text=payload['title'] + '\n\n' + payload['body'])
    preview = counselor.post('/api/campus/audience-preview', json={'audience': 'class', **CLASS1}).json()
    assert preview == {'total': 3, 'students': 1, 'staff': 2}
    files = [('files', ('说明.txt', '请携带有效证件。'.encode(), 'text/plain'))]
    result = publish(counselor, payload, files)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['delivery']['delivered'] == 3 and data['delivery']['students'] == 1
    assert [n['title'] for n in two.get('/api/notices').json()] == []
    assert [n['title'] for n in three.get('/api/notices').json()] == []
    mine = one.get('/api/notices').json()
    assert len(mine) == 2 and prior['id'] in {n['id'] for n in mine}
    received = next(n for n in mine if n['title'] == payload['title'])
    assert '学院工作台发布' in received['source_label'] and '2026级 / 一班' in received['source_label']
    detail = one.get('/api/notices/' + received['id']).json()
    attachment = next(s for s in detail['sources'] if s['kind'] == 'txt')
    assert one.get('/api/notices/' + received['id'] + '/sources/' + attachment['id'] + '/download').content == '请携带有效证件。'.encode()
    assert two.get('/api/notices/' + received['id']).status_code == 404
    assert two.get('/api/notices/' + received['id'] + '/sources/' + attachment['id'] + '/download').status_code == 404
    assert publish(counselor, payload, files).json()['id'] == data['id']
    assert len(one.get('/api/notices').json()) == 2
    assert publish(counselor, {**payload, 'body': '不同内容'}).status_code == 409
    assert publish(manager, publication('grade', request_id='campus-request-0002')).status_code == 200
    assert len(two.get('/api/notices').json()) == 1 and len(three.get('/api/notices').json()) == 0
    assert publish(manager, publication('college', request_id='campus-request-0003')).status_code == 200
    assert len(three.get('/api/notices').json()) == 1
    assert one.get('/api/tasks').json() == []


def test_correction_withdrawal_and_authorization_changes_keep_personal_data(env):
    _, manager, counselor, one, two, _ = actors(env)
    sent = publish(counselor, publication()).json()
    item = one.get('/api/notices').json()[0]
    checked = one.post('/api/notices/' + item['id'] + '/materials', json={'version':item['version'],'complete':True})
    assert checked.status_code == 200
    task_id = confirm(one, manual(one, checked.json()))
    pid = sent['id']
    changed = counselor.post('/api/campus/publications/' + pid + '/correct', json={
        'version': 1, 'title': '资环院课堂通知', 'body': '时间变更，请重新核对。', 'keep_attachments': True})
    assert changed.status_code == 200, changed.text
    assert changed.json()['version'] == 2 and changed.json()['delivery']['delivered'] == 3
    assert one.get('/api/notices').json()[0]['pending_intake_updates'] == 1
    assert [t['id'] for t in one.get('/api/tasks').json()] == [task_id]
    assert counselor.post('/api/campus/publications/' + pid + '/correct', json={
        'version': 1, 'title': '旧页面', 'body': '不应覆盖'}).status_code == 409
    assert assign(manager, 'student-one', 'student', version=1, **CLASS2).status_code == 200
    withdrawn = counselor.post('/api/campus/publications/' + pid + '/withdraw', json={'version': 2, 'reason': '原安排已取消'})
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()['delivery']['out_of_scope'] == 1
    assert one.get('/api/notices/' + item['id']).status_code == 200
    assert len(two.get('/api/notices').json()) == 0  # Published recipients are fixed at publication time.
    assert one.post('/api/campus/publications/' + pid + '/retry').status_code == 403
    assert assign(manager, 'counselor', 'counselor', version=1, scopes=[CLASS2]).status_code == 200
    assert counselor.get('/api/campus/publications').json()['items'] == []
    assert counselor.post('/api/campus/publications/' + pid + '/retry').status_code == 403


def test_delivery_failure_isolated_and_retry_has_no_duplicates(env, monkeypatch):
    _, manager, _, one, two, _ = actors(env)
    affected = one.get('/api/session').json()['user']['id']
    original = notice_ingest.ingest_notice
    def fail_one(conn, uid, **kwargs):
        if uid == affected:
            raise HTTPException(413, '该账号暂时无法收件')
        return original(conn, uid, **kwargs)
    monkeypatch.setattr(notice_ingest, 'ingest_notice', fail_one)
    sent = publish(manager, publication('grade')).json()
    assert sent['delivery']['failed'] == 1 and len(two.get('/api/notices').json()) == 1
    assert one.get('/api/notices').json() == []
    monkeypatch.setattr(notice_ingest, 'ingest_notice', original)
    endpoint = '/api/campus/publications/' + sent['id'] + '/retry'
    assert manager.post(endpoint).json()['delivery']['failed'] == 0
    assert manager.post(endpoint).json()['delivery']['delivered'] >= 2
    assert len(one.get('/api/notices').json()) == len(two.get('/api/notices').json()) == 1


def test_explicit_backfill_only_delivers_to_newly_eligible_members(env):
    _, manager, counselor, one, two, three = actors(env)
    sent = publish(counselor, publication()).json()
    endpoint = '/api/campus/publications/' + sent['id'] + '/deliver-new'
    assert one.post(endpoint).status_code == 403
    assert assign(manager, 'student-two', 'student', version=1, **CLASS1).status_code == 200
    assert two.get('/api/notices').json() == []
    first = counselor.post(endpoint)
    assert first.status_code == 200, first.text
    assert first.json()['delivery']['added'] == 1
    assert len(one.get('/api/notices').json()) == len(two.get('/api/notices').json()) == 1
    assert three.get('/api/notices').json() == []
    assert counselor.post(endpoint).json()['delivery']['added'] == 0
    assert len(two.get('/api/notices').json()) == 1
    assert counselor.post('/api/campus/publications/' + sent['id'] + '/withdraw',
                          json={'version': 1, 'reason': '测试撤回'}).status_code == 200
    assert counselor.post(endpoint).status_code == 409


def test_review_rejects_a_changed_recipient_set_and_keeps_retry_idempotent(env):
    _, manager, counselor, one, two, three = actors(env)
    audience = {'audience': 'class', **CLASS1}
    review = counselor.post('/api/campus/audience-review', json=audience).json()
    assert (review['students'], review['staff'], review['total']) == (1, 2, 3)
    assert len(review['review']) == 64
    # A review cannot be reused by another authorized sender.
    assert publish(manager, {**publication(), 'audience_review': review['review']}).status_code == 409
    # Keep the count unchanged while swapping who will receive it.
    assert assign(manager, 'student-one', 'student', version=1, **CLASS2).status_code == 200
    assert assign(manager, 'student-two', 'student', version=1, **CLASS1).status_code == 200
    stale = publish(counselor, {**publication(), 'audience_review': review['review']})
    assert stale.status_code == 409
    assert one.get('/api/notices').json() == two.get('/api/notices').json() == []
    updated = counselor.post('/api/campus/audience-review', json=audience).json()
    assert (updated['students'], updated['total']) == (1, 3)
    sent = publish(counselor, {**publication(), 'audience_review': updated['review']})
    assert sent.status_code == 200
    assert one.get('/api/notices').json() == [] and len(two.get('/api/notices').json()) == 1
    assert three.get('/api/notices').json() == []
    assert assign(manager, 'student-one', 'student', version=2, **CLASS1).status_code == 200
    retry = publish(counselor, {**publication(), 'audience_review': updated['review']})
    assert retry.status_code == 200 and retry.json()['id'] == sent.json()['id']
    assert len(two.get('/api/notices').json()) == 1 and one.get('/api/notices').json() == []
    assert one.post('/api/campus/audience-review', json=audience).status_code == 403


def test_counselor_records_are_not_hidden_by_other_publishers(env):
    _, manager, counselor, one, _, _ = actors(env)
    sent = publish(counselor, publication()).json()
    publisher_id = manager.get('/api/session').json()['user']['id']
    with env[0].state.db.connect(write=True) as conn:
        for i in range(101):
            pid = 'other-publication-' + str(i)
            conn.execute('INSERT INTO campus_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (pid, COLLEGE, publisher_id, '其他发布者', pid, pid,
                          'college', '', '', 'published', 1, 2000000000 + i, 2000000000 + i))
            conn.execute('INSERT INTO campus_publication_versions VALUES(?,?,?,?,?,?)',
                         (pid, 1, '其他通知', '其他正文', publisher_id, 2000000000 + i))
    visible = counselor.get('/api/campus/publications').json()['items']
    assert [item['id'] for item in visible] == [sent['id']]
    assert len(manager.get('/api/campus/publications').json()['items']) == 100
    first = manager.get('/api/campus/publications', params={'page_size': 10, 'q': '其他通知'}).json()
    last = manager.get('/api/campus/publications', params={'page': 11, 'page_size': 10, 'q': '其他通知'}).json()
    assert (first['total'], first['pages'], len(first['items'])) == (101, 11, 10)
    assert (last['page'], len(last['items'])) == (11, 1)
    assert counselor.get('/api/campus/publications', params={'q': '其他通知'}).json()['total'] == 0
    assert counselor.get('/api/campus/publications', params={'q': '课堂'}).json()['total'] == 1
    assert one.get('/api/campus/publications').status_code == 403
    assert manager.get('/api/campus/publications', params={'page_size': 101}).status_code == 422


def test_cross_college_and_backup_restore_do_not_revive_grants(env, tmp_path):
    site, manager, counselor, one, _, _ = actors(env)
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO campus_colleges VALUES('other','其他学院',0)")
    other = account(env, 'other-college')
    assert assign(site, 'other-college', 'college_admin', college='other').status_code == 200
    assert manager.get('/api/campus/members', params={'college_id':'other'}).status_code == 403
    assert assign(manager, 'other-college', 'student', college='sres', version=1, **CLASS1).status_code == 403
    sent = publish(counselor, publication()).json()
    assert other.post('/api/campus/publications/' + sent['id'] + '/retry').status_code == 404
    backup, destination = tmp_path/'backup.sqlite3', tmp_path/'restored.sqlite3'
    env[0].state.db.backup(backup)
    restore_database(backup, destination)
    restored = Database(destination)
    with restored.connect() as conn:
        assert conn.execute('SELECT count(*) FROM campus_members').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM campus_counselor_scopes').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM campus_publications').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM notices').fetchone()[0] > 0
        assert not conn.execute('PRAGMA foreign_key_check').fetchone()
