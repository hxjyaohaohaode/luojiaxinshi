"""隐私权利（同意记录、注销）、提醒中心、数据看板与通知相关性。"""
from datetime import datetime, timedelta
import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.insights import CST, build_reminders
from app.main import create_app
from app.models import TaskData

ORIGIN = 'http://127.0.0.1:8765'
HEADERS = {'Origin': ORIGIN, 'X-Requested-With': 'campus-notice'}


def client(tmp_path, **overrides):
    app = create_app(Settings(tmp_path, origin=ORIGIN, ai_api_key='', **overrides))
    return app, TestClient(app, base_url=ORIGIN, headers=HEADERS)


def register(c, username='consent.user', accepted=True, **extra):
    r = c.post('/api/auth/register', json={'username': username, 'password': 'Synthetic-Password-2026', 'display_name': '合成用户',
                                           'accepted_terms': accepted, **extra})
    if r.status_code == 200:
        c.headers['X-CSRF-Token'] = c.get('/api/session').json()['csrf']
    return r


def notice_with_task(c, title='合成通知', **task):
    n = c.post('/api/notices', data={'title': title, 'body': title + '。本人按要求提交材料。', 'source_label': '合成来源', 'materials_complete': 'true'}).json()
    n = c.post(f"/api/notices/{n['id']}/manual", json={'version': n['version']}).json()
    data = TaskData(title=task.pop('task_title', '提交材料'), **task).model_dump()
    r = c.post(f"/api/notices/{n['id']}/confirm", json={'version': n['version'], 'reviewed': True, 'tasks': [data]})
    assert r.status_code == 200, r.text
    return n['id'], r.json()['task_ids'][0]


def test_registration_requires_and_records_policy_consent(tmp_path):
    app, c = client(tmp_path)
    assert register(c, accepted=False).status_code == 422
    assert register(c).status_code == 200
    consent = c.get('/api/session').json()['consent']
    assert consent['accepted'] and consent['version'] and consent['accepted_at']
    legal = c.get('/api/legal').json()
    assert legal['model_provider'] == '小米 MiMo' and legal['backup_retention_days'] >= 1


def test_invite_registration_also_requires_consent(tmp_path):
    from app.security import new_invite
    app, c = client(tmp_path)
    invite = new_invite(app.state.db)
    assert register(c, 'invited.user', accepted=False, invite=invite).status_code == 422
    assert register(c, 'invited.user', invite=invite).status_code == 200


def test_existing_account_can_accept_updated_policy(tmp_path):
    app, c = client(tmp_path)
    register(c)
    with app.state.db.connect(write=True) as conn:
        conn.execute('DELETE FROM account_consents')
    assert c.get('/api/session').json()['consent']['accepted'] is False
    assert c.post('/api/account/consent').json()['accepted'] is True
    assert c.get('/api/session').json()['consent']['accepted'] is True


def test_account_deletion_removes_every_personal_record(tmp_path):
    app, c = client(tmp_path)
    register(c, 'leaving.user')
    uid = c.get('/api/session').json()['user']['id']
    notice_with_task(c, '注销前的通知', due_date=(datetime.now(CST) + timedelta(days=2)).date().isoformat())
    conversation = c.post('/api/conversations', json={'title': '注销前的对话'}).json()
    upload = c.post(f"/api/conversations/{conversation['id']}/sources", files={'files': ('note.txt', '只属于这个账号的私人资料'.encode(), 'text/plain')}, data={'version': str(conversation['version'])})
    assert upload.status_code == 200, upload.text
    memory = c.post('/api/memory/items', json={'content': '只属于这个账号的私人记忆片段', 'scope': 'global'})
    assert memory.status_code == 200, memory.text
    with sqlite3.connect(tmp_path / 'campus.sqlite3') as conn:
        assert conn.execute("SELECT COUNT(*) FROM personal_memories WHERE content LIKE '%只属于这个账号%'").fetchone()[0] >= 1
    other_app_client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
    register(other_app_client, 'staying.user')
    notice_with_task(other_app_client, '另一个账号的通知')

    assert c.post('/api/account/delete', json={'password': 'wrong-password', 'confirm': '注销账号'}).status_code == 400
    assert c.post('/api/account/delete', json={'password': 'Synthetic-Password-2026', 'confirm': '删除'}).status_code == 422
    r = c.post('/api/account/delete', json={'password': 'Synthetic-Password-2026', 'confirm': '注销账号'})
    assert r.status_code == 200 and r.json()['ok']
    assert c.get('/api/session').status_code == 401

    with sqlite3.connect(tmp_path / 'campus.sqlite3') as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            if 'user_id' in columns:
                assert conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE user_id=?', (uid,)).fetchone()[0] == 0, table
        # 全文索引与原件中不再有该账号的任何文字。
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            for column in columns:
                try:
                    hits = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE CAST("{column}" AS TEXT) LIKE ?', ('%只属于这个账号%',)).fetchone()[0]
                except sqlite3.OperationalError:
                    continue
                assert hits == 0, (table, column)
        assert conn.execute("SELECT COUNT(*) FROM notices WHERE title='另一个账号的通知'").fetchone()[0] == 1
    assert other_app_client.get('/api/tasks').status_code == 200


