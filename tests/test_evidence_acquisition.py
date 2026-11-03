"""Real intake transitions, owner isolation and evidence/Agent parity."""
import asyncio
import copy
import json

import httpx
from fastapi import HTTPException

from app import notice_intake
from app.documents import text_source
from app.notice_ingest import ingest_notice
from app.notice_network import provenance, retain_unavailable
from app.source_coverage import coverage
from tests.test_workflow import account, env

URL = 'https://school.example.edu.cn/info/1.htm'
PDF = 'https://school.example.edu.cn/apply.pdf'


def root(at=100):
    source = text_source('报名原文，请核对已公布的申请表。', '申请通知')
    source['origin'] = {'url': URL, 'retrieved_at': at, 'attachments': [PDF],
                        'received_attachments': [], 'warnings': ['申请表上次未读到']}
    return source


def receive(conn, uid, materials, at, key='website:source:article'):
    return ingest_notice(conn, uid, sources=materials, source_url=URL, external_key=key, observed_at=at)


def test_successful_retry_refreshes_live_evidence_and_revision_without_reanalysis(env):
    c = account(env); uid = c.get('/api/session').json()['user']['id']; db = env[0].state.db
    initial = root()
    leaf = text_source('实际申请表内容', '申请表'); leaf.update(kind='pdf', content=b'%PDF-fixture')
    leaf['origin'] = {'url':PDF, 'retrieved_at':100, 'parent_url':URL, 'relationship':'attachment'}
    with db.connect(write=True) as conn:
        result = receive(conn, uid, [initial, leaf], 100)
        # The attachment already exists as identical evidence from a previous
        # successful read; only the root's acquisition record is stale.
        initial['origin'].update(received_attachments=[PDF], warnings=[])
        refreshed = copy.deepcopy(initial); refreshed['origin']['retrieved_at'] = 200
    old = c.get('/api/proactive/revision').json()['revision']
    with db.connect(write=True) as conn:
        result2 = receive(conn, uid, [refreshed, leaf], 200)
        assert result2['provenance_updated'] and not result2['updated']
        assert conn.execute('SELECT version FROM notices WHERE id=?', (result['notice_id'],)).fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM notice_ingest_updates').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM notice_ingest_receipts').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM notice_automation_jobs').fetchone()[0] == 0
    assert c.get('/api/proactive/revision').json()['revision'] != old
    detail = c.get('/api/proactive/notices/' + result['notice_id']).json()
    document = next(d for d in detail['evidence_chain']['documents'] if d['origin']['url'] == URL)
    assert not document['missing_attachments'] and document['coverage']['state'] == 'complete'
    assert document['origin']['retrieved_at'] == 200 and document['origin']['first_retrieved_at'] == 100
    assert provenance([{'id': document['id'], 'status': 'ok', 'origin': document['origin']}])[0]['coverage'] == document['coverage']


def test_old_observation_and_forwarding_copy_cannot_overwrite_fresh_origin(env):
    c = account(env); other = account(env, 'other'); uid = c.get('/api/session').json()['user']['id']
    foreign_uid = other.get('/api/session').json()['user']['id']; db = env[0].state.db
    fresh = root(200); fresh['origin'].update(received_attachments=[PDF], warnings=[])
    with db.connect(write=True) as conn:
        n = receive(conn, uid, [fresh], 200)
        assert receive(conn, uid, [root(100)], 100)['stale']
        forwarded = root(300); forwarded['origin']['url'] = 'https://group.example.org/copied'
        assert not receive(conn, uid, [forwarded], 300)['provenance_updated']
        foreign = receive(conn, foreign_uid, [root(400)], 400)
        assert foreign['notice_id'] != n['notice_id']
    document = c.get('/api/proactive/notices/' + n['notice_id']).json()['evidence_chain']['documents'][0]
    assert document['origin']['url'] == URL and not document['missing_attachments']


