"""Owner-authorized public source subscriptions; durable cursors, no model calls."""
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import logging
import time
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx
from fastapi import Depends, HTTPException
from pydantic import Field, field_validator, model_validator

from .db import dumps, ident
from .evidence_web import decode_page, public_url
from .models import Strict
from .notice_intake import read_link
from .official_sources import PRESETS, get_preset, parse_official_index
from .public_http import PublicHTTPTransport
from .security import rate_limit

POLL_SECONDS = 30
MAX_CONCURRENT_SOURCES = 2
TABLES = {'source_subscriptions', 'source_subscription_items'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS source_subscriptions(
 source_id TEXT PRIMARY KEY REFERENCES source_catalog(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 config TEXT NOT NULL, enabled INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 next_poll INTEGER NOT NULL DEFAULT 0, running_until INTEGER NOT NULL DEFAULT 0,
 checked_at INTEGER, succeeded_at INTEGER, error TEXT NOT NULL DEFAULT '',
 received_count INTEGER NOT NULL DEFAULT 0, updated_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS source_subscription_items(
 source_id TEXT NOT NULL REFERENCES source_subscriptions(source_id) ON DELETE CASCADE,
 url TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT, discovered_at INTEGER NOT NULL,
 checked_at INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(source_id,url));
CREATE INDEX IF NOT EXISTS source_subscriptions_due ON source_subscriptions(enabled,next_poll);
INSERT OR IGNORE INTO meta VALUES('source_sync_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='source_sync_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('来源订阅记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


class Subscription(Strict):
    version: int = Field(default=0, ge=0)
    enabled: bool = True
    mode: Literal['html', 'feed'] = 'html'
    url: str = Field(min_length=1, max_length=2000)
    article_path_prefix: str = Field(default='', max_length=300)
    interval_minutes: int = Field(default=30, ge=5, le=1440)
    preset_id: str = Field(default='', max_length=80)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if not public_url(value):
            raise ValueError('请输入公开的通知列表或 RSS/Atom 地址')
        return value

    @model_validator(mode='after')
    def bounded_scope(self):
        if self.preset_id:
            preset = get_preset(self.preset_id)
            if (not preset or self.mode != 'html' or canonical_url(self.url) != canonical_url(preset['url'])
                    or self.article_path_prefix != preset['article_path_prefix']):
                raise ValueError('预设栏目范围已改变，请重新选择学校官网或使用自定义来源')
        if self.mode == 'html' and (not self.article_path_prefix.startswith('/') or
                len(self.article_path_prefix) < 2 or any(x in self.article_path_prefix for x in ('?', '#', '..', '\\'))):
            raise ValueError('网页订阅须填写通知正文的路径前缀，例如 /info/；不能订阅整站所有链接')
        return self


def canonical_url(value):
    safe = public_url(value)
    if not safe:
        return None
    parts = urlsplit(safe)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or '/', parts.query, ''))


class ListLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.href, self.parts, self.depth = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href, self.parts = dict(attrs).get('href'), []

    def handle_data(self, value):
        if self.href is not None:
            self.parts.append(value)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((self.href, ' '.join(''.join(self.parts).split())))
            self.href = None


def parse_index(text, url, config):
    """Only links on the subscribed host; no crawl traversal or inferred dates."""
    if config.get('preset_id'):
        return parse_official_index(text, url, config['preset_id'])
    candidates = []
    if config['mode'] == 'feed':
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise HTTPException(422, '订阅源含不支持的 XML 声明')
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise HTTPException(422, '订阅地址未返回有效 RSS/Atom') from None
        for entry in root.iter():
            if entry.tag.split('}')[-1] not in {'item', 'entry'}:
                continue
            values = {node.tag.split('}')[-1]: node for node in entry}
            title = ''.join(values['title'].itertext()).strip() if 'title' in values else ''
            link = values.get('link')
            href = (link.get('href') or link.text or '') if link is not None else ''
            date_node = values.get('pubDate')
            if date_node is None:
                date_node = values.get('published')
            published = None
            if date_node is not None and date_node.text:
                try:
                    parsed = parsedate_to_datetime(date_node.text) if 'pubDate' in values else datetime.fromisoformat(date_node.text.replace('Z', '+00:00'))
                    if parsed.tzinfo:
                        published = parsed.astimezone(timezone.utc).isoformat()
                except (ValueError, TypeError, OverflowError):
                    pass
            candidates.append((href, title, published))
    else:
        parser = ListLinks()
        parser.feed(text)
        candidates = [(href, title, None) for href, title in parser.links
                      if urlsplit(urljoin(url, href)).path.startswith(config['article_path_prefix'])]
    result, seen = [], set()
    for href, title, published in candidates:
        target = canonical_url(urljoin(url, href))
        if not target or target in seen or target == canonical_url(url) or urlsplit(target).hostname != urlsplit(config['url']).hostname:
            continue
        if not title:
            continue
        seen.add(target)
        result.append({'url': target, 'title': title[:160], 'published_at': published})
    if len(result) > 200:
        raise HTTPException(422, '列表超过 200 条正文链接，请使用更具体的栏目或订阅源')
    if not result:
        raise HTTPException(422, '没有找到符合范围的通知正文，请核对列表地址与正文路径前缀')
    return result


async def fetch_index(config):
    url = config['url']
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(transport=PublicHTTPTransport(), trust_env=False,
                follow_redirects=False, timeout=httpx.Timeout(15, connect=5)) as client:
            for _ in range(4):
                if not public_url(url) or urlsplit(url).hostname != urlsplit(config['url']).hostname:
                    raise HTTPException(422, '订阅列表跳转出了授权的来源域名')
                async with client.stream('GET', url, headers={'User-Agent': 'LuojiaNoticeReader/1.0'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    if response.status_code != 200:
                        raise HTTPException(502, f'来源返回 HTTP {response.status_code}，本次未完成同步')
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 1_500_000:
                            raise HTTPException(413, '来源列表过大，请选择具体通知栏目')
                    text, _ = decode_page(content, response.charset_encoding)
                    return parse_index(text, url, config)
            raise HTTPException(422, '来源跳转次数过多')
    except (httpx.HTTPError, OSError, TimeoutError, ValueError, LookupError):
        raise HTTPException(502, '来源连接失败，将按订阅间隔重试；已有通知保留') from None


def owned(conn, sid, uid):
    row = conn.execute('SELECT * FROM source_catalog WHERE id=? AND user_id=?', (sid, uid)).fetchone()
    if not row:
        raise HTTPException(404, '来源不存在或无权访问')
    return row


def status(conn, sid, uid):
    owned(conn, sid, uid)
    row = conn.execute('SELECT * FROM source_subscriptions WHERE source_id=? AND user_id=?', (sid, uid)).fetchone()
    if not row:
        return {'source_id': sid, 'enabled': False, 'state': 'manual', 'error': ''}
    result = dict(row)
    result['config'] = json.loads(result['config'])
    result['enabled'] = bool(result['enabled'])
    result['state'] = 'paused' if not result['enabled'] else 'syncing' if result['running_until'] > time.time() else 'error' if result['error'] else 'active' if result['succeeded_at'] else 'waiting'
    result['pending_count'] = conn.execute('SELECT count(*) FROM source_subscription_items WHERE source_id=? AND checked_at=0', (sid,)).fetchone()[0]
    return result


def retry_delay(snapshot,config,*,pending,failed):
    base=config['interval_minutes']*60
    if not failed:return 60 if pending else base
    previous=max(base,(snapshot.get('next_poll') or 0)-(snapshot.get('checked_at') or 0))
    return min(base*8,previous*2) if snapshot.get('error') else base


async def sync_source(db, sid, uid=None, force=False):
    from .notice_ingest import ingest_notice
    now = int(time.time())
    with db.connect(write=True) as conn:
        row = conn.execute('SELECT s.*,c.data AS catalog,c.version AS catalog_version FROM source_subscriptions s JOIN source_catalog c ON c.id=s.source_id WHERE s.source_id=?', (sid,)).fetchone()
        if not row or (uid and row['user_id'] != uid):
            raise HTTPException(404, '订阅不存在')
        if not row['enabled']:
            raise HTTPException(409, '订阅已暂停')
        if row['running_until'] > now or (not force and row['next_poll'] > now):
            return status(conn, sid, row['user_id'])
        snapshot = dict(row)
        conn.execute('UPDATE source_subscriptions SET running_until=?,checked_at=? WHERE source_id=?', (now + 300, now, sid))
    config, catalog = json.loads(snapshot['config']), json.loads(snapshot['catalog'])
    if catalog['platform'] != 'website' or urlsplit(catalog.get('url','')).hostname != urlsplit(config['url']).hostname:
        with db.connect(write=True) as conn:
            conn.execute("UPDATE source_subscriptions SET enabled=0,running_until=0,error='来源已改变，请重新确认订阅范围' WHERE source_id=?",(sid,))
            return status(conn,sid,snapshot['user_id'])
    errors, created, updated = [], 0, 0
    index_succeeded=False
    def unchanged(conn):
        return conn.execute('SELECT 1 FROM source_subscriptions s JOIN source_catalog c ON c.id=s.source_id WHERE s.source_id=? AND s.enabled=1 AND s.version=? AND c.version=?', (sid, snapshot['version'],snapshot['catalog_version'])).fetchone()
    try:
        entries = await fetch_index(config)
        index_succeeded=True
        with db.connect(write=True) as conn:
            if not unchanged(conn):
                return None
            if not conn.execute('SELECT 1 FROM source_baseline_runs WHERE source_id=?',(sid,)).fetchone():
                conn.executemany('INSERT OR IGNORE INTO source_baseline_items VALUES(?,?)',[(sid,e['url']) for e in entries])
                conn.execute('INSERT INTO source_baseline_runs VALUES(?,?)',(sid,now))
            for entry in entries:
                conn.execute('INSERT INTO source_subscription_items(source_id,url,title,published_at,discovered_at) VALUES(?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET title=excluded.title,published_at=COALESCE(excluded.published_at,source_subscription_items.published_at)',
                             (sid, entry['url'], entry['title'], entry['published_at'], now))
            # Retain discovered backlog across polls. Recent known pages are also
            # revisited so a correction at an existing URL is detected.
            pending = [dict(r) for r in conn.execute('SELECT * FROM source_subscription_items WHERE source_id=? ORDER BY checked_at,discovered_at DESC LIMIT 8', (sid,))]
        for item in pending:
            try:
                with db.connect(write=True) as conn:
                    if not unchanged(conn):
                        return None
                    conn.execute('UPDATE source_subscriptions SET running_until=? WHERE source_id=?',
                                 (int(time.time()) + 300, sid))
                source, _ = await read_link(item['url'])
                if urlsplit(source.get('origin', {}).get('url', item['url'])).hostname != urlsplit(config['url']).hostname:
                    raise HTTPException(422, '正文跳转出了订阅来源域名')
                article_date = source.get('origin', {}).get('published_at')
                if article_date and item['published_at'] and article_date[:10] != item['published_at'][:10]:
                    source['origin']['listed_published_at'] = item['published_at']
                    source['origin'].setdefault('warnings', []).append(
                        f"列表日期 {item['published_at'][:10]} 与正文日期 {article_date[:10]} 不同，已保留两者并采用正文日期，请核对原文")
                from .notice_network import read_network,retain_unavailable
                materials = await read_network(source,config,entries,read=read_link)
                published = article_date or item['published_at']
                with db.connect(write=True) as conn:
                    if not unchanged(conn):
                        return None
                    key='website:'+sid+':'+item['url']
                    materials=retain_unavailable(conn,snapshot['user_id'],key,materials)
                    result = ingest_notice(conn, snapshot['user_id'], title=source.get('origin',{}).get('title') or item['title'], sources=materials,
                        source_label=catalog['name'], source_url=item['url'], published_at=published,
                        external_key='website:' + sid + ':' + item['url'], materials_complete=False,observed_at=time.time())
                    created += bool(result.get('created'))
                    if result.get('created') and conn.execute('SELECT 1 FROM source_baseline_items WHERE source_id=? AND url=?',(sid,item['url'])).fetchone():
                        conn.execute('INSERT OR IGNORE INTO notice_delivery_suppressions VALUES(?,?)',(result['notice_id'],'initial_website_snapshot'))
                    updated += bool(result.get('updated'))
                    origin=materials[0].get('origin',{})
                    from .source_coverage import coverage
                    incomplete=any(coverage(material)['reading_incomplete'] for material in materials)
                    article_error='部分附件或关联内容未完整复查；已有正文和旧证据已保留' if incomplete else ''
                    if article_error:errors.append(article_error)
                    conn.execute('UPDATE source_subscription_items SET checked_at=?,error=? WHERE source_id=? AND url=?', (int(time.time()), article_error, sid, item['url']))
            except HTTPException as exc:
                errors.append(str(exc.detail))
                with db.connect(write=True) as conn:
                    conn.execute('UPDATE source_subscription_items SET checked_at=?,error=? WHERE source_id=? AND url=?', (int(time.time()), str(exc.detail)[:500], sid, item['url']))
    except asyncio.CancelledError:
        errors.append('同步被中断，下次检查会继续；已保存通知保留')
        raise
    except HTTPException as exc:
        errors.append(str(exc.detail))
    except Exception:
        logging.getLogger('campus').exception('source_sync_failed')
        errors.append('同步发生错误，将稍后重试；已保存通知保留')
    finally:
        with db.connect(write=True) as conn:
            if unchanged(conn):
                pending_count = conn.execute('SELECT count(*) FROM source_subscription_items WHERE source_id=? AND checked_at=0', (sid,)).fetchone()[0]
                failed_count=conn.execute("SELECT count(*) FROM source_subscription_items WHERE source_id=? AND error<>''",(sid,)).fetchone()[0]
                if failed_count:errors.append(f'{failed_count} 篇正文仍未成功读取，请在来源状态中核对')
                # An old login-restricted article must not progressively defer
                # discovery of NEW public notices for the entire column.
                # Retain its visible failure, while the successful index keeps
                # its ordinary interval (or drains undiscovered articles).
                delay = retry_delay(snapshot,config,pending=bool(pending_count),failed=bool(errors) and not index_succeeded)
                conn.execute('UPDATE source_subscriptions SET running_until=0,next_poll=?,error=?,succeeded_at=CASE WHEN ? THEN succeeded_at ELSE ? END,received_count=received_count+?,updated_count=updated_count+? WHERE source_id=?',
                             (int(time.time()) + delay, '；'.join(dict.fromkeys(errors))[:1000], bool(errors), int(time.time()), created, updated, sid))
            else:
                conn.execute("UPDATE source_subscriptions SET enabled=0,running_until=0,error='来源设置已变化，请重新确认订阅' WHERE source_id=? AND version=?",(sid,snapshot['version']))
    with db.connect() as conn:
        return status(conn, sid, snapshot['user_id']) if conn.execute('SELECT 1 FROM source_catalog WHERE id=?', (sid,)).fetchone() else None


async def poll_batch(db,rows):
    """A free worker starts the next source immediately; failures stay scoped."""
    slots=asyncio.Semaphore(MAX_CONCURRENT_SOURCES)
    async def poll(sid):
        async with slots:
            try:await sync_source(db,sid)
            except HTTPException:
                # A source can be removed or paused after the due list is read.
                logging.getLogger('campus').info('source_subscription_changed_during_poll')
    async with asyncio.TaskGroup() as tasks:
        for row in rows:tasks.create_task(poll(row['source_id']))


async def run_worker(db, settings=None):
    from starlette.concurrency import run_in_threadpool
    from .integrations import PublisherClient
    from .publisher_sync import sync_due
    publisher=PublisherClient(settings) if settings else None
    while True:
        try:
            if publisher:
                await run_in_threadpool(sync_due,db,publisher)
            with db.connect() as conn:
                rows = conn.execute('SELECT source_id FROM source_subscriptions WHERE enabled=1 AND next_poll<=? AND running_until<=? ORDER BY next_poll LIMIT 8', (int(time.time()), int(time.time()))).fetchall()
            await poll_batch(db,rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('campus').error('source_subscription_worker_failed')
        await asyncio.sleep(POLL_SECONDS)


def install(app, db, user):
    @app.get('/api/source-presets')
    def presets(current=Depends(user)):
        return PRESETS

    @app.post('/api/source-presets/{preset_id}/subscribe')
    def subscribe_preset(preset_id: str, current=Depends(user)):
        from .usage_limits import check_count
        from .workspace import CatalogItem
        preset = get_preset(preset_id)
        if not preset:
            raise HTTPException(404, '此学校栏目不存在，请重新选择')
        # Source and subscription are saved together. Repeated requests reuse the
        # same owner-scoped source and never resume an explicitly paused one.
        with db.connect(write=True) as conn:
            sid = None
            for row in conn.execute('SELECT id,data FROM source_catalog WHERE user_id=? ORDER BY created_at,rowid', (current['id'],)):
                catalog = json.loads(row['data'])
                if catalog.get('platform') == 'website' and canonical_url(catalog.get('url', '')) == canonical_url(preset['url']):
                    sid = row['id']
                    break
            created = sid is None
            if created:
                check_count(conn, current['id'], 'source_catalog', 'sources', '来源')
                catalog = CatalogItem(name=preset['name'], platform='website', url=preset['url'],
                                      institution=preset['institution'], purpose=preset['purpose'])
                sid, now = ident(), int(time.time())
                conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,?,?)',
                             (sid, current['id'], catalog.model_dump_json(), now, now))
            previous = conn.execute('SELECT source_id FROM source_subscriptions WHERE source_id=?', (sid,)).fetchone()
            if not previous:
                config = Subscription(url=preset['url'], article_path_prefix=preset['article_path_prefix'],
                                      preset_id=preset_id).model_dump(exclude={'enabled', 'version'})
                conn.execute('INSERT INTO source_subscriptions(source_id,user_id,config,enabled) VALUES(?,?,?,1)',
                             (sid, current['id'], dumps(config)))
            return {'source_id': sid, 'created': created, 'subscription': status(conn, sid, current['id'])}

    @app.get('/api/source-subscriptions')
    def subscriptions(current=Depends(user)):
        with db.connect() as conn:
            return [status(conn, row['id'], current['id']) for row in conn.execute('SELECT id FROM source_catalog WHERE user_id=?', (current['id'],))]

    @app.put('/api/source-catalog/{sid}/subscription')
    def configure(sid: str, payload: Subscription, current=Depends(user)):
        with db.connect(write=True) as conn:
            catalog = json.loads(owned(conn, sid, current['id'])['data'])
            if catalog['platform'] != 'website':
                raise HTTPException(422, '仅公开网站使用网页订阅；公众号和群需要各自的平台授权')
            if not public_url(catalog.get('url', '')) or urlsplit(payload.url).hostname != urlsplit(catalog['url']).hostname:
                raise HTTPException(422, '订阅地址须属于所登记网站的同一域名')
            config = payload.model_dump(exclude={'enabled','version'})
            previous = conn.execute('SELECT config,version FROM source_subscriptions WHERE source_id=?', (sid,)).fetchone()
            if payload.version != (previous['version'] if previous else 0):
                raise HTTPException(409,'订阅设置已在另一处修改，请刷新后再保存')
            if previous and json.loads(previous['config']) != config:
                conn.execute('DELETE FROM source_subscription_items WHERE source_id=?', (sid,))
            conn.execute('INSERT INTO source_subscriptions(source_id,user_id,config,enabled) VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET config=excluded.config,enabled=excluded.enabled,version=version+1,next_poll=0,running_until=0,error=\'\'',
                         (sid, current['id'], dumps(config), payload.enabled))
            return status(conn, sid, current['id'])

    @app.post('/api/source-catalog/{sid}/refresh')
    async def refresh(sid: str, current=Depends(user)):
        rate_limit(db, 'source-refresh:' + current['id'], 20, 3600)
        with db.connect() as conn:
            owned(conn, sid, current['id'])
        return await sync_source(db, sid, current['id'], force=True)
