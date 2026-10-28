"""Offline contracts using bounded excerpts of live public columns."""
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app import notice_intake
from app.documents import MAX_CHARS, MAX_FILE, text_source
from app.official_sources import get_preset, parse_official_article, parse_official_index


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'official-sources'
WHU = 'https://www.whu.edu.cn/info/5231/276744.htm'
JOURNAL = 'https://journal.whu.edu.cn/graduate/notice/20260918whfl'
SRES = 'https://sres.whu.edu.cn/info/3771/346681.htm'
SRES_PDF = 'https://sres.whu.edu.cn/info/3771/345931.htm'


def fixture(name):
    return (FIXTURES / (name + '.html')).read_text(encoding='utf-8')


def test_live_column_excerpts_preserve_dates_real_links_and_exclude_navigation():
    whu = get_preset('whu-notices')
    rows = parse_official_index(fixture('whu-index'), whu['url'], whu['id'])
    assert len(rows) == 10
    assert sum('/new2024/tzggnr.jsp?' in row['url'] for row in rows) == 5
    assert rows[0]['published_at'] == '2026-10-26'
    assert rows[2] == {'url': WHU, 'title': '珞珈讲坛第549讲预告', 'published_at': '2026-10-21'}
    journal = get_preset('whu-journal-affairs')
    rows = parse_official_index(fixture('journal-index'), journal['url'], journal['id'])
    assert len(rows) == 10 and rows[0]['url'] == JOURNAL
    assert rows[0]['published_at'] == '2026-09-18'
    assert any('/graduate/' in row['url'] for row in rows)
    assert all('/index' not in row['url'] for row in rows)
    mixed = fixture('journal-index').replace('<ul class="p-list5">', '<ul class="p-list5"><li><a href="/undergraduate/notice/20261029demo">本科通知</a><span class="date">2026-10-29</span></li>')
    assert parse_official_index(mixed, journal['url'], journal['id'])[0]['url'].endswith('/undergraduate/notice/20261029demo')
    assert get_preset('unknown') is None
    whu['url'] = 'changed'
    assert get_preset('whu-notices')['url'] != 'changed'


def test_index_rejects_structure_drift_wrong_host_and_out_of_scope_links():
    preset = get_preset('whu-journal-affairs')
    for text, url in [('<nav><a href="/graduate/notice/20261029abc">导航</a></nav>', preset['url']),
                      (fixture('journal-index'), 'https://other.example.org/index')]:
        with pytest.raises(HTTPException):
            parse_official_index(text, url, preset['id'])
    text = '<ul class="p-list5"><li><a href="https://other.example.org/graduate/notice/20261029abc">外站</a></li><li><a href="/graduate/notice/index">栏目</a></li></ul>'
    with pytest.raises(HTTPException):
        parse_official_index(text, preset['url'], preset['id'])


def test_sres_current_column_preserves_real_links_and_separates_title_from_date():
    preset = get_preset('whu-sres-notices')
    rows = parse_official_index(fixture('sres-index'), preset['url'], preset['id'])
    assert len(rows) == 15
    assert rows[1] == {'url': SRES, 'title': '第三届“星湖杯”地图设计大赛获奖名单公示', 'published_at': '2026-10-18'}
    assert len([row for row in rows if '/xzcontent.jsp?' in row['url']]) == 1
    assert all('【2026-' not in row['title'] and '/999.htm' not in row['url'] for row in rows)
    assert rows[0]['published_at'] == '2026-04-07'  # A pinned item is not a new date.


def test_sres_column_rejects_navigation_other_columns_and_bad_dynamic_ids():
    preset = get_preset('whu-sres-notices')
    for html in ['<nav><a href="/info/3771/346681.htm">学院导航</a></nav>',
                 '<ul class="list-container"><li><a href="/info/3271/346681.htm">其他栏目</a></li><li><a href="/xzcontent.jsp?wbtreeid=3271&wbnewsid=346681">错误栏目</a></li><li><a href="/xzcontent.jsp?wbtreeid=3771&wbnewsid=nope">错误编号</a></li></ul>']:
        with pytest.raises(HTTPException):
            parse_official_index(html, preset['url'], preset['id'])


def test_sres_article_keeps_full_body_and_attachment_link_without_chrome_icons():
    parsed = parse_official_article(fixture('sres-article'), SRES)
    assert parsed['title'] == '第三届“星湖杯”地图设计大赛获奖名单公示'
    assert parsed['published_at'] == '2026-10-18'
    assert '地图设计大赛完整获奖名单' in parsed['text']
    assert '学院概况' not in parsed['text'] and '版权所有' not in parsed['text']
    assert len(parsed['attachments']) == 1
    assert parsed['attachment_names'][parsed['attachments'][0]].endswith('.pdf')
    assert not parsed['has_media'] and not parsed['attachment_only']