def test_retained_attachment_is_not_claimed_as_a_new_success(env):
    c = account(env); uid = c.get('/api/session').json()['user']['id']; db = env[0].state.db
    first = root(); first['origin'].update(received_attachments=[PDF], warnings=[])
    leaf = text_source('申请表须本人签字。', '申请表'); leaf.update(kind='pdf', content=b'%PDF-synthetic')
    leaf['origin'] = {'url': PDF, 'retrieved_at': 100, 'parent_url': URL, 'relationship': 'attachment'}
    with db.connect(write=True) as conn:
        n = receive(conn, uid, [first, leaf], 100)
        materials = retain_unavailable(conn, uid, 'website:source:article', [root(200)])
        assert receive(conn, uid, materials, 200)['provenance_updated']
    documents = c.get('/api/proactive/notices/' + n['notice_id']).json()['evidence_chain']['documents']
    primary = next(d for d in documents if d['origin']['url'] == URL)
    retained = next(d for d in documents if d['origin']['url'] == PDF)
    assert primary['coverage']['reading_incomplete'] and primary['coverage']['retained_snapshots']
    assert retained['origin']['retrieved_at'] == 100


def test_two_collectors_cannot_drop_real_restoration_or_leave_superseded_facts_active(env):
    c = account(env); uid = c.get('/api/session').json()['user']['id']; db = env[0].state.db
    with db.connect(write=True) as conn:
        first = receive(conn, uid, [root(100)], 100, key='website:first')
        assert receive(conn, uid, [root(110)], 110, key='website:second')['notice_id'] == first['notice_id']
        new = root(200); new.update(text_source('更正：改用新的申请表。', '更正通知'))
        assert receive(conn, uid, [new], 200, key='website:second')['updated']
        assert receive(conn, uid, [root(150)], 150, key='website:first')['stale']
        # The publisher really restored the first content. It equals this key's
        # old receipt, but differs from the current notice and is a new version.
        assert receive(conn, uid, [root(300)], 300, key='website:first')['updated']
        active = conn.execute('SELECT sha256 FROM sources WHERE notice_id=? AND active=1', (first['notice_id'],)).fetchall()
        assert [r[0] for r in active] == [root()['sha256']]
        assert conn.execute('SELECT version FROM notices WHERE id=?', (first['notice_id'],)).fetchone()[0] == 3
        updates=conn.execute('SELECT previous_source_ids,new_source_ids FROM notice_ingest_updates WHERE notice_id=? ORDER BY rowid',(first['notice_id'],)).fetchall()
        assert json.loads(updates[1]['previous_source_ids']) == json.loads(updates[0]['new_source_ids'])


def test_failed_refresh_keeps_newer_attachment_obtained_by_another_collector(env):
    c = account(env); uid = c.get('/api/session').json()['user']['id']; db = env[0].state.db
    complete = root(); complete['origin'].update(received_attachments=[PDF], warnings=[])
    old = text_source('旧版申请表', '申请表'); old.update(kind='pdf', content=b'%PDF-old')
    old['origin'] = {'url':PDF, 'retrieved_at':100, 'parent_url':URL, 'relationship':'attachment'}
    latest = text_source('新版申请表，已更正要求', '申请表'); latest.update(kind='pdf', content=b'%PDF-new')
    latest['origin'] = {**old['origin'], 'retrieved_at':200}
    with db.connect(write=True) as conn:
        n = receive(conn, uid, [complete, old], 100, key='website:first')
        receive(conn, uid, [complete, old], 110, key='website:second')
        receive(conn, uid, [complete, latest], 200, key='website:second')
        materials = retain_unavailable(conn, uid, 'website:first', [root(300)])
        assert {s['sha256'] for s in materials} == {complete['sha256'], latest['sha256']}
        result = receive(conn, uid, materials, 300, key='website:first')
        assert result['notice_id'] == n['notice_id'] and not result['updated']
        assert conn.execute('SELECT version FROM notices WHERE id=?', (n['notice_id'],)).fetchone()[0] == 2
        # Collector history is caught up, while notice facts remain current.
        assert conn.execute('SELECT count(*) FROM sources WHERE notice_id=? AND active=1', (n['notice_id'],)).fetchone()[0] == 2
        assert not conn.execute('SELECT active FROM sources WHERE notice_id=? AND sha256=?', (n['notice_id'],old['sha256'])).fetchone()[0]


def test_attachment_ledger_covers_every_link_and_accepts_fifth_real_file():
    source = root(); urls = [f'https://school.example.edu.cn/{i}.pdf' for i in range(6)]
    source['origin']['attachments'] = urls + ['https://school.example.edu.cn/old.ppt', 'https://other.example.org/a.pdf']
    calls = []
    async def read(url):
        calls.append(url); value = text_source('附表要求' + url, '申请表')
        value.update(kind='pdf', content=b'fixture'); value['origin'] = {'url': url}
        return value, '申请表'
    materials = asyncio.run(notice_intake.read_notice_materials(source, read=read))
    readings = materials[0]['origin']['attachment_reads']
    assert calls == urls[:5] and len(materials) == 6
    assert [r['state'] for r in readings] == ['received'] * 5 + ['budget', 'unsupported', 'out_of_scope']
    assert len(coverage(materials[0])['unread_attachments']) == 3


