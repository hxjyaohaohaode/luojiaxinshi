"""Read public notices from WHU's dynamic employment website by its GET API."""
import asyncio
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

import httpx
from fastapi import HTTPException

from .documents import MAX_CHARS, text_source, total_chars
from .evidence_web import public_url
from .official_sources import _FILES, _PERMISSION, _Tree, _clean, _date
from .public_http import PublicHTTPTransport
from .source_fetch import transport


HOST = 'xsjy.whu.edu.cn'
CATEGORY = '739BEBB72A0B2B25E0538713470A6C41'
INDEX_API = 'https://xsjy.whu.edu.cn/f/ajaxHome/ajax_cmsListByIds'
ARTICLE_API = 'https://xsjy.whu.edu.cn/f/newsCenter/ajax_view'
ARTICLE_PATH = '/frontpage/whu/html/newsDetail.html'


def article_id(url):
    safe = public_url(url)
    if not safe:
        return None
    parts = urlsplit(safe)
    if parts.scheme != 'https' or parts.hostname != HOST or parts.path != ARTICLE_PATH:
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    values = query.get('id', [])
    if set(query) != {'id'} or len(values) != 1 or not re.fullmatch(r'[0-9a-fA-F]{32}', values[0]):
        return None
    return values[0]


async def _json_get(client, url, params):
    # The endpoint may include a session field. Do not reuse cookies or store
    # its response in the shared public cache; reject any session-bearing data.
    client.cookies.clear()
    async with client.stream('GET', url, params=params,
            headers={'User-Agent': 'LuojiaNoticeReader/1.0', 'Cache-Control': 'no-store'}) as response:
        if response.status_code != 200:
            raise HTTPException(422, f'就业中心公开接口返回 HTTP {response.status_code}，本次未读取')
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > 1_500_000:
                raise HTTPException(413, '就业中心公告过大，未接收截断内容')
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get('state') != 1 and _PERMISSION.search(str(result.get('msg') or '')):
                raise HTTPException(422, '这则就业公告需要登录，未作为公开正文接收')
            if not isinstance(result, dict) or result.get('state') != 1 or result.get('jessionid'):
                raise ValueError('not an anonymous public response')
        except (ValueError, TypeError):
            raise HTTPException(422, '就业中心返回的数据不完整或不是匿名公开内容') from None
        return result, hashlib.sha256(raw).hexdigest()


async def fetch_employment_entries(client):
    payload, digest = await _json_get(client, INDEX_API, {'categoryIds': CATEGORY, 'number': '8'})
    try:
        groups = payload['object']
        if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], list) or len(groups[0]) > 8:
            raise ValueError('unexpected list')
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, '就业中心公告列表结构已变化') from None
    entries, rejected, seen = [], [], set()
    for item in groups[0]:
        if not isinstance(item, dict):
            rejected.append({'url': INDEX_API, 'reason': '公告列表存在无法识别的项目'})
            continue
        raw_url = item.get('url')
        target = public_url(urljoin(INDEX_API, raw_url)) if isinstance(raw_url, str) else None
        identity = article_id(target or '')
        title = item.get('title')
        category = item.get('category')
        if (not identity or identity != item.get('id') or item.get('isExternalLink') is not False or
                not isinstance(category, dict) or category.get('id') != CATEGORY or
                not isinstance(title, str) or not _clean(title)):
            rejected.append({'url': target or INDEX_API, 'reason': '公告不在已订阅的就业中心栏目'})
            continue
        if target in seen:
            continue
        entries.append({'url': target, 'title': _clean(title)[:160],
                        'published_at': _date(str(item.get('releaseDate') or ''))})
        seen.add(target)
    if not entries:
        raise HTTPException(422, '就业中心当前列表没有可识别的公开公告')
    return entries, rejected, {'data_sha256': digest, 'format': 'whu-employment-public-api'}


