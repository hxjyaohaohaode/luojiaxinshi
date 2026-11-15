"""Read the library's public, dynamic notice list without executing scripts."""
import hashlib
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from fastapi import HTTPException

from .evidence_web import public_url
from .official_sources import _clean, _date


HOST = 'www.lib.whu.edu.cn'
API = 'https://www.lib.whu.edu.cn/engine2/general/4627353/type/more-datas'


async def _read(client, url, *, params=None, referer=None, limit=1_500_000):
    # An anonymous subscription must not forward cookies, including any set by
    # an earlier response from this public site.
    client.cookies.clear()
    headers = {'User-Agent': 'LuojiaNoticeReader/1.0'}
    if referer:
        headers['Referer'] = referer
    async with client.stream('GET', url, params=params, headers=headers) as response:
        if response.status_code != 200:
            raise HTTPException(502, f'图书馆公告返回 HTTP {response.status_code}，本次未完成读取')
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise HTTPException(413, '图书馆公告数据过大，未接收截断内容')
        return bytes(data)


def _proxy_url(index_url, item):
    value = item.get('url')
    if not isinstance(value, str):
        return None
    candidate = public_url(urljoin(index_url, value))
    if not candidate:
        return None
    parts = urlsplit(candidate)
    query = parse_qs(parts.query)
    if (parts.hostname != HOST or parts.scheme != 'https' or
            parts.path != f"/engine2/general-rest/{item['id']}/proxy-detail-url" or
            query.get('pageType') != ['1'] or query.get('typeId') != ['11166542'] or
            query.get('dataTypeId') != ['11166542'] or query.get('pageId') not in (['740716'], ['1']) or
            query.get('engineInstanceId') != ['5619257'] or len(query.get('sign', [])) != 1):
        return None
    return candidate


def _article_url(index_url, item_id, page_id, raw):
    # The response is a literal site-provided JavaScript string, parsed only as
    # JSON. Never run it or follow a redirect to another host or column.
    matches = list(re.finditer(r'window\.location\.href\s*=\s*("(?:\\.|[^"\\])*")\s*;', raw))
    if len(matches) != 1:
        return None
    try:
        value = json.loads(matches[0][1])
    except (ValueError, TypeError):
        return None
    candidate = public_url(urljoin(index_url, value))
    if not candidate:
        return None
    parts = urlsplit(candidate)
    if (parts.scheme != 'https' or parts.hostname != HOST or
            parts.path != f'/engine2/d/{item_id}/5619257/0' or
            parse_qs(parts.query) != {'t': ['11166542'], 'p': [page_id]}):
        return None
    return candidate


async def fetch_library_entries(client, index_url, index_text):
    for variable, expected in [('engineInstanceId', '5619257'), ('appId', '4627353')]:
        values = re.findall(r'\bvar\s+' + variable + r'\s*=\s*(\d+)\s*;', index_text)
        if values != [expected]:
            raise HTTPException(422, '图书馆公告栏目结构已变化，未读取其他栏目')
    signs = re.findall(r'\bvar\s+sign\s*=\s*"([a-f0-9]{32})"\s*;', index_text)
    if len(signs) != 1:
        raise HTTPException(422, '图书馆公告列表缺少公开读取参数')
    params = {'engineInstanceId': '5619257', 'sign': signs[0], 'pageNum': '1', 'pageSize': '10',
              'typeId': '11166542', 'topTypeId': '', 'sw': '', 'startDate': '', 'endDate': '',
              'typeDataSort': '', 'needViewNum': 'false'}
    raw = await _read(client, API, params=params, referer=index_url)
    try:
        payload = json.loads(raw)
        rows = payload['data']['datas']['datas']
        if payload.get('code') != 1 or not isinstance(rows, list) or not 1 <= len(rows) <= 10:
            raise ValueError('unexpected list')
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(422, '图书馆公告列表数据不完整或结构已变化') from None
    entries, rejected, seen = [], [], set()
    for item in rows:
        if not isinstance(item, dict):
            rejected.append({'url': index_url, 'reason': '公告列表存在无法识别的项目'})
            continue
        item_id = item.get('id')
        label = item.get('1', {})
        label = _clean(label.get('value', '')) if isinstance(label, dict) and isinstance(label.get('value', ''), str) else ''
        if (not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0 or
                item.get('typeId') != '11166542' or item.get('pageType') != 1 or
                item.get('isOuter') is not False or item.get('publicUse') is not True or
                item.get('isPublish') != 1 or not label):
            rejected.append({'url': index_url, 'title': label[:160], 'reason': '不是本馆可公开读取的栏目原文'})
            continue
        proxy = _proxy_url(index_url, item)
        if not proxy:
            rejected.append({'url': index_url, 'title': label[:160], 'reason': '图书馆原文地址不符合订阅范围'})
            continue
        try:
            redirect = await _read(client, proxy, referer=index_url, limit=16384)
            page_id = parse_qs(urlsplit(proxy).query)['pageId'][0]
            target = _article_url(index_url, item_id, page_id, redirect.decode('utf-8'))
        except HTTPException as error:
            if error.status_code == 429:
                raise
            target = None
        except UnicodeError:
            target = None
        if not target:
            rejected.append({'url': index_url, 'title': label[:160], 'reason': '无法确认图书馆公告原文地址'})
            continue
        if target in seen:
            continue
        stamp = item.get('6', {})
        published = _date(stamp.get('value', '')) if isinstance(stamp, dict) and isinstance(stamp.get('value', ''), str) else None
        entries.append({'url': target, 'title': label[:160], 'published_at': published})
        seen.add(target)
    if not entries:
        raise HTTPException(422, '图书馆列表没有可确认的公开公告原文')
    return entries, rejected, {'data_sha256': hashlib.sha256(raw).hexdigest(), 'format': 'library-public-list'}