def test_reminders_cover_overdue_unconfirmed_and_personal_reminders():
    now = datetime(2026, 10, 23, 9, 0, tzinfo=CST)
    def task(tid, **data):
        base = {'title': tid, 'scope': 'personal', 'deadline_confirmed': True}
        base.update(data)
        return {'id': tid, 'status': 'pending', 'data': base, 'notice_title': '合成通知'}
    tasks = [
        task('过期', due_date='2026-10-22', due_time='17:00'),
        task('今天', due_date='2026-10-23', due_time='18:00'),
        task('未确认', due_date='2026-10-25', deadline_confirmed=False),
        task('远期', due_date='2026-11-20'),
        task('提醒', reminder_at='2026-10-23T15:00:00+08:00'),
        {'id': '他人', 'status': 'pending', 'data': {'title': '他人', 'scope': 'other', 'due_date': '2026-10-23'}},
        {'id': '完成', 'status': 'done', 'data': {'title': '完成', 'scope': 'personal', 'due_date': '2026-10-23'}},
    ]
    arrangements = [{'id': 'a1', 'data': {'title': '每周课程', 'start_date': '2026-10-09', 'end_date': '2026-10-09', 'start_time': '10:00', 'end_time': '11:40',
                                          'repeat': 'weekly', 'repeat_until': '2026-12-31', 'location': '教一'}}]
    result = build_reminders(tasks, [{'id': 'n1', 'status': 'draft'}], arrangements, now)
    by_title = {item['title']: item for item in result['items']}
    assert by_title['过期']['kind'] == 'overdue' and by_title['过期']['level'] == 'urgent'
    assert by_title['今天']['level'] == 'urgent'
    assert by_title['未确认']['confirmed'] is False and '核实' in by_title['未确认']['note']
    assert '远期' not in by_title and '他人' not in by_title and '完成' not in by_title
    assert by_title['提醒']['kind'] == 'reminder'
    assert by_title['每周课程']['kind'] == 'arrangement' and '10:00' in by_title['每周课程']['text']
    assert any(item['kind'] == 'notice' for item in result['items'])
    assert result['counts']['urgent'] == 2
    assert any(entry['title'] == '提醒' for entry in result['upcoming'])
    # 今天 18:00 截止：17:00 的“1 小时后截止”在未来 24 小时内。
    assert any(entry['title'] == '今天' and '1 小时' in entry['text'] for entry in result['upcoming'])


def test_reminder_and_insight_endpoints_are_owner_scoped(tmp_path):
    app, c = client(tmp_path)
    register(c, 'owner.user')
    tomorrow = (datetime.now(CST) + timedelta(days=1)).date().isoformat()
    nid, tid = notice_with_task(c, '明天截止的合成通知', due_date=tomorrow, due_time='23:00', deadline_confirmed=True,
                                deadline_text=tomorrow + ' 23:00 前')
    reminders = c.get('/api/reminders').json()
    assert any(item.get('task_id') == tid for item in reminders['items'])
    task = next(t for t in c.get('/api/tasks').json() if t['id'] == tid)
    assert c.put(f'/api/tasks/{tid}', json={'version': task['version'], 'data': task['data'], 'status': 'done', 'reason': '合成完成'}).status_code == 200
    insights = c.get('/api/insights').json()
    assert insights['tasks']['done'] == 1 and insights['tasks']['on_time'] == 1
    assert sum(week['done'] for week in insights['trend']) == 1
    assert insights['notices']['confirmed'] == 1
    other = TestClient(app, base_url=ORIGIN, headers=HEADERS)
    register(other, 'other.user')
    assert other.get('/api/insights').json()['tasks']['total'] == 0
    assert not any(item.get('task_id') == tid for item in other.get('/api/reminders').json()['items'])
    assert other.get('/api/admin/insights').status_code == 403


def test_admin_insights_are_aggregate_only(tmp_path):
    from app.security import new_invite
    app, c = client(tmp_path)
    invite = new_invite(app.state.db, 'admin')
    register(c, 'site.admin', invite=invite)
    notice_with_task(c, '管理员看不到标题的通知')
    data = c.get('/api/admin/insights').json()
    assert data['users']['total'] == 1 and data['notices']['total'] == 1
    assert '管理员看不到标题的通知' not in str(data) and 'site.admin' not in str(data)


def test_notice_list_exposes_relevance(tmp_path):
    app, c = client(tmp_path)
    register(c)
    nid, _ = notice_with_task(c)
    notice = next(n for n in c.get('/api/notices').json() if n['id'] == nid)
    assert 'applicability' in notice