async def read_employment_article(url):
    identity = article_id(url)
    if not identity:
        raise HTTPException(422, '就业公告地址不在已识别范围内')
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(transport=transport(PublicHTTPTransport), trust_env=False,
                follow_redirects=False, timeout=httpx.Timeout(15, connect=5)) as client:
            payload, digest = await _json_get(client, ARTICLE_API, {'id': identity})
    except (httpx.HTTPError, OSError, TimeoutError, ValueError, LookupError):
        raise HTTPException(422, '就业公告读取失败，已有通知保留') from None
    try:
        obj = payload['object']
        article = obj['article']
        title = article['title']
        content = article['articleData']['content']
        if (article.get('id') != identity or article.get('isExternalLink') is not False or
                (article.get('category') or {}).get('id') != CATEGORY or not isinstance(title, str) or
                not _clean(title) or not isinstance(content, str)):
            raise ValueError('unexpected article')
        title = _clean(title)[:160]
        published = _date(str(article.get('releaseDate') or ''))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(422, '就业中心正文不完整或不属于公开公告栏目') from None
    body = _Tree(content).root
    text = '\n'.join(_clean(line) for line in body.text().splitlines() if _clean(line))
    if text and _PERMISSION.search(text) and len(text) < 300:
        raise HTTPException(422, '这则就业公告需要登录或没有公开正文')
    attachments, names, related = [], {}, []
    for node in body.walk():
        if node.tag != 'a':
            continue
        target = public_url(urldefrag(urljoin(url, node.attrs.get('href') or ''))[0])
        label = _clean(node.text())
        if not target:
            continue
        if _FILES.search(target) or _FILES.search(label):
            if target not in attachments and len(attachments) < 30:
                attachments.append(target)
                names[target] = label[:160]
        elif len(related) < 100:
            related.append({'url': target, 'title': label[:300]})
    files = obj.get('fileMap') or []
    if not isinstance(files, list) or len(files) > 30:
        raise HTTPException(422, '就业公告附件列表不完整或超出读取范围')
    for item in files:
        if not isinstance(item, dict):
            continue
        name, path = item.get('fileName'), item.get('fileUrl')
        if not isinstance(name, str) or not isinstance(path, str):
            continue
        target = public_url(urldefrag(urljoin(url, path))[0])
        if target and target not in attachments and len(attachments) < 30:
            attachments.append(target)
            names[target] = name[:160]
    media = any(n.tag in {'img', 'video', 'audio', 'iframe'} for n in body.walk())
    image_only = not text
    if image_only:
        for node in body.walk():
            if node.tag != 'img':
                continue
            target = public_url(urldefrag(urljoin(url, node.attrs.get('src') or ''))[0])
            image_type = re.search(r'\.(png|jpe?g|webp)$', urlsplit(target).path, re.I) if target else None
            if image_type and target not in attachments and len(attachments) < 30:
                attachments.append(target)
                names[target] = '公告图片.' + image_type[1].lower()
        if not attachments:
            raise HTTPException(422, '这则就业公告需要登录或没有公开正文')
        text = title
    warnings = []
    if media:
        warnings.append('网页中的图片、音视频未自动读取，请按需要补上传原件')
    if attachments:
        warnings.append('原文含外链附件，请核对并补上传关键附件')
    if article.get('hasAttachment') and not attachments:
        warnings.append('原文标有附件，但未取得附件地址，请打开原文核对')
    source = text_source(text, title)
    if image_only:
        warnings.append('原文以图片或附件形式发布，当前文字仅为标题；请核对原件')
        source['status'] = 'review'
        source['warning'] = '通知内容位于图片或附件，当前网页只有标题；请核对原件内容后使用'
    if total_chars([source]) > MAX_CHARS:
        raise HTTPException(422, f'就业公告超过 {MAX_CHARS:,} 字，请打开原文核对')
    source['origin'] = {'url': url, 'retrieved_at': int(time.time()), 'title': title,
                        'published_at': published, 'published_at_precision': 'date' if published else None,
                        'parser_id': 'whu-employment', 'attachments': attachments, 'attachment_names': names,
                        'warnings': warnings, 'related_links': related, 'raw_sha256': digest,
                        'acquisition': 'fetched_uncached', 'parser_version': '2'}
    if image_only:
        source['origin']['attachment_only'] = True
    return source, title