def test_sres_pdf_only_page_preserves_literal_document_url_without_running_script():
    parsed = parse_official_article(fixture('sres-pdf-article'), SRES_PDF)
    assert parsed['text'] == parsed['title']
    assert parsed['published_at'] == '2026-09-15'
    assert parsed['attachment_only'] and '仅为标题' in parsed['warnings'][0]
    assert parsed['attachments'] == ['https://sres.whu.edu.cn/__local/6/8A/C1/2D837EF105F26E148837E0B296D_33BE5632_4F6B052.pdf']
    dynamic = fixture('sres-pdf-article').replace('showVsbpdfIframe("/__local/6/8A/C1/2D837EF105F26E148837E0B296D_33BE5632_4F6B052.pdf",', 'showVsbpdfIframe(resolveSecret(),')
    with pytest.raises(HTTPException, match='没有公开文字'):
        parse_official_article(dynamic, SRES_PDF)


@pytest.mark.parametrize(('name', 'url', 'published', 'needle'), [
    ('whu-article', WHU, '2026-10-21', '武汉大学樱顶老图书馆'),
    ('journal-article', JOURNAL, '2026-09-18', '9月21日上午9时'),
])
def test_real_article_regions_exclude_chrome_and_keep_original_title(name, url, published, needle):
    parsed = parse_official_article(fixture(name), url)
    assert needle in parsed['text']
    assert '版权所有' not in parsed['text'] and '学院概况' not in parsed['text']
    assert not parsed['has_media']
    assert parsed['published_at'] == published
    assert parsed['published_at_precision'] == 'date'
    assert parsed['title'] and '--武汉大学' not in parsed['title']


def test_permissions_structure_drift_and_body_images_are_explicit():
    with pytest.raises(HTTPException, match='校内权限'):
        parse_official_article('<div class="v_news_content">您没有权限访问，请登录后查看</div>', WHU)
    with pytest.raises(HTTPException, match='校内权限'):
        parse_official_article('<div>非常抱歉，您暂无权限浏览此页</div>', WHU)
    with pytest.raises(HTTPException, match='正文结构'):
        parse_official_article('<title>武汉大学</title><nav>新闻通知</nav>', WHU)
    assert parse_official_article('<p>普通网站正文</p>', 'https://school.example.org/a') is None
    raw = fixture('whu-article').replace('武汉大学樱顶老图书馆', '武汉大学樱顶老图书馆<img src="/poster.png">')
    assert parse_official_article(raw, WHU)['has_media']


def test_dynamic_attachment_link_and_publication_metadata_are_preserved():
    url = 'https://www.whu.edu.cn/new2024/tzggnr.jsp?urltype=news.NewsContentUrl&wbtreeid=5231&wbnewsid=277084'
    html = '<meta name="PubDate" content="2026-10-26 09:20"><div class="ar_tit"><h3>2026-11-01 活动报名</h3><p>发布时间：2026-10-26</p></div><div id="zoomcon"><div class="v_news_content"><p>报名需填写附件。</p></div><ul><li>附件【<a href="/system/_content/download.jsp?wbfileid=demo">报名表.docx</a>】</li></ul></div>'
    parsed = parse_official_article(html, url)
    assert parsed['published_at'] == '2026-10-26'
    attachment = 'https://www.whu.edu.cn/system/_content/download.jsp?wbfileid=demo'
    assert parsed['attachments'] == [attachment]
    assert parsed['attachment_names'][attachment] == '报名表.docx'


def mock_reader(monkeypatch, handler):
    monkeypatch.setattr(notice_intake, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))


def test_read_link_uses_article_adapter_without_automatically_downloading(monkeypatch):
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=fixture('whu-article'))
    mock_reader(monkeypatch, response)
    source, title = asyncio.run(notice_intake.read_link(WHU))
    assert source['origin']['title'] == title == '珞珈讲坛第549讲预告'
    assert source['origin']['published_at'] == '2026-10-21'
    assert source['origin']['warnings'] == []
    assert calls == [WHU]