def test_cms_handler_uses_trimmed_attachment_label_for_format_detection():
    source = root(); url='https://school.example.edu.cn/system/download.jsp?id=1'
    source['origin'].update(attachments=[url],attachment_names={url:'附件：推荐名单.xlsx \u00a0\n'})
    async def read(requested):
        assert requested==url
        value=text_source('原始表格内容', '推荐名单.xlsx');value.update(kind='xlsx',content=b'fixture')
        value['origin']={'url':url};return value,value['name']
    materials=asyncio.run(notice_intake.read_notice_materials(source,read=read))
    assert len(materials)==2 and materials[0]['origin']['attachment_reads'][0]['state']=='received'


def test_scan_review_is_not_a_missing_download_and_failure_is_recorded():
    source = root(); source['origin']['attachments'].append('https://school.example.edu.cn/broken.pdf')
    async def read(url):
        if url.endswith('broken.pdf'): raise HTTPException(503, '来源正在维护')
        value = text_source('', '扫描申请表'); value.update(kind='pdf', content=b'fixture', status='review', warning='需逐页图像核对')
        value['origin'] = {'url': url}; return value, value['name']
    materials = asyncio.run(notice_intake.read_notice_materials(source, read=read))
    assert coverage(materials[1])['review_required'] and not coverage(materials[1])['reading_incomplete']
    missing = coverage(materials[0])['unread_attachments']
    assert len(missing) == 1 and missing[0]['reason'] == '来源正在维护'
    assert materials[0]['origin']['attachment_reads'][0]['state'] == 'review'


def test_timeout_marks_all_unfinished_attachments_without_discarding_completed(monkeypatch):
    source = root(); source['origin']['attachments'] += ['https://school.example.edu.cn/slow.pdf', 'https://school.example.edu.cn/next.pdf']
    async def read(url):
        if url.endswith('slow.pdf'): await asyncio.sleep(10)
        value = text_source('已读要求', '申请表'); value.update(kind='pdf', content=b'fixture')
        value['origin'] = {'url': url}; return value, value['name']
    monkeypatch.setattr(notice_intake, 'ATTACHMENT_READ_SECONDS', .02)
    materials = asyncio.run(notice_intake.read_notice_materials(source, read=read))
    assert len(materials) == 2
    assert [r['state'] for r in materials[0]['origin']['attachment_reads']] == ['received', 'timeout', 'timeout']


def test_downloaded_invalid_legacy_document_keeps_original_and_explicit_parse_failure(monkeypatch):
    monkeypatch.setattr(notice_intake, 'PublicHTTPTransport', lambda: httpx.MockTransport(
        lambda request: httpx.Response(200, headers={'content-type': 'application/msword'}, content=b'legacy-doc')))
    source,_=asyncio.run(notice_intake.read_link('https://school.example.edu.cn/form.doc'))
    assert source['kind']=='doc' and source['content']==b'legacy-doc'
    assert source['status']=='failed' and not source['sections']
    assert '类型与内容不符' in source['warning'] and '链接读取失败' not in source['warning']


def test_declared_oversized_attachment_is_rejected_before_consuming_body(monkeypatch):
    consumed=[]
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            consumed.append(True)
            yield b'body-must-not-be-read'
    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={
        'content-type':'application/pdf','content-length':'83275858'},stream=Body()))
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:transport)
    import pytest
    with pytest.raises(HTTPException)as error:
        asyncio.run(notice_intake.read_link(PDF))
    assert error.value.status_code==413 and not consumed


def test_unknown_or_understated_length_still_enforces_real_decoded_stream_limit(monkeypatch):
    import pytest
    monkeypatch.setattr(notice_intake,'MAX_FILE',8)
    for declared in ('','1','invalid','-1'):
        headers={'content-type':'application/pdf'}
        if declared:headers['content-length']=declared
        transport=httpx.MockTransport(lambda request:httpx.Response(200,headers=headers,content=b'x'*9))
        monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:transport)
        with pytest.raises(HTTPException)as error:
            asyncio.run(notice_intake.read_link(PDF))
        assert error.value.status_code==413
