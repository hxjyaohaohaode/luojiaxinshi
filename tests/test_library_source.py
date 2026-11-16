"""Exercise the public dynamic list, including out-of-scope redirects."""
import asyncio
import json

import httpx

from app import source_sync
from app.official_sources import get_preset


def test_dynamic_library_list_follows_only_valid_same_column_public_items(monkeypatch):
    preset = get_preset('whu-library-notices')
    requests = []
    index = 'var engineInstanceId = 5619257; var sign = "0123456789abcdef0123456789abcdef"; var appId = 4627353;'
    def row(id, **changes):
        return {'id': id, 'typeId': '11166542', 'pageType': 1, 'isOuter': False,
                'publicUse': True, 'isPublish': 1, '1': {'value': f'公告{id}'},
                '6': {'value': '2026-06-08 16:30:44'},
                'url': f'/engine2/general-rest/{id}/proxy-detail-url?pageType=1&typeId=11166542&dataTypeId=11166542&pageId=1&engineInstanceId=5619257&sign=public', **changes}
    external = 'https://mp.weixin.qq.com/s/public-notice'
    rows = [row(1), row(2, isOuter=True, pageType=3,
                         url='/engine2/general-rest/outer-proxy-detail-url?url='+external),
            row(3), row(4, url='https://external.example/steal')]
    def handler(request):
        requests.append(str(request.url))
        assert 'cookie' not in request.headers
        if request.url.path.endswith('/more'):
            return httpx.Response(200, text=index, headers={'set-cookie': 'private=not-forwarded'})
        if request.url.path.endswith('/more-datas'):
            assert request.url.params['typeId'] == '11166542'
            return httpx.Response(200, json={'code': 1, 'data': {'datas': {'datas': rows}}})
        if '/1/proxy-detail-url' in request.url.path:
            return httpx.Response(200, text='window.location.href = "\\/engine2\\/d\\/1\\/5619257\\/0?t=11166542\\u0026p=1";')
        if '/3/proxy-detail-url' in request.url.path:
            return httpx.Response(200, text='window.location.href = "https://external.example/article";')
        raise AssertionError('An unauthorized or unexpected URL was read')
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    config = {'mode': 'html', 'url': preset['url'], 'preset_id': preset['id'],
              'article_path_prefix': preset['article_path_prefix']}
    entries = asyncio.run(source_sync.fetch_index(config))
    assert list(entries) == [{'title': '公告1', 'url': 'https://www.lib.whu.edu.cn/engine2/d/1/5619257/0?t=11166542&p=1',
                              'published_at': '2026-06-08'}]
    assert len(entries.rejected) == 3 and len(requests) == 4
    assert entries.rejected[0]['url'] == external and '外部网页' in entries.rejected[0]['reason']
    assert not any('external.example' in url for url in requests)
    assert not any('mp.weixin.qq.com' in url for url in requests)
    assert entries.snapshot['format'] == 'library-public-list'


def test_one_timed_out_library_link_does_not_discard_other_notices(monkeypatch):
    preset=get_preset('whu-library-notices')
    index='var engineInstanceId = 5619257; var sign = "0123456789abcdef0123456789abcdef"; var appId = 4627353;'
    def row(number):
        return {'id':number,'typeId':'11166542','pageType':1,'isOuter':False,'publicUse':True,'isPublish':1,
                '1':{'value':f'公告{number}'},'6':{'value':'2026-06-08'},
                'url':f'/engine2/general-rest/{number}/proxy-detail-url?pageType=1&typeId=11166542&dataTypeId=11166542&pageId=1&engineInstanceId=5619257&sign=public'}
    def handler(request):
        if request.url.path.endswith('/more'):return httpx.Response(200,text=index)
        if request.url.path.endswith('/more-datas'):return httpx.Response(200,json={'code':1,'data':{'datas':{'datas':[row(1),row(2)]}}})
        if '/1/proxy-detail-url' in request.url.path:raise httpx.ReadTimeout('temporarily unavailable',request=request)
        if '/2/proxy-detail-url' in request.url.path:return httpx.Response(200,text='window.location.href = "/engine2/d/2/5619257/0?t=11166542&p=1";')
        raise AssertionError('Unexpected URL')
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    config={'mode':'html','url':preset['url'],'preset_id':preset['id'],'article_path_prefix':preset['article_path_prefix']}
    entries=asyncio.run(source_sync.fetch_index(config))
    assert [item['title'] for item in entries]==['公告2']
    assert len(entries.rejected)==1 and entries.rejected[0]['title']=='公告1'
