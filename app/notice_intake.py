"""Explicit material intake and owner-controlled notice disposition.

Reading a public link produces a short-lived, owner-scoped preview. Saving uses
that exact snapshot, never a second fetch. No model or external account is used.
"""
import hashlib
import asyncio
import json
import re
import time
from email.message import Message
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from fastapi import Depends, HTTPException
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from .db import audit, dumps, ident
from .documents import MAX_CHARS, MAX_FILE, file_source, text_source, total_chars
from .evidence_web import PageText, decode_page, public_url
from .models import Strict
from .official_sources import parse_official_article
from .public_http import PublicHTTPTransport
from .security import rate_limit

TABLES = {'notice_dispositions', 'notice_link_previews', 'notice_source_origins', 'notice_submissions'}
ATTACHMENT_READ_SECONDS = 25
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_dispositions(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
 disposition TEXT NOT NULL, note TEXT NOT NULL, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notice_link_previews(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 data TEXT NOT NULL, content BLOB, expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS notice_link_previews_owner ON notice_link_previews(user_id,expires_at);
CREATE TABLE IF NOT EXISTS notice_source_origins(
 source_id TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notice_submissions(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, request_id TEXT NOT NULL,
 notice_id TEXT REFERENCES notices(id) ON DELETE SET NULL, digest TEXT NOT NULL,
 PRIMARY KEY(user_id,request_id));
INSERT OR IGNORE INTO meta VALUES('notice_intake_schema_version','1');
"""


class LinkRequest(Strict):
    url: str = Field(min_length=1, max_length=2000)

    @field_validator('url')
    @classmethod
    def public_only(cls, value):
        if not public_url(value):
            raise ValueError('请输入可公开访问的 http(s) 原文链接')
        return value


class DispositionUpdate(Strict):
    version: int = Field(ge=1)
    disposition: Literal['inbox', 'reference', 'not_applicable', 'closed']
    note: str = Field(default='', max_length=1000)


class IntakePage(PageText):
    def __init__(self, url):
        super().__init__()
        self.url, self.attachments, self.has_media = url, [], False

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag in {'img', 'video', 'audio', 'iframe'}:
            self.has_media = True
        if tag == 'a':
            url = public_url(urljoin(self.url, attrs.get('href', '')))
            if url and re.search(r'\.(pdf|docx?|xlsx?|zip|png|jpe?g)(?:[?#]|$)', url, re.I):
                if url not in self.attachments and len(self.attachments) < 30:
                    self.attachments.append(url)


async def read_link(url):
    """Bound every response and redirect; PublicHTTPTransport pins public DNS."""
    return await _read_link(url)


async def _read_link(url, allowed_host=None):
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(transport=PublicHTTPTransport(), trust_env=False,
                follow_redirects=False, timeout=httpx.Timeout(15, connect=5)) as client:
            for _ in range(4):
                if not public_url(url):
                    raise HTTPException(422, '链接跳转到了非公开地址，未读取')
                if allowed_host and urlsplit(url).hostname != allowed_host:
                    raise HTTPException(422, '附件跳转出了通知来源域名，未读取')
                async with client.stream('GET', url, headers={'User-Agent': 'LuojiaNoticeReader/1.0',
                        'Accept': 'text/html,text/plain,application/pdf,application/octet-stream'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    if response.status_code != 200:
                        raise HTTPException(422, '这个链接无法公开读取，请上传原件或粘贴正文')
                    mime = response.headers.get('content-type', '').split(';')[0].lower().strip()
                    content = bytearray()
                    limit = 1_500_000 if mime in {'text/html', 'application/xhtml+xml'} else MAX_FILE
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > limit:
                            raise HTTPException(413, '链接内容超过读取上限，请下载后按事项分别上传；未截断')
                    name = unquote(PurePosixPath(urlsplit(url).path).name) or '链接材料'
                    disposition_header = response.headers.get('content-disposition')
                    if disposition_header:
                        disposition = Message()
                        disposition['content-disposition'] = disposition_header
                        filename = disposition.get_filename()
                        if isinstance(filename, str) and filename.strip():
                            name = unquote(filename)
                    if mime in {'text/html', 'application/xhtml+xml', 'text/plain'}:
                        text, _ = decode_page(content, response.charset_encoding)
                        parser = IntakePage(url)
                        official = parse_official_article(text, url) if mime != 'text/plain' else None
                        if mime != 'text/plain':
                            if official:
                                text = official['text']
                                parser.attachments = official['attachments']
                                parser.has_media = official['has_media']
                            else:
                                parser.feed(text)
                                text = '\n'.join(p.strip() for p in ''.join(parser.parts).split('\n') if p.strip())
                        if not text.strip():
                            raise HTTPException(422, '网页没有可读取的正文，请粘贴原文或上传截图')
                        title = official['title'] if official else re.sub(r'\s+', ' ', ''.join(parser.title_parts)).strip()[:160]
                        source = text_source(text, title or name[:160])
                        warnings = []
                        if parser.has_media:
                            warnings.append('网页中的图片、音视频未自动读取，请按需要补上传原件')
                        if parser.attachments:
                            warnings.append('原文含外链附件，请核对并补上传关键附件')
                        origin = {'url': url, 'retrieved_at': int(time.time()), 'attachments': parser.attachments,
                                  'warnings': warnings}
                        if official:
                            origin.update({key: official[key] for key in ('title', 'published_at',
                                'published_at_precision', 'attachment_names', 'parser_id')})
                    else:
                        if mime == 'application/pdf' and not name.lower().endswith('.pdf'):
                            name += '.pdf'
                        if mime == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' and not name.lower().endswith('.docx'):
                            name += '.docx'
                        source = await run_in_threadpool(file_source, name, bytes(content))
                        title = PurePosixPath(source['name']).stem[:160]
                        origin = {'url': url, 'retrieved_at': int(time.time()), 'attachments': [],
                                  'warnings': [source['warning']] if source['warning'] else []}
                    if total_chars([source]) > MAX_CHARS:
                        raise HTTPException(422, f'链接正文超过 {MAX_CHARS:,} 字，请按事项拆分后粘贴或上传；未截断')
                    source['origin'] = origin
                    return source, title
            raise HTTPException(422, '链接跳转次数过多，请打开最终原文链接再试')
    except (httpx.HTTPError, OSError, ValueError, LookupError, TimeoutError):
        raise HTTPException(422, '链接读取失败，请粘贴原文或上传附件；已有内容未修改') from None


async def read_notice_materials(source, read=None):
    """Best-effort same-host PDF/DOCX intake; always retain the original text.

    Only an explicit subscription caller uses this helper. Link previews remain
    one exact snapshot and never recursively fetch attachments.
    """
    reader = read or read_link
    primary = {**source, 'origin': {**source.get('origin', {})}}
    origin = primary['origin']
    warnings = list(origin.get('warnings', []))
    origin['warnings'] = warnings
    materials, attempted, received = [primary], 0, []
    total_bytes = len(source.get('content') or b'')
    host = urlsplit(origin.get('url', '')).hostname
    names = origin.get('attachment_names', {})
    attachments = list(dict.fromkeys(origin.get('attachments', [])))
    if not host or not attachments:
        return materials

    def warn(message):
        if message not in warnings:
            warnings.append(message)

    try:
        async with asyncio.timeout(ATTACHMENT_READ_SECONDS):
            for url in attachments:
                label = names.get(url) or unquote(PurePosixPath(urlsplit(url).path).name) or '附件'
                supported = re.search(r'\.(pdf|docx)(?:[?#]|$)', url, re.I) or re.search(r'\.(pdf|docx)$', label, re.I)
                if not supported:
                    warn('部分附件格式暂不自动读取，请核对并补上传关键附件')
                    continue
                if not public_url(url) or urlsplit(url).hostname != host:
                    warn('部分附件不在通知来源域名内，未自动读取，请核对并补上传')
                    continue
                if attempted >= 4:
                    warn('每则通知最多自动读取 4 份附件，其余请核对并补上传')
                    break
                if total_bytes >= MAX_FILE or total_chars(materials) >= MAX_CHARS:
                    warn('正文与已收附件达到材料大小上限，剩余附件未读取，请拆分或补充关键内容')
                    break
                attempted += 1
                try:
                    if reader is read_link:
                        attachment, _ = await _read_link(url, allowed_host=host)
                    else:
                        attachment, _ = await reader(url)
                    if urlsplit(attachment.get('origin', {}).get('url', url)).hostname != host:
                        raise HTTPException(422, '附件跳转出了通知来源域名，未接收')
                    if attachment.get('kind') not in {'pdf', 'docx'}:
                        raise HTTPException(422, '返回内容不是可读取的 PDF/DOCX 附件')
                    size = len(attachment.get('content') or b'')
                    if total_bytes + size > MAX_FILE or total_chars(materials + [attachment]) > MAX_CHARS:
                        warn(f'{label}：加入后超过材料大小上限，主文已保留，请按事项拆分附件')
                        continue
                    materials.append(attachment)
                    total_bytes += size
                    received.append(url)
                    if attachment.get('status') != 'ok':
                        warn(f'{label}：{attachment.get("warning") or "附件未完整解析，请补充文字"}')
                except (HTTPException, OSError, ValueError, TimeoutError) as exc:
                    detail = str(exc.detail) if isinstance(exc, HTTPException) else '读取失败，请补上传原件'
                    warn(f'{label}：{detail}')
    except TimeoutError:
        warn('附件读取达到 25 秒上限，主文及已读取附件已保留，其余请核对并补上传')
    origin['received_attachments'] = received
    if len(received) == len(attachments):
        warnings[:] = [w for w in warnings if w != '原文含外链附件，请核对并补上传关键附件']
    return materials


def preview_source(conn, uid, preview_id):
    row = conn.execute('SELECT * FROM notice_link_previews WHERE id=? AND user_id=?', (preview_id, uid)).fetchone()
    if not row or row['expires_at'] < int(time.time()):
        raise HTTPException(409, '链接预览已过期或不可用，请重新读取链接；当前草稿仍保留')
    source = json.loads(row['data'])
    return {**source, 'id': ident(), 'content': row['content']}


def disposition(conn, nid):
    row = conn.execute('SELECT disposition,note,updated_at FROM notice_dispositions WHERE notice_id=?', (nid,)).fetchone()
    return dict(row) if row else {'disposition': 'inbox', 'note': '', 'updated_at': None}


def reopen(conn, nid):
    conn.execute('DELETE FROM notice_dispositions WHERE notice_id=?', (nid,))


def save_origin(conn, sid, source):
    if source.get('origin'):
        conn.execute('INSERT INTO notice_source_origins VALUES(?,?)', (sid, dumps(source['origin'])))


def submission_digest(values, fingerprint):
    keys = ('title', 'source_label', 'source_url', 'published_at', 'materials_complete', 'allow_duplicate')
    return hashlib.sha256(dumps({**{k: values.get(k, '') for k in keys}, 'fingerprint': fingerprint}).encode()).hexdigest()


def prior_submission(conn, uid, request_id, digest):
    if not request_id:
        return None
    if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_id):
        raise HTTPException(422, '提交标识无效，请重新打开通知录入页')
    row = conn.execute('SELECT * FROM notice_submissions WHERE user_id=? AND request_id=?', (uid, request_id)).fetchone()
    if not row:
        return None
    if row['digest'] != digest:
        raise HTTPException(409, {'message':'这次提交已经保存，但内容与当前草稿不同，请先核对已保存通知',
                                  'duplicate_id':row['notice_id'],'reason':'request_changed'})
    if row['notice_id'] is None:
        raise HTTPException(409, '这次提交的通知已被删除；需要重新录入时请另建草稿')
    return row['notice_id']


def require_open(conn, nid):
    if disposition(conn,nid)['disposition']!='inbox':
        raise HTTPException(409,'这则通知已处理，请先选择“重新处理”再整理行动')


def install(app, db, user, own_notice, expect_version, detailed_notice):
    @app.post('/api/intake/link')
    async def link_preview(payload: LinkRequest, current=Depends(user)):
        rate_limit(db, 'notice-link:' + current['id'], 20, 3600)
        source, title = await read_link(payload.url)
        pid, now = ident(), int(time.time())
        content = source.pop('content')
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM notice_link_previews WHERE expires_at<?', (now,))
            if conn.execute('SELECT count(*) FROM notice_link_previews WHERE user_id=?', (current['id'],)).fetchone()[0] >= 12:
                raise HTTPException(429, '待使用的链接预览较多，请先保存材料，或稍后再读取')
            conn.execute('INSERT INTO notice_link_previews VALUES(?,?,?,?,?)', (pid, current['id'], dumps(source), content, now + 3600))
        return {'id': pid, 'title': title, 'source': source, 'expires_at': now + 3600}

    @app.put('/api/notices/{nid}/disposition')
    def set_disposition(nid: str, payload: DispositionUpdate, current=Depends(user)):
        with db.connect(write=True) as conn:
            record = own_notice(conn, nid, current['id'])
            expect_version(record, payload.version)
            if record['status'] == 'processing':
                raise HTTPException(409, '通知正在整理，完成或停止后再更改处理方式')
            if payload.disposition != 'inbox' and conn.execute(
                    "SELECT 1 FROM tasks WHERE notice_id=? AND status='pending'", (nid,)).fetchone():
                raise HTTPException(422, '还有未完成事项，请先处理待办，再结束这则通知')
            before = disposition(conn, nid)
            now = int(time.time())
            conn.execute('INSERT INTO notice_dispositions VALUES(?,?,?,?) ON CONFLICT(notice_id) DO UPDATE SET disposition=excluded.disposition,note=excluded.note,updated_at=excluded.updated_at',
                         (nid, payload.disposition, payload.note, now))
            conn.execute('UPDATE notices SET version=version+1,updated_at=? WHERE id=?', (now, nid))
            # Existing draft evidence remains available, but confirmation requires
            # reopening/reprocessing this new version instead of a stale form.
            audit(conn, current['id'], nid, 'notice_disposition', before=before,
                  after={'disposition': payload.disposition, 'note': payload.note})
            return detailed_notice(conn, nid, current['id'])
