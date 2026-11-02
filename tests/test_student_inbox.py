"""Student inbox exposes owner-scoped aggregation, dates and source warnings."""
import json
import shutil
import subprocess

import pytest

from app.notice_ingest import search_notices
from tests.test_workflow import account, env


def test_merged_origins_are_browsable_and_private(env):
    one = account(env, 'student-one')
    two = account(env, 'student-two')
    body = '2026年测试活动\n请同学对照原文核实报名条件。'
    first = one.post('/api/notices', data={'body': body, 'source_label': '资环院官网',
        'published_at': '2026-10-20T08:00:00+08:00', 'materials_complete': 'true'})
    assert first.status_code == 200
    second = one.post('/api/notices', data={'body': '转发学院通知：' + body, 'source_label': '班级群'})
    assert second.status_code == 200 and second.json()['id'] == first.json()['id']
    nid = first.json()['id']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE sources SET status='review',warning='测试材料需核对' WHERE notice_id=? AND active=1", (nid,))
    items = one.get('/api/notices').json()
    assert len(items) == 1
    item = items[0]
    assert item['origin_labels'] == ['资环院官网', '班级群']
    assert item['published_at'].startswith('2026-10-20')
    assert '核实报名条件' in item['source_excerpt'] and item['source_review_count'] >= 1
    assert [n['id'] for n in one.get('/api/notices/search', params={'q': '班级群'}).json()] == [nid]
    assert two.get('/api/notices').json() == []
    assert two.get('/api/notices/search', params={'q': '班级群'}).json() == []
    assert two.get('/api/notices/' + nid).status_code == 404


def test_legacy_notice_without_receipts_has_safe_fallback(env):
    student = account(env)
    uid = student.get('/api/session').json()['user']['id']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('''INSERT INTO notices(id,user_id,title,source_label,source_url,published_at,
            materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            ('legacy-personal', uid, '旧通知', '', '', None, 0, 'legacy-fixture', 1, 1))
    item = student.get('/api/notices').json()[0]
    assert item['origin_labels'] == ['个人提交']
    assert item['published_at'] is None and item['source_excerpt'] is None and item['source_review_count'] == 0
    # Older records may acquire a new source after they were created, while the
    # original receipt is missing. Both the original and later origin matter.
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('''INSERT INTO notice_ingest_receipts(id,user_id,notice_id,external_key,
            fingerprint,source_label,source_url,source_ids,created_at,observed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            ('legacy-receipt', uid, 'legacy-personal', '', '', '班级群', '', '[]', 2, 2))
    assert student.get('/api/notices').json()[0]['origin_labels'] == ['个人提交', '班级群']
    assert student.get('/api/notices/search', params={'q': '班级群'}).json()[0]['id'] == 'legacy-personal'


def test_notice_list_query_runs_with_node_sqlite(env):
    """Exercise the actual list query on Node's independently bundled SQLite."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is not installed')
    one, two = account(env, 'sqlite-one'), account(env, 'sqlite-two')
    response = one.post('/api/notices', data={'title': '示例通知', 'body': '示例通知\n这里是正文'})
    assert response.status_code == 200
    assert two.post('/api/notices', data={'title': '别人的通知', 'body': '另一账号的正文'}).status_code == 200
    uid = one.get('/api/session').json()['user']['id']
    db = env[0].state.db
    statements = []
    with db.connect() as conn:
        conn.set_trace_callback(statements.append)
        assert len(search_notices(conn, uid)) == 1
        conn.set_trace_callback(None)
    sql = next(statement for statement in statements if statement.lstrip().startswith('SELECT n.id,n.title'))
    script = r'''
const fs = require('node:fs');
let DatabaseSync;
try { ({DatabaseSync} = require('node:sqlite')); }
catch (error) { console.error('NODE_SQLITE_UNAVAILABLE'); process.exit(77); }
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const db = new DatabaseSync(input.path, {readOnly: true});
console.log(JSON.stringify({version:process.versions.sqlite, rows:db.prepare(input.sql).all()}));
db.close();
'''
    run = subprocess.run([node, '-e', script], input=json.dumps({'path': str(db.path), 'sql': sql}),
                         text=True, encoding='utf-8', capture_output=True, timeout=30)
    if run.returncode == 77 and 'NODE_SQLITE_UNAVAILABLE' in run.stderr:
        pytest.skip('Node does not provide a built-in SQLite library')
    assert run.returncode == 0, run.stderr
    rows = json.loads(run.stdout)['rows']
    assert len(rows) == 1 and rows[0]['title'] == '示例通知'
    assert rows[0]['source_excerpt'] == '这里是正文'
