"""Preset subscriptions reuse existing owner, version, and intake boundaries."""
from app import source_sync
from app.documents import text_source
from tests.test_workflow import account, env


def subscribe(client, preset='whu-notices'):
    response = client.post('/api/source-presets/' + preset + '/subscribe', json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_preset_subscription_is_atomic_idempotent_and_owner_scoped(env):
    a, b = account(env), account(env, 'bob')
    presets = a.get('/api/source-presets').json()
    assert {p['id'] for p in presets} == {'whu-notices', 'whu-sres-notices', 'whu-journal-affairs'}
    assert [p['id'] for p in presets[:2]] == ['whu-sres-notices', 'whu-notices']
    first, again, other = subscribe(a), subscribe(a), subscribe(b)
    assert first['created'] and not again['created']
    assert first['source_id'] == again['source_id'] != other['source_id']
    assert len(a.get('/api/source-catalog').json()) == 1
    assert first['subscription']['config']['preset_id'] == 'whu-notices'
    assert a.get('/api/notice-automation').json()['enabled'] is False
    assert a.get('/api/notices').json() == []
    assert a.post('/api/source-presets/unknown/subscribe', json={}).status_code == 404


def test_preset_reuses_manual_source_and_keeps_paused_subscription(env):
    client = account(env)
    preset = client.get('/api/source-presets').json()[0]
    sid = client.post('/api/source-catalog', json={
        'name': '我原来的校级来源', 'platform': 'website', 'url': preset['url']
    }).json()['id']
    saved = subscribe(client, preset['id'])
    assert saved['source_id'] == sid and not saved['created']
    subscription = saved['subscription']
    paused = client.put('/api/source-catalog/' + sid + '/subscription', json={
        **subscription['config'], 'version': subscription['version'], 'enabled': False,
    })
    assert paused.status_code == 200, paused.text
    repeated = subscribe(client, preset['id'])
    assert repeated['subscription']['state'] == 'paused'
    assert client.get('/api/source-catalog').json()[0]['data']['name'] == '我原来的校级来源'


def test_preset_configuration_cannot_expand_to_another_column(env):
    client = account(env)
    saved = subscribe(client)
    subscription = saved['subscription']
    for changes in ({'url': 'https://www.whu.edu.cn/other.htm'},
                    {'article_path_prefix': '/info/'}, {'preset_id': 'unknown'}, {'mode': 'feed'}):
        response = client.put('/api/source-catalog/' + saved['source_id'] + '/subscription', json={
            **subscription['config'], 'version': subscription['version'], **changes,
        })
        assert response.status_code == 422, response.text


def test_preset_sync_keeps_date_materials_and_duplicate_identity(env, monkeypatch):
    client = account(env)
    saved = subscribe(client)
    async def index(config):
        return [{'title': '公开通知', 'url': 'https://www.whu.edu.cn/info/5231/123.htm',
                 'published_at': '2026-10-28'}]
    async def read(url):
        source = text_source('通知原文：请核对条件。')
        source['origin'] = {'url': url, 'published_at': '2026-10-29', 'attachments': [], 'warnings': []}
        return source, '公开通知'
    async def materials(source, read=None):
        assert read is not None
        return [source, text_source('附件说明：材料清单。', '附件说明')]
    monkeypatch.setattr(source_sync, 'fetch_index', index)
    monkeypatch.setattr(source_sync, 'read_link', read)
    monkeypatch.setattr('app.notice_network.read_notice_materials', materials)
    endpoint = '/api/source-catalog/' + saved['source_id'] + '/refresh'
    assert client.post(endpoint).json()['received_count'] == 1
    assert client.post(endpoint).json()['received_count'] == 1
    notices = client.get('/api/notices').json()
    assert len(notices) == 1
    detail = client.get('/api/notices/' + notices[0]['id']).json()
    assert detail['published_at'] == '2026-10-29'
    assert detail['sources'][0]['origin']['listed_published_at'] == '2026-10-28'
    assert any('列表日期' in w for w in detail['sources'][0]['origin']['warnings'])
    assert len(detail['sources']) == 2
    assert not detail['materials_complete']
    assert client.get('/api/tasks').json() == []
