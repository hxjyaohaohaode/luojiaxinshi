import json

import httpx
import pytest

from app import notice_intake
from tests.test_workflow import account, confirm, env, manual, notice


def mock_web(monkeypatch, handler):
    monkeypatch.setattr(notice_intake, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))


def test_link_preview_is_owner_scoped_exact_snapshot_and_keeps_provenance(env, monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text='<title>学术讲座</title><p>2027年10月20日到会场参加讲座。</p><img src="p.png"><a href="/apply.pdf">附件</a><script>secret()</script>')
    mock_web(monkeypatch, handler)
    c, other = account(env), account(env, 'other')
    r = c.post('/api/intake/link', json={'url': 'https://school.example.edu.cn/news/1'})
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview['source']['origin']['attachments'] == ['https://school.example.edu.cn/apply.pdf']
    assert 'secret()' not in json.dumps(preview)
    values = {'title': '学术讲座', 'link_preview': preview['id'], 'materials_complete': 'false', 'request_id': 'synthetic-intake-0001'}
    assert other.post('/api/notices', data=values).status_code == 409
    saved = c.post('/api/notices', data=values)
    assert saved.status_code == 200, saved.text
    n = saved.json()
    assert n['sources'][0]['origin']['url'].endswith('/news/1')
    assert n['sources'][0]['sections'] == preview['source']['sections']
    assert len(calls) == 1
    again = c.post('/api/notices', data=values)
    assert again.status_code == 200 and again.json()['id'] == n['id']
    assert c.post('/api/notices', data={**values, 'title': '不同内容'}).status_code == 409
    assert len(c.get('/api/notices').json()) == 1


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'http://10.0.0.1/a', 'file:///tmp/a', 'https://user:pass@example.com/a', 'https://example.com:8765/a'])
def test_link_rejects_nonpublic_urls_without_fetch(env, monkeypatch, url):
    mock_web(monkeypatch, lambda request: pytest.fail('unsafe URL was fetched'))
    assert account(env).post('/api/intake/link', json={'url': url}).status_code == 422


def test_link_redirect_rechecks_destination_and_failure_keeps_existing_materials(env, monkeypatch):
    c = account(env)
    n = notice(c)
    mock_web(monkeypatch, lambda request: httpx.Response(302, headers={'location': 'http://127.0.0.1/private'}))
    assert c.post('/api/intake/link', json={'url': 'https://school.example.edu.cn/a'}).status_code == 422
    assert c.get('/api/notices/' + n['id']).json()['sources'] == n['sources']


def test_link_expiry_and_oversized_text_are_explicit(env, monkeypatch):
    c = account(env)
    mock_web(monkeypatch, lambda request: httpx.Response(200, headers={'content-type': 'text/plain'}, text='校园公告'))
    p = c.post('/api/intake/link', json={'url': 'https://school.example.edu.cn/a'}).json()
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE notice_link_previews SET expires_at=0')
    assert c.post('/api/notices', data={'title': '公告', 'link_preview': p['id']}).status_code == 409
    mock_web(monkeypatch, lambda request: httpx.Response(200, headers={'content-type': 'text/plain'}, text='字' * 10001))
    assert c.post('/api/intake/link', json={'url': 'https://school.example.edu.cn/long'}).status_code == 422
    assert c.get('/api/notices').json() == []


def test_disposition_closes_information_without_fake_task_and_supplement_reopens(env):
    c = account(env)
    n = notice(c, '图书馆开放时间说明，无需办理。')
    r = c.put('/api/notices/' + n['id'] + '/disposition', json={'version': n['version'], 'disposition': 'reference', 'note': '已阅读，留作参考'})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved['handling']['disposition'] == 'reference' and saved['tasks'] == []
    assert c.get('/api/notices').json()[0]['disposition'] == 'reference'
    assert not any(item['kind'] == 'notice' for item in c.get('/api/reminders').json()['items'])
    assert c.put('/api/notices/' + n['id'] + '/disposition', json={'version': n['version'], 'disposition': 'closed'}).status_code == 409
    update = c.post('/api/notices/' + n['id'] + '/supplement', data={'version': saved['version'], 'body': '补充：周末时间有所调整。'})
    assert update.status_code == 200, update.text
    assert update.json()['handling']['disposition'] == 'inbox'


def test_disposition_cannot_hide_unfinished_actions_or_cross_accounts(env):
    c, other = account(env), account(env, 'other')
    n = manual(c, notice(c))
    confirm(c, n)
    n = c.get('/api/notices/' + n['id']).json()
    payload = {'version': n['version'], 'disposition': 'closed'}
    assert c.put('/api/notices/' + n['id'] + '/disposition', json=payload).status_code == 422
    assert other.put('/api/notices/' + n['id'] + '/disposition', json=payload).status_code == 404


def test_deleted_submission_cannot_be_recreated_by_retry(env):
    c = account(env)
    values = {'title': '独立公告', 'body': '保存后删除的公告正文', 'request_id': 'synthetic-intake-deleted'}
    n = c.post('/api/notices', data=values).json()
    assert c.request('DELETE', '/api/notices/' + n['id'], json={'version': n['version']}).status_code == 200
    assert c.post('/api/notices', data=values).status_code == 409
    assert c.get('/api/notices').json() == []