def test_sres_pdf_only_link_is_review_material_not_complete_body(monkeypatch):
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=fixture('sres-pdf-article'))
    mock_reader(monkeypatch, response)
    source, title = asyncio.run(notice_intake.read_link(SRES_PDF))
    assert source['status'] == 'review'
    assert '只有标题' in source['warning']
    assert source['origin']['attachment_only'] is True
    assert len(source['origin']['attachments']) == 1
    assert source['origin']['attachments'][0].endswith('.pdf')
    assert any('仅为标题' in warning for warning in source['origin']['warnings'])
    assert source['sections'][0]['text'] == title
    assert calls == [SRES_PDF]


def primary(urls):
    source = text_source('通知正文')
    source['origin'] = {'url': WHU, 'attachments': urls,
                        'warnings': ['原文含外链附件，请核对并补上传关键附件']}
    return source


def document(url, text='附件内容', content=b'%PDF-test'):
    source = text_source(text)
    source.update(kind='pdf', content=content)
    source['origin'] = {'url': url, 'attachments': ['https://www.whu.edu.cn/nested.pdf'], 'warnings': []}
    return source, '附件'


def test_materials_are_same_host_bounded_nonrecursive_and_partial_failures_keep_text():
    calls = []
    urls = ['https://other.example.org/out.pdf'] + [f'https://www.whu.edu.cn/{i}.pdf' for i in range(6)]
    async def read(url):
        calls.append(url)
        if url.endswith('/1.pdf'):
            raise HTTPException(422, '附件暂时不可用')
        return document(url)
    result = asyncio.run(notice_intake.read_notice_materials(primary(urls), read=read))
    assert len(calls) == 4 and all('nested' not in url for url in calls)
    assert len(result) == 4 and result[0]['sections'][0]['text'] == '通知正文'
    warnings = ' '.join(result[0]['origin']['warnings'])
    assert '来源域名' in warnings and '暂时不可用' in warnings and '最多自动读取 4' in warnings


@pytest.mark.parametrize(('text', 'content'), [('字' * MAX_CHARS, b'%PDF-test'), ('短文', b'x' * (MAX_FILE + 1))], ids=['character-limit', 'byte-limit'])
def test_material_budget_skips_oversized_attachment_not_the_notice(text, content):
    async def read(url):
        return document(url, text=text, content=content)
    result = asyncio.run(notice_intake.read_notice_materials(primary(['https://www.whu.edu.cn/large.pdf']), read=read))
    assert len(result) == 1 and result[0]['sections'][0]['text'] == '通知正文'
    assert '主文已保留' in ' '.join(result[0]['origin']['warnings'])


def test_timeout_keeps_primary_and_successfully_read_attachment(monkeypatch):
    monkeypatch.setattr(notice_intake, 'ATTACHMENT_READ_SECONDS', 0.01)
    async def read(url):
        if url.endswith('slow.pdf'):
            await asyncio.sleep(1)
        return document(url)
    result = asyncio.run(notice_intake.read_notice_materials(primary([
        'https://www.whu.edu.cn/first.pdf', 'https://www.whu.edu.cn/slow.pdf']), read=read))
    assert len(result) == 2
    assert '已保留' in ' '.join(result[0]['origin']['warnings'])


def test_attachment_redirect_cannot_fetch_another_host(monkeypatch):
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'https://other.example.org/file.pdf'})
    mock_reader(monkeypatch, response)
    result = asyncio.run(notice_intake.read_notice_materials(primary(['https://www.whu.edu.cn/file.pdf'])))
    assert calls == ['https://www.whu.edu.cn/file.pdf'] and len(result) == 1
    assert '跳转出了通知来源域名' in ' '.join(result[0]['origin']['warnings'])


def test_download_endpoint_uses_content_disposition_filename(monkeypatch):
    def response(request):
        return httpx.Response(200, headers={'content-type': 'application/octet-stream',
            'content-disposition': "attachment; filename*=UTF-8''form.docx"}, content=b'docx-fixture')
    mock_reader(monkeypatch, response)
    def parse_file(name, content):
        source = text_source('报名表正文', name)
        source.update(kind='docx', content=content)
        return source
    monkeypatch.setattr(notice_intake, 'file_source', parse_file)
    url = 'https://www.whu.edu.cn/system/_content/download.jsp?wbfileid=demo'
    source = primary([url])
    source['origin']['attachment_names'] = {url: '报名表.docx'}
    result = asyncio.run(notice_intake.read_notice_materials(source))
    assert len(result) == 2 and result[1]['name'] == 'form.docx'
    assert result[0]['origin']['received_attachments'] == [url]
    assert not result[0]['origin']['warnings']
