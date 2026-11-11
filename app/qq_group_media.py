"""Bounded attachment retrieval for signed, authorized QQ group events."""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import PurePosixPath
import re
import time
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx
from starlette.concurrency import run_in_threadpool

from .db import dumps, ident
from .documents import MAX_FILE, file_source
from .public_http import PublicHTTPTransport

MAX_FILES = 5
DOWNLOAD_WINDOW = 30*60
CACHE_WINDOW = 24*3600
LEASE_SECONDS = 8*60
FORMATS = {'pdf','doc','docx','txt','md','csv','xls','xlsx','png','jpg','jpeg','webp','mp4','webm'}
MIME_EXT = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
    'video/mp4': 'mp4', 'video/webm': 'webm', 'application/pdf': 'pdf',
    'text/plain': 'txt', 'text/markdown': 'md', 'text/csv': 'csv',
    'application/msword': 'doc', 'application/vnd.ms-excel': 'xls',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
}
TABLES = {'qq_group_attachment_batches', 'qq_group_attachment_files'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS qq_group_attachment_batches(
 id TEXT PRIMARY KEY,app_id TEXT NOT NULL,group_id TEXT NOT NULL,
 event_key TEXT NOT NULL,fingerprint TEXT NOT NULL,manifest TEXT NOT NULL,skipped INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','ready')),
 created_at INTEGER NOT NULL,finished_at INTEGER,lease_until INTEGER NOT NULL DEFAULT 0,token TEXT,
 note TEXT NOT NULL DEFAULT '',
 UNIQUE(app_id,group_id,event_key,fingerprint),
 FOREIGN KEY(app_id,group_id) REFERENCES qq_authorized_groups(app_id,group_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS qq_group_attachment_due ON qq_group_attachment_batches(app_id,state,created_at);
CREATE TABLE IF NOT EXISTS qq_group_attachment_files(
 batch_id TEXT NOT NULL REFERENCES qq_group_attachment_batches(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,content BLOB NOT NULL,
 sha256 TEXT NOT NULL,status TEXT NOT NULL,sections TEXT NOT NULL,warning TEXT NOT NULL,
 PRIMARY KEY(batch_id,position));
INSERT OR IGNORE INTO meta VALUES('qq_group_attachment_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='qq_group_attachment_schema_version'").fetchone()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('QQ 群附件队列版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


@dataclass
class AttachmentPlan:
    files: list[dict]
    skipped: int
    fingerprint: str

    @property
    def total(self):
        return len(self.files)+self.skipped


def media_url(value):
    if not isinstance(value, str) or not value or len(value)>4096 or any(ord(ch)<33 or ord(ch)==127 for ch in value):
        return None
    if value.startswith('//'):
        value = 'https:'+value
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        if (url.scheme!='https' or url.port not in (None,443) or url.username is not None or
                url.password is not None or url.fragment or not
                (host=='multimedia.nt.qq.com.cn' or host.endswith('.qpic.cn'))):
            return None
        return urlunsplit(('https', host, url.path or '/', url.query, ''))
    except ValueError:
        return None


def safe_name(value, mime, index):
    text = value if isinstance(value,str) else ''
    name = re.split(r'[/\\]', text)[-1]
    name = ''.join(ch for ch in name if not unicontrol(ch)).strip()
    suffix = PurePosixPath(name).suffix.lower().lstrip('.')
    if suffix not in FORMATS:
        ext = MIME_EXT.get(mime)
        if not ext or suffix:
            return None
        name = (name or f'QQ 附件 {index}')[:140]+'.'+ext
        suffix = ext
    return name[:150-len(suffix)-1]+'.'+suffix if len(name)>150 else name


def unicontrol(ch):
    return ord(ch)<32 or ord(ch)==127 or ch in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'


def inspect(attachments):
    files, identities, seen = [], [], set()
    skipped = 0
    for raw in attachments:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        url = media_url(raw.get('url'))
        mime = str(raw.get('content_type') or '').lower().split(';',1)[0].strip()
        try:
            size = max(0, int(raw.get('size') or 0))
        except (TypeError, ValueError, OverflowError):
            size = 0
        filename = raw.get('filename')
        name = safe_name(filename, mime, len(files)+1)
        if url:
            # The official CDN uses rkey for temporary access. Keep fileid,
            # size and type in the event identity without keeping that token.
            split = urlsplit(url)
            params = sorted((k,v) for k,v in parse_qsl(split.query,keep_blank_values=True) if k.casefold()!='rkey')
            identity_name = safe_name(filename,mime,0)
            key = hashlib.sha256(dumps([split.netloc,split.path,params,identity_name,mime,size]).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            identities.append(key)
        if url and name and size<=MAX_FILE and len(files)<MAX_FILES:
            files.append({'url':url,'name':name})
        else:
            skipped += 1
    signature = hashlib.sha256(dumps([sorted(identities),skipped]).encode()).hexdigest() if files or skipped else ''
    return AttachmentPlan(files,skipped,signature)


def skipped_note(count):
    return f'{count} 份附件的地址、类型、大小或数量超出自动读取范围，请补传原件。' if count else ''


def stage(conn, app_id, group_id, event_key, fingerprint, plan, now):
    conn.execute('''INSERT OR IGNORE INTO qq_group_attachment_batches
        (id,app_id,group_id,event_key,fingerprint,manifest,skipped,created_at) VALUES(?,?,?,?,?,?,?,?)''',
        (ident(),app_id,group_id,event_key,fingerprint,dumps(plan.files),plan.skipped,now))
    return conn.execute('''SELECT id FROM qq_group_attachment_batches
        WHERE app_id=? AND group_id=? AND event_key=? AND fingerprint=?''',
        (app_id,group_id,event_key,fingerprint)).fetchone()['id']


def refresh_manifest(conn, app_id, group_id, event_key, fingerprint, plan):
    # A reissued token for the same event can refresh a waiting job without
    # scheduling another download or touching an active lease.
    manifest = dumps(plan.files)
    conn.execute('''UPDATE qq_group_attachment_batches SET manifest=?
        WHERE app_id=? AND group_id=? AND event_key=? AND fingerprint=? AND state='queued' AND manifest<>?''',
        (manifest,app_id,group_id,event_key,fingerprint,manifest))


class AttachmentError(Exception):
    def __init__(self, message, *, retry=False):
        super().__init__(message)
        self.retry = retry


async def fetch_file(url):
    try:
        # The HTTPX client logs complete request URLs at INFO. Send through
        # the pinned transport so the signed attachment query stays private.
        timeout = httpx.Timeout(10,connect=5).as_dict()
        async with asyncio.timeout(15), PublicHTTPTransport() as transport:
            for _ in range(3):
                url = media_url(url)
                if not url:
                    raise AttachmentError('附件跳转出了 QQ 文件服务范围')
                request = httpx.Request('GET',url,headers={'User-Agent':'LuojiaNoticeReader/1.0','Accept-Encoding':'identity'},
                                        extensions={'timeout':timeout})
                response = await transport.handle_async_request(request)
                try:
                    if response.status_code in {301,302,303,307,308}:
                        url = urljoin(url,response.headers.get('location',''))
                        continue
                    if response.status_code in {401,403,404,410}:
                        raise AttachmentError('原件链接已失效或暂无下载权限')
                    if response.status_code!=200:
                        raise AttachmentError('QQ 文件服务暂未返回原件',
                                              retry=response.status_code==429 or response.status_code>=500)
                    if response.headers.get('content-type','').split(';',1)[0].strip().lower() in {'text/html','application/json'}:
                        raise AttachmentError('文件服务返回了网页或错误说明')
                    if response.headers.get('content-encoding','identity').strip().lower()!='identity':
                        raise AttachmentError('文件服务返回了不支持的传输编码')
                    length = response.headers.get('content-length','')
                    if length.isdecimal() and int(length)>MAX_FILE:
                        raise AttachmentError('原件超过 5 MB')
                    data = bytearray()
                    async for chunk in response.aiter_raw():
                        data.extend(chunk)
                        if len(data)>MAX_FILE:
                            raise AttachmentError('原件超过 5 MB')
                    if not data:
                        raise AttachmentError('文件服务返回空原件')
                    return bytes(data)
                finally:
                    await response.aclose()
            raise AttachmentError('QQ 文件服务跳转次数过多')
    except (httpx.HTTPError,TimeoutError,OSError,ValueError):
        raise AttachmentError('读取原件时连接中断',retry=True) from None


def prune(conn, now):
    # A subscriber's failure can retain shared bytes only while their
    # retry window is open. Revocation removes the last reference.
    conn.execute('''DELETE FROM qq_group_attachment_batches
        WHERE NOT EXISTS(SELECT 1 FROM qq_group_delivery_info i JOIN qq_group_deliveries d ON d.id=i.delivery_id
            WHERE i.media_id=qq_group_attachment_batches.id AND d.state IN ('pending','failed'))
        OR (state='ready' AND finished_at<?)''', (now-CACHE_WINDOW,))
    conn.execute("""UPDATE qq_group_attachment_batches SET state='ready',manifest='[]',finished_at=?,
        lease_until=0,token=NULL,note='原件下载窗口已结束，请从群里补传。'
        WHERE created_at<=? AND (state='queued' OR state='running' AND lease_until<=?)""",
        (now,now-DOWNLOAD_WINDOW,now))


def claim(db, app_id, now):
    with db.connect(write=True) as conn:
        prune(conn,now)
        row = conn.execute('''SELECT * FROM qq_group_attachment_batches
            WHERE app_id=? AND (state='queued' OR state='running' AND lease_until<=?)
            ORDER BY created_at,rowid LIMIT 1''', (app_id,now)).fetchone()
        if not row:
            return None
        token = ident()
        conn.execute("UPDATE qq_group_attachment_batches SET state='running',lease_until=?,token=? WHERE id=?",
                     (now+LEASE_SECONDS,token,row['id']))
        return {**dict(row),'token':token}


def authorized_batch(db, batch):
    with db.connect() as conn:
        return conn.execute('''SELECT 1 FROM qq_group_attachment_batches b
            JOIN qq_group_delivery_info i ON i.media_id=b.id JOIN qq_group_deliveries d ON d.id=i.delivery_id
            JOIN qq_group_subscriptions s ON s.user_id=d.user_id AND s.app_id=d.app_id AND s.group_id=d.group_id
            WHERE b.id=? AND b.token=? AND b.state='running' AND b.app_id=d.app_id AND b.group_id=d.group_id
            AND d.state IN ('pending','failed') LIMIT 1''',
            (batch['id'],batch['token'])).fetchone() is not None


def finish(db, batch, files, note, now):
    with db.connect(write=True) as conn:
        prune(conn,now)
        if not conn.execute("""UPDATE qq_group_attachment_batches SET state='ready',manifest='[]',
            finished_at=?,lease_until=0,token=NULL,note=? WHERE id=? AND token=? AND state='running'""",
            (now,note[:800],batch['id'],batch['token'])).rowcount:
            return False
        conn.executemany('''INSERT INTO qq_group_attachment_files VALUES(?,?,?,?,?,?,?,?,?)''', [
            (batch['id'],index,item['name'],item['kind'],item['content'],item['sha256'],item['status'],
             dumps(item['sections']),item['warning']) for index,item in enumerate(files)])
        return True


def load_files(conn, batch_id):
    return [{**dict(row),'sections':json.loads(row['sections'])} for row in conn.execute('''
        SELECT name,kind,content,sha256,status,sections,warning FROM qq_group_attachment_files
        WHERE batch_id=? ORDER BY position''', (batch_id,))]


async def retrieve(entry, db, batch):
    if not await run_in_threadpool(authorized_batch,db,batch):
        return None
    try:
        data = await fetch_file(entry['url'])
    except AttachmentError as error:
        if not error.retry:
            raise
        await asyncio.sleep(0.4)
        if not await run_in_threadpool(authorized_batch,db,batch):
            return None
        data = await fetch_file(entry['url'])
    if not await run_in_threadpool(authorized_batch,db,batch):
        return None
    try:
        return await run_in_threadpool(file_source,entry['name'],data)
    except ValueError:
        raise AttachmentError('原件格式无法保存') from None


async def run_one(db, app_id, *, now=None):
    start = int(time.time()) if now is None else now
    batch = await run_in_threadpool(claim,db,app_id,start)
    if not batch:
        return False
    files, notes = [], [skipped_note(batch['skipped'])] if batch['skipped'] else []
    for entry in json.loads(batch['manifest']):
        try:
            original = await retrieve(entry,db,batch)
            if original is None:
                return False
            files.append(original)
        except AttachmentError as error:
            notes.append(f'{entry["name"]}：{error}')
    return await run_in_threadpool(finish,db,batch,files,'；'.join(notes),int(time.time()) if now is None else now)


async def run_worker(db, settings):
    from .group_delivery import tick
    while True:
        try:
            if settings.qq_bot_app_id and settings.qq_bot_secret and await run_one(db,settings.qq_bot_app_id):
                await run_in_threadpool(tick,db,settings.qq_bot_app_id)
                await asyncio.sleep(0)
                continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('campus').error('qq_group_attachments_worker_failed')
        await asyncio.sleep(5)
