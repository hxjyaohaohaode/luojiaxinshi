"""Anonymous WHU recruitment and campus-presentation feeds."""
import asyncio
import hashlib
import re
import time
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

import httpx
from fastapi import HTTPException

from .documents import MAX_CHARS, text_source, total_chars
from .employment_source import HOST, _json_get
from .evidence_web import public_url
from .official_sources import _FILES, _PERMISSION, _Tree, _clean, _date
from .public_http import PublicHTTPTransport
from .source_fetch import transport


CONFIG = {
    'whu-employment-jobs': {'kind': 'job', 'position_type': '1'},
    'whu-employment-internships': {'kind': 'job', 'position_type': '2'},
    'whu-employment-fairs': {'kind': 'fair'},
}
PATHS = {'job': ('/f/recruitmentinfo/show', 'recruitmentId'),
         'fair': ('/f/recruitmentFair/show', 'recruitmentFairId')}
PUBLIC_DETAIL_PATHS = {'job': ('/frontpage/whu/html/recruitmentinfoForm.html', 'positionDetailId'),
                       'fair': ('/frontpage/whu/html/recruitmentFairForm.html', 'id')}
LIST_API = {'job': 'https://xsjy.whu.edu.cn/f/recruitmentinfo/ajax_frontRecruitinfo',
            'fair': 'https://xsjy.whu.edu.cn/f/recruitmentFair/ajax_frontRecruitfair'}
DETAIL_API = {'job': 'https://xsjy.whu.edu.cn/f/recruitmentinfo/ajax_show',
              'fair': 'https://xsjy.whu.edu.cn/f/recruitmentFair/ajax_show'}
PAGE_SIZE = 15
MAX_PAGES = 3


def career_identity(url):
    safe = public_url(url)
    if not safe:
        return None
    parts = urlsplit(safe)
    if parts.scheme != 'https' or parts.hostname != HOST:
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    for routes in (PATHS, PUBLIC_DETAIL_PATHS):
        for kind, (path, key) in routes.items():
            values = query.get(key, [])
            if (parts.path == path and set(query) == {key} and len(values) == 1 and
                    re.fullmatch(r'[0-9a-fA-F]{32}', values[0])):
                return kind, values[0]
    return None


async def fetch_career_entries(client, preset_id):
    config = CONFIG.get(preset_id)
    if not config:
        raise HTTPException(422, '就业栏目范围不匹配')
    kind = config['kind']
    entries, rejected, seen, digests = [], [], set(), []
    total = None
    expired = 0
    for page in range(1, MAX_PAGES + 1):
        params = {'pageNo': str(page), 'pageSize': str(PAGE_SIZE)}
        if kind == 'job':
            params['positionType'] = config['position_type']
        else:
            params.update(fairType='', title='')
        payload, digest = await _json_get(client, LIST_API[kind], params)
        digests.append(digest)
        try:
            obj = payload['object']
            rows = obj['list']
            if not isinstance(obj, dict) or not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                raise ValueError('unexpected list')
            count = obj.get('count')
            if count is not None and (isinstance(count, bool) or not str(count).isdigit()):
                raise ValueError('unexpected count')
            if total is None and count is not None:
                total = int(count)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(422, '就业信息列表结构已变化，未接收导航内容') from None
        for item in rows:
            if not isinstance(item, dict):
                rejected.append({'url': LIST_API[kind], 'reason': '列表存在无法识别的项目'})
                continue
            raw_url, title = item.get('url'), item.get('title')
            target = public_url(urljoin(LIST_API[kind], raw_url)) if isinstance(raw_url, str) else None
            identity = career_identity(target or '')
            if (not identity or identity != (kind, item.get('id')) or
                    not isinstance(title, str) or not _clean(title) or
                    (kind == 'job' and (str(item.get('positionType')) != config['position_type'] or
                                        str(item.get('isFrontShow')) != '1'))):
                rejected.append({'url': target or LIST_API[kind], 'reason': '信息不在已订阅的武汉大学就业栏目'})
                continue
            # The university's listing marks ended presentations separately.
            # Existing received notices are never deleted when an event ends.
            if kind == 'fair' and str(item.get('isExpired')) == '1':
                expired += 1
                continue
            if target in seen:
                continue
            entries.append({'url': target, 'title': _clean(title)[:160],
                            'published_at': _date(str(item.get('updateDate') or '')) if kind == 'fair' else None})
            seen.add(target)
        if len(rows) < PAGE_SIZE:
            break
    snapshot = {'data_sha256': hashlib.sha256(''.join(digests).encode('ascii')).hexdigest(),
                'format': 'whu-career-public-api', 'pages_read': len(digests),
                'listed_total': total, 'ended_events_skipped': expired,
                'window_limited': total is not None and total > len(digests) * PAGE_SIZE}
    return entries, rejected, snapshot, not entries and not rejected