def test_reminder_read_archive_restore_persist_without_completing_tasks(tmp_path):
    app, c = client(tmp_path)
    register(c)
    tomorrow = (datetime.now(CST) + timedelta(days=1)).date().isoformat()
    _, tid = notice_with_task(c, due_date=tomorrow, due_time='23:00', deadline_confirmed=True)
    before = c.get('/api/tasks').json()
    initial = c.get('/api/reminders').json()
    rid = next(item['id'] for item in initial['items'] if item.get('task_id') == tid)
    assert initial['unread_counts']['total'] == 1
    for status, read, archived in [('read', True, False), ('archived', True, True), ('unread', False, False)]:
        r = c.post('/api/reminders/state', json={'ids': [rid], 'state': status})
        assert r.status_code == 200, r.text
        assert r.json()['updated'] == 1
        # Read a fresh response rather than trusting only the mutation receipt.
        result = c.get('/api/reminders').json()
        item = next(item for item in result['items'] if item['id'] == rid)
        assert item['is_read'] is read and item['is_archived'] is archived
        assert result['unread_counts']['total'] == (0 if read else 1)
    assert c.get('/api/tasks').json() == before
    assert c.post('/api/reminders/state', json={'ids': [rid], 'state': 'read'}, headers={'X-CSRF-Token': ''}).status_code == 403


def test_bulk_read_is_owner_scoped_and_marks_only_submitted_snapshot(tmp_path):
    app, c = client(tmp_path)
    register(c)
    tomorrow = (datetime.now(CST) + timedelta(days=1)).date().isoformat()
    notice_with_task(c, '旧提醒', due_date=tomorrow)
    old = c.get('/api/reminders').json()['items'][0]['id']
    other = TestClient(app, base_url=ORIGIN, headers=HEADERS)
    register(other, 'another.reader')
    notice_with_task(other, '其他人的提醒', due_date=tomorrow)
    foreign = other.get('/api/reminders').json()['items'][0]['id']
    notice_with_task(c, '刚收到的新提醒', due_date=tomorrow)
    r = c.post('/api/reminders/state', json={'ids': [old, old, foreign, 'stale'], 'state': 'read'})
    assert r.status_code == 200 and r.json()['updated'] == 1
    assert r.json()['unread_counts']['total'] == 1
    assert other.get('/api/reminders').json()['unread_counts']['total'] == 1
    assert c.post('/api/reminders/state', json={'ids': [], 'state': 'read'}).status_code == 422
    assert c.post('/api/reminders/state', json={'ids': [old], 'state': 'done'}).status_code == 422


def test_changed_deadline_reappears_as_unread(tmp_path):
    _, c = client(tmp_path)
    register(c)
    tomorrow = (datetime.now(CST) + timedelta(days=1)).date().isoformat()
    _, tid = notice_with_task(c, due_date=tomorrow)
    old = c.get('/api/reminders').json()['items'][0]['id']
    c.post('/api/reminders/state', json={'ids': [old], 'state': 'archived'})
    task = next(t for t in c.get('/api/tasks').json() if t['id'] == tid)
    task['data']['due_time'] = '22:00'
    r = c.put(f'/api/tasks/{tid}', json={'version': task['version'], 'data': task['data'], 'status': 'pending', 'reason': '调整期限'})
    assert r.status_code == 200, r.text
    new = next(item for item in c.get('/api/reminders').json()['items'] if item['kind'] == 'due')
    assert new['id'] != old and not new['is_read'] and not new['is_archived']


def test_reminder_identity_tracks_urgency_and_new_sources_not_relative_wording():
    now = datetime(2026, 10, 23, 9, tzinfo=CST)
    task = {'id': 't', 'status': 'pending', 'data': {'title': '交材料', 'scope': 'personal', 'due_date': '2026-10-25'}}
    one = build_reminders([task], [], [], now)['items'][0]
    two = build_reminders([task], [], [], now + timedelta(days=1))['items'][0]
    assert one['text'] != two['text'] and one['id'] == two['id']
    urgent = build_reminders([task], [], [], now + timedelta(days=2))['items'][0]
    assert urgent['id'] != one['id']
    notices = [{'id': 'n1', 'status': 'received', 'version': 1}, {'id': 'n2', 'status': 'draft', 'version': 1}]
    before = build_reminders([], notices, [], now)['items'][0]['id']
    assert before == build_reminders([], list(reversed(notices)), [], now)['items'][0]['id']
    notices[0]['version'] = 2
    assert before != build_reminders([], notices, [], now)['items'][0]['id']


def test_all_reminders_are_available_for_bulk_read_not_only_first_sixty():
    now = datetime(2026, 10, 23, 9, tzinfo=CST)
    tasks = [{'id': str(i), 'status': 'pending', 'data': {'title': f'事项{i}', 'scope': 'personal', 'due_date': '2026-10-24'}} for i in range(75)]
    result = build_reminders(tasks, [], [], now)
    assert len(result['items']) == result['counts']['total'] == 75
    assert len({item['id'] for item in result['items']}) == 75
