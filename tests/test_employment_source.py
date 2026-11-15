"""Public WHU employment announcements retain original links and materials."""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app import employment_source, source_sync
from app.official_sources import get_preset


ID = '543adf64a27a4b118b32ef90fc95fe99'
URL = f'https://xsjy.whu.edu.cn/frontpage/whu/html/newsDetail.html?id={ID}'


def article(**changes):
    value = {'id': ID, 'title': '基层就业活动通知', 'releaseDate': '2026-11-12 19:53',
             'isExternalLink': False, 'category': {'id': employment_source.CATEGORY},
             'articleData': {'content': '<p>报名时间和条件见原文。</p>'}, 'hasAttachment': True}
    value.update(changes)
    return value


def test_employment_index_and_article_read_anonymous_api_and_retain_attachment(monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/newsList.html'):
            return httpx.Response(200, text='<html>employment list</html>')
        assert request.headers.get('cache-control') == 'no-store' and 'cookie' not in request.headers
        if request.url.path.endswith('/ajax_cmsListByIds'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': [[{
                'id': ID, 'url': '/frontpage/whu/html/newsDetail.html?id='+ID, 'title': '基层就业活动通知',
                'releaseDate': '2026-11-12 19:53', 'isExternalLink': False, 'category': {'id': employment_source.CATEGORY}},
                {'id': 'x', 'url': 'https://other.example/private', 'title': '外站', 'isExternalLink': True},
                {'id': ID, 'url': '/frontpage/whu/html/newsDetail.html?id='+ID,
                 'title': '错误栏目', 'isExternalLink': False, 'category': 'not-an-object'}]]})
        if request.url.path.endswith('/ajax_view'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'article': article(),
                'fileMap': [{'fileName': '报名表.docx', 'fileUrl': '/files/form.docx'}]}})
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(employment_source, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    p = get_preset('whu-employment')
    config = {'url': p['url'], 'preset_id': p['id'], 'article_path_prefix': p['article_path_prefix'], 'mode': 'html'}
    entries = asyncio.run(source_sync.fetch_index(config))
    assert list(entries) == [{'url': URL, 'title': '基层就业活动通知', 'published_at': '2026-11-12'}]
    assert len(entries.rejected) == 2
    source, title = asyncio.run(employment_source.read_employment_article(URL))
    assert title == '基层就业活动通知' and source['origin']['url'] == URL
    assert source['origin']['published_at'] == '2026-11-12'
    assert source['origin']['attachments'] == ['https://xsjy.whu.edu.cn/files/form.docx']
    assert source['origin']['attachment_names']['https://xsjy.whu.edu.cn/files/form.docx'] == '报名表.docx'
    assert not any('other.example' in u for u in calls)


def test_employment_rejects_private_or_wrong_article(monkeypatch):
    assert employment_source.article_id(URL+'&next=https://other.example') is None
    assert employment_source.article_id(URL+'&next=') is None
    for payload in [
        {'state': 1, 'jessionid': 'private-session', 'object': {'article': article()}},
        {'state': 1, 'jessionid': '', 'object': {'article': article(id='bad')}},
        {'state': 1, 'jessionid': '', 'object': {'article': article(articleData={'content': '<p>请登录后查看</p>'})}},
    ]:
        monkeypatch.setattr(employment_source, 'PublicHTTPTransport', lambda p=payload: httpx.MockTransport(lambda request: httpx.Response(200, json=p)))
        with pytest.raises(HTTPException):
            asyncio.run(employment_source.read_employment_article(URL))
    monkeypatch.setattr(employment_source, 'PublicHTTPTransport',
        lambda: httpx.MockTransport(lambda request: httpx.Response(200, json={'state': 2, 'msg': '请登录后查看！'})))
    with pytest.raises(HTTPException, match='需要登录'):
        asyncio.run(employment_source.read_employment_article(URL))


def test_employment_image_only_notice_retains_original_and_requires_review(monkeypatch):
    payload = {'state': 1, 'jessionid': '', 'object': {'article': article(hasAttachment=False,
        articleData={'content': '<p><img src="/files/notice.jpg"></p>'})}}
    monkeypatch.setattr(employment_source, 'PublicHTTPTransport',
        lambda: httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    source, title = asyncio.run(employment_source.read_employment_article(URL))
    assert source['status'] == 'review' and source['origin']['attachment_only']
    assert source['origin']['attachments'] == ['https://xsjy.whu.edu.cn/files/notice.jpg']
    assert '只有标题' in source['warning'] and title == '基层就业活动通知'
