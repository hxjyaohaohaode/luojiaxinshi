"""School notice-board publications from selected Wuhan University units.

This is a partial, explicitly labelled supplement while some unit sites require
verification. It never retrieves or attempts to solve verification pages.
"""
import re
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException

from .evidence_web import decode_page
from .official_sources import _Node, _Tree, _article_url, _clean, _date


PUBLISHERS = frozenset({
    '党委学生工作部', '学生工作部', '党委研究生工作部',
    '共青团武汉大学委员会', '武汉大学团委', '校团委',
    '财务部', '武汉大学财务部',
    '第一临床学院', '武汉大学第一临床学院', '武汉大学人民医院',
    '第二临床学院', '武汉大学第二临床学院', '武汉大学中南医院',
})


def parse_page(text, url):
    root = _Tree(text).root
    table = next((n for n in root.walk() if n.tag == 'table' and
                  all(label in n.text() for label in ('发布单位', '发布日期'))), None)
    if table is None:
        raise HTTPException(422, '学校公告列表结构已变化，无法确认发布单位')
    entries = []
    for row in (n for n in table.walk() if n.tag == 'tr'):
        cells = [n for n in row.children if isinstance(n, _Node) and n.tag == 'td']
        if len(cells) < 3:
            continue
        publisher = _clean(cells[1].text()).replace('\u200b', '')
        names = set(re.split(r'[\s,，、;；/]+', publisher))
        if not names.intersection(PUBLISHERS):
            continue
        for link in (n for n in cells[0].walk() if n.tag == 'a'):
            target = _article_url(link.attrs.get('href'), url, 'whu-notices')
            title = _clean(link.attrs.get('title') or link.text())
            if target and title:
                entries.append({'url': target, 'title': title[:160],
                                'published_at': _date(cells[2].text()), 'publisher': publisher})
                break
    pages = {}
    for link in (n for n in root.walk() if n.tag == 'a'):
        label = _clean(link.text())
        target = urljoin(url, link.attrs.get('href', ''))
        parts = urlsplit(target)
        if (label in {'2', '3', '4', '5'} and parts.scheme == 'https' and
                parts.hostname == 'www.whu.edu.cn' and not parts.query and not parts.fragment and
                re.fullmatch(r'/tzgg/\d+\.htm', parts.path)):
            pages[int(label)] = target
    return entries, pages


async def fetch_entries(client, url, text):
    entries, pages = parse_page(text, url)
    visited = [url]
    for number in sorted(pages):
        target = pages[number]
        if target in visited:
            continue
        async with client.stream('GET', target, headers={'User-Agent': 'LuojiaNoticeReader/1.0'}) as response:
            if response.status_code != 200:
                raise HTTPException(502, f'学校公告第 {number} 页返回 HTTP {response.status_code}，本次未完成检查')
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1_500_000:
                    raise HTTPException(413, '学校公告列表过大，未截断')
            page, _ = decode_page(content, response.charset_encoding)
            found, _ = parse_page(page, target)
            entries.extend(found)
            visited.append(target)
    unique = {item['url']: item for item in entries}
    return list(unique.values()), {'pages_checked': len(visited), 'page_urls': visited}
