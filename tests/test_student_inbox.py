"""Student inbox exposes owner-scoped aggregation, dates and source warnings."""
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