def _field(value):
    if value is None or isinstance(value, (dict, list, bool)):
        return ''
    return _clean(str(value))


def _body(html):
    root = _Tree(html).root
    text = '\n'.join(_clean(line) for line in root.text().splitlines() if _clean(line))
    return root, text


async def read_career_article(url):
    identity = career_identity(url)
    if not identity:
        raise HTTPException(422, '就业信息地址不在已识别范围内')
    kind, item_id = identity
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(transport=transport(PublicHTTPTransport), trust_env=False,
                follow_redirects=False, timeout=httpx.Timeout(15, connect=5)) as client:
            payload, digest = await _json_get(client, DETAIL_API[kind], {PATHS[kind][1]: item_id})
    except (httpx.HTTPError, OSError, TimeoutError, ValueError, LookupError):
        raise HTTPException(422, '就业信息读取失败，已有内容保留') from None
    try:
        obj = payload['object']
        item = obj['recruitmentinfo' if kind == 'job' else 'recruitmentFair']
        raw_url = item['url']
        target = public_url(urljoin(url, raw_url)) if isinstance(raw_url, str) else None
        title, content = item['title'], item.get('content') or ''
        if (not isinstance(obj, dict) or not isinstance(item, dict) or career_identity(target or '') != identity or
                (kind == 'fair' and item.get('id') != item_id) or
                str(item.get('isFrontShow')) != '1' or not isinstance(title, str) or not _clean(title) or
                not isinstance(content, str)):
            raise ValueError('unexpected detail')
        title = _clean(title)[:160]
        positions = item.get('recruitmentPositionList' if kind == 'job' else 'recruitmentFairPositionList') or []
        if not isinstance(positions, list) or len(positions) > 200:
            raise ValueError('unexpected positions')
    except (KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(422, '就业信息正文不完整或不属于公开栏目') from None
    root, main_text = _body(content)
    if main_text and _PERMISSION.search(main_text) and len(main_text) < 300:
        raise HTTPException(422, '此就业信息需要登录，未作为公开正文接收')
    blocks = []
    company = _field(item.get('corporationName'))
    if not company and isinstance(item.get('corporationinfo'), dict):
        company = _field(item['corporationinfo'].get('name'))
    if company:
        blocks.append('用人单位：' + company)
    start, end = _field(item.get('startTime')), _field(item.get('endTime'))
    if kind == 'fair':
        if start:
            blocks.append('举办开始时间：' + start)
        if end:
            blocks.append('举办结束时间：' + end)
        field = item.get('field') if isinstance(item.get('field'), dict) else {}
        location = _field(item.get('fieldExport')) or _field(field.get('name')) or _field(item.get('place'))
        if location:
            blocks.append('举办地点：' + location)
    else:
        location = ''
        if start:
            blocks.append('网站标注日期：' + start)
        if end:
            blocks.append('网站标注结束时间：' + end)
    links = []
    for label, key in [('网申入口', 'onlineApplicationUrl'), ('线上宣讲入口', 'videourl'), ('其他活动链接', 'otherlink')]:
        target = public_url(str(item.get(key) or ''))
        if target:
            blocks.append(label + '：' + target)
            links.append({'url': target, 'title': label})
    email = _field(item.get('resumeReceiveEmail'))
    if re.fullmatch(r'[^\s@<>]{1,100}@[^\s@<>]{1,150}', email):
        blocks.append('简历接收邮箱：' + email)
    for position in positions:
        if not isinstance(position, dict):
            raise HTTPException(422, '职位信息结构不完整，请打开原文核对')
        lines = []
        for key, label in [('positionName', '职位'), ('studentType', '学历'), ('demandNumber', '需求人数'),
                           ('majorName', '需求专业'), ('cityName', '工作地点'), ('salaryMonth', '月薪')]:
            value = _field(position.get(key))
            if value:
                lines.append(label + '：' + value)
        description = position.get('positionDescription')
        if isinstance(description, str) and description:
            _, value = _body(description)
            if value:
                lines.append('职位说明：' + value)
        if lines:
            blocks.append('\n'.join(lines))
    if main_text:
        blocks.append('招聘原文：\n' + main_text)
    attachments, names = [], {}
    for node in root.walk():
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
        elif len(links) < 100:
            links.append({'url': target, 'title': label[:300]})
    raw_file = item.get('fileURL' if kind == 'job' else 'fileUrl')
    files = obj.get('fileMap') or []
    if not isinstance(files, list) or len(files) > 30:
        raise HTTPException(422, '就业信息附件列表不完整或超出读取范围')
    if isinstance(raw_file, str) and raw_file:
        files = [*files, {'fileUrl': raw_file, 'fileName': _field(obj.get('fileName')) or '附件'}]
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get('fileUrl'), str):
            continue
        target = public_url(urldefrag(urljoin(url, file['fileUrl']))[0])
        if target and target not in attachments and len(attachments) < 30:
            attachments.append(target)
            names[target] = _field(file.get('fileName'))[:160] or '附件'
    has_media = any(n.tag in {'img', 'video', 'audio', 'iframe'} for n in root.walk())
    if not main_text and not positions:
        for node in root.walk():
            if node.tag != 'img':
                continue
            target = public_url(urldefrag(urljoin(url, node.attrs.get('src') or ''))[0])
            image_type = re.search(r'\.(png|jpe?g|webp)$', urlsplit(target).path, re.I) if target else None
            if image_type and target not in attachments and len(attachments) < 30:
                attachments.append(target)
                names[target] = '信息图片.' + image_type[1].lower()
    incomplete = not main_text and not positions
    if incomplete and not blocks and not attachments:
        raise HTTPException(422, '就业信息没有可读取的公开内容')
    kept, size, omitted = [], 0, 0
    for block in blocks:
        if size + len(block) + 2 <= MAX_CHARS - 100:
            kept.append(block)
            size += len(block) + 2
        else:
            omitted += 1
    warnings = []
    if has_media:
        warnings.append('原文含图片或音视频，请按需要核对原件')
    if attachments:
        warnings.append('原文含外链附件，请核对并补上传关键附件')
    if incomplete:
        warnings.append('未取得完整招聘正文，当前仅保留可读信息；请核对原文')
    if omitted:
        warnings.append(f'{omitted} 段招聘正文或职位信息超出本次文字上限，未完整接收；请打开原文')
    text = '\n\n'.join(kept) or title
    source = text_source(text, title)
    if incomplete or omitted:
        source['status'] = 'review'
        source['warning'] = '招聘正文或职位信息未完整读取，请打开原文核对'
    if total_chars([source]) > MAX_CHARS:
        raise HTTPException(422, '就业信息超过读取上限，请打开原文核对')
    published = _date(_field(item.get('updateDate'))) if kind == 'fair' else None
    origin = {'url': url, 'retrieved_at': int(time.time()), 'title': title,
              'published_at': published, 'published_at_precision': 'date' if published else None,
              'parser_id': 'whu-career-' + kind, 'attachments': attachments, 'attachment_names': names,
              'warnings': warnings, 'related_links': links[:100], 'raw_sha256': digest,
              'acquisition': 'fetched_uncached', 'parser_version': '2',
              'event_start': start if kind == 'fair' else '', 'event_end': end if kind == 'fair' else '',
              'event_location': location, 'source_display_date': start if kind == 'job' else ''}
    if incomplete:
        origin['attachment_only'] = bool(attachments)
    source['origin'] = origin
    return source, title
