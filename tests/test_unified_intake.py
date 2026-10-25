import json

from app.documents import text_source
from app.notice_ingest import ingest_notice
from app.insights import build_reminders
from tests.test_workflow import account, confirm, env, manual, notice


def test_no_title_and_cross_channel_forward_reuse_preserve_plan(env):
    c = account(env)
    body = '2027年奖学金申请通知\n请本科生在10月30日前交申请表。'
    n = c.post('/api/notices', data={'body': body, 'source_label': '官网', 'materials_complete': 'true'}).json()
    assert n['title'] == '2027年奖学金申请通知'
    drafted = manual(c, n)
    tid = confirm(c, drafted)
    original = c.get('/api/notices/' + n['id']).json()
    r = c.post('/api/notices', data={'body': '转发学院通知：' + body, 'source_label': '班级群'})
    assert r.status_code == 200, r.text
    merged = r.json()
    assert merged['id'] == n['id'] and merged['reused']
    assert merged['status'] == 'confirmed' and merged['version'] == original['version']
    assert [t['id'] for t in merged['tasks']] == [tid]
    assert {r['source_label'] for r in merged['receipts']} == {'官网', '班级群'}


def test_same_text_conversation_promotion_reuses_manual_notice(env):
    c = account(env)
    body = '2027年图书馆开放安排：周六8:00开馆。'
    n = notice(c, body)
    chat = c.post('/api/conversations', json={}).json()
    upload = c.post('/api/conversations/' + chat['id'] + '/sources', data={'version': chat['version'], 'body': body})
    assert upload.status_code == 200, upload.text
    conversation = upload.json()
    r = c.post('/api/conversations/' + chat['id'] + '/promote', json={'version': conversation['version'], 'source_ids': [conversation['sources'][0]['id']]})
    assert r.status_code == 200, r.text
    assert r.json()['notice_id'] == n['id'] and r.json()['already_created']
    assert len(c.get('/api/notices').json()) == 1


def test_new_round_and_explicit_distinct_copy_not_silently_merged(env):
    c = account(env)
    first = notice(c, '2027年第一批奖学金申请，10月30日截止。')
    second = notice(c, '2027年第二批奖学金申请，11月30日截止。')
    assert first['id'] != second['id']
    distinct = c.post('/api/notices', data={'body': '2027年第一批奖学金申请，10月30日截止。', 'allow_duplicate': 'true'})
    assert distinct.status_code == 200 and distinct.json()['id'] != first['id']


def test_identical_template_does_not_merge_conflicting_years_or_batches(env):
    c=account(env);body='请按通知要求提交申请材料。'
    values=[]
    for title,at in [('2026年第一批申请','2026-10-20T08:00:00+08:00'),('2027年第一批申请','2027-10-20T08:00:00+08:00'),('2027年第二批申请','2027-10-20T08:00:00+08:00')]:
        r=c.post('/api/notices',data={'body':body,'title':title,'published_at':at})
        assert r.status_code==200,r.text
        values.append(r.json()['id'])
    assert len(set(values))==3
    repeated=c.post('/api/notices',data={'body':body,'title':'2027年第二批申请','published_at':'2027-10-21T08:00:00+08:00'})
    assert repeated.json()['id']==values[2]


def test_search_body_attachment_and_other_users_are_isolated(env):
    c, other = account(env), account(env, 'another')
    n = notice(c, '请携带蓝色证件到文理学部办理。', files=[('files', ('requirements.txt', '必须由班主任签章'.encode(), 'text/plain'))])
    foreign = notice(other, '绝密申请材料：不可返回给其他人。')
    for query in ('蓝色证件', '班主任签章', '文理学部 办理'):
        result = c.get('/api/notices/search', params={'q': query})
        assert result.status_code == 200, result.text
        assert [r['id'] for r in result.json()] == [n['id']]
        assert result.json()[0]['search_snippet']
    assert c.get('/api/notices/search', params={'q': '绝密'}).json() == []


def test_source_versions_can_restore_content_but_old_events_cannot_roll_back(env):
    c = account(env)
    uid = c.get('/api/session').json()['user']['id']
    db = env[0].state.db
    def receive(text, observed):
        with db.connect(write=True) as conn:
            return ingest_notice(conn, uid, sources=[text_source(text)], external_key='website:source:article', observed_at=observed)
    first = receive('10月30日提交申请。', 100)
    change = receive('延期至11月3日提交。', 200)
    assert change['notice_id'] == first['notice_id'] and change['updated']
    replay = receive('10月30日提交申请。', 150)
    assert replay['stale']
    restore = receive('10月30日提交申请。', 300)
    assert restore['updated'] and restore['notice_id'] == first['notice_id']
    detail = c.get('/api/notices/' + first['notice_id']).json()
    assert len(detail['intake_updates']) == 2
    assert len([s for s in detail['sources'] if s['active']]) == 1


def test_same_public_text_keeps_each_account_private(env):
    c, other = account(env), account(env, 'another')
    a = notice(c, '本周六闭馆。')
    b = notice(other, '本周六闭馆。')
    assert a['id'] != b['id']
    assert c.get('/api/notices/' + b['id']).status_code == 404


def test_completed_action_still_receives_correction_reminder():
    result = build_reminders([{'id': 't1', 'status': 'done', 'data': {'scope': 'personal', 'title': '已交申请表'},
                              'pending_changes': [{'change_id': 'c1', 'kind': 'materials'}]}], [], [])
    assert [i['kind'] for i in result['items']] == ['change']


def test_receipt_replay_does_not_duplicate_provenance(env):
    c = account(env)
    payload = {'body': '新生入学确认。', 'request_id': 'a' * 20}
    a = c.post('/api/notices', data=payload)
    b = c.post('/api/notices', data=payload)
    assert a.status_code == b.status_code == 200
    assert a.json()['id'] == b.json()['id'] and len(b.json()['receipts']) == 1
