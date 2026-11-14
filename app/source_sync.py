"""Owner-authorized public source subscriptions; durable cursors, no model calls."""
import asyncio
import hashlib
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
from .source_fetch import acquisition,allowed,origin,transport

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
OBSERVATION_TABLES={'source_acquisition_runs','source_rule_versions','source_rule_trials','source_entry_provenance'}
OBSERVATION_SCHEMA="""
CREATE TABLE IF NOT EXISTS source_acquisition_runs(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE CASCADE,
 rule_version INTEGER NOT NULL, config_hash TEXT NOT NULL, started_at INTEGER NOT NULL,
 finished_at INTEGER, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS source_acquisition_latest ON source_acquisition_runs(source_id,started_at);
CREATE TABLE IF NOT EXISTS source_rule_versions(
 source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, config TEXT NOT NULL, saved_at INTEGER NOT NULL,
 PRIMARY KEY(source_id,version));
CREATE TABLE IF NOT EXISTS source_rule_trials(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, config TEXT NOT NULL, data TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_entry_provenance(
 source_id TEXT NOT NULL REFERENCES source_catalog(id) ON DELETE CASCADE,
 url TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(source_id,url));
INSERT OR IGNORE INTO meta VALUES('source_observation_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='source_sync_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('来源订阅记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)
    from .source_fetch import initialize as init_fetch
    init_fetch(conn)
    observation_version=conn.execute("SELECT value FROM meta WHERE key='source_observation_schema_version'").fetchone()
    if observation_version and (observation_version[0]!='1' or not OBSERVATION_TABLES.issubset(tables)):
        # tables was captured before first-time schema installation, but an
        # existing marker requires all of its historical receipts to exist.
        raise ValueError('来源实读回执版本不兼容或缺少必要数据表')
    conn.executescript(OBSERVATION_SCHEMA)


class Subscription(Strict):
    version: int = Field(default=0, ge=0)
    enabled: bool = True
    mode: Literal['html', 'feed'] = 'html'
    url: str = Field(min_length=1, max_length=2000)
    article_path_prefix: str = Field(default='', max_length=300)
    interval_minutes: int = Field(default=30, ge=5, le=1440)
    preset_id: str = Field(default='', max_length=80)
    # Feed service and original publisher are separate trust boundaries. Empty
    # scope keeps the existing same-host behavior for old subscriptions.
    allowed_article_origins: list[str] = Field(default_factory=list,max_length=20)
    source_identity: str = Field(default='',max_length=160)

    @field_validator('allowed_article_origins')
    @classmethod
    def valid_origins(cls,values):
        result=[]
        for value in values:
            parsed=urlsplit(value)
            normalized=origin(value)
            if not normalized or '*' in value or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
                raise ValueError('允许原文来源须为明确的公网 http(s) origin，例如 https://rsgis.whu.edu.cn；不支持通配符')
            if normalized not in result:result.append(normalized)
        return result

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if not public_url(value):
            raise ValueError('请输入公开的通知列表或 RSS/Atom 地址')
        return value

    @model_validator(mode='after')
    def bounded_scope(self):
        if self.mode!='feed' and self.allowed_article_origins:
            raise ValueError('跨来源授权仅用于已明确来源的 RSS/Atom；网页采集保持同域范围')
        if self.allowed_article_origins and not self.source_identity.strip():
            raise ValueError('请明确填写真实发布方，Feed服务名称不能代替发布方')
        if self.preset_id:
            preset = get_preset(self.preset_id)
            if (not preset or self.mode != 'html' or canonical_url(self.url) != canonical_url(preset['url'])
                    or self.article_path_prefix != preset['article_path_prefix']):
                raise ValueError('预设栏目范围已改变，请重新选择学校官网或使用自定义来源')
        if self.mode == 'html' and (not self.article_path_prefix.startswith('/') or
                len(self.article_path_prefix) < 2 or any(x in self.article_path_prefix for x in ('?', '#', '..', '\\'))):
            raise ValueError('网页订阅须填写通知正文的路径前缀，例如 /info/；不能订阅整站所有链接')
        return self


def article_scope(config):
    origins=(config.get('allowed_article_origins') or []) if config.get('mode','html')=='feed' else []
    return (origins,[]) if origins else ([],[urlsplit(config['url']).hostname])


def article_allowed(url,config):
    origins,hosts=article_scope(config)
    return allowed(url,origins,hosts)


def catalog_matches(catalog,config):
    if catalog.get('platform')!='website' or not public_url(catalog.get('url','')):return False
    if config['mode']=='feed' and config.get('allowed_article_origins'):
        return origin(catalog['url']) in config['allowed_article_origins'] and bool(config.get('source_identity','').strip())
    return urlsplit(catalog['url']).hostname==urlsplit(config['url']).hostname


class IndexEntries(list):
    def __init__(self,entries=(),*,rejected=(),empty_confirmed=False):
        super().__init__(entries)
        self.rejected=list(rejected)
        self.empty_confirmed=empty_confirmed
        self.snapshot={}


class RuleApply(Strict):
    version:int=Field(ge=0)
    trial_id:str=Field(min_length=1,max_length=100)
    enabled:bool=True


class RuleRollback(Strict):
    version:int=Field(ge=1)
    restore_version:int=Field(ge=1)


async def trial_rule(db,sid,uid,config,version):
    """Read in isolation; never ingest personal notices or send notifications."""
    from .source_coverage import coverage
    result={'can_apply':False,'list':{},'articles':[],'errors':[]}
    try:
        with acquisition(db,config,hosts=[urlsplit(config['url']).hostname],max_bytes=1_500_000):
            entries=await fetch_index(config)
        result['list']={'count':len(entries),'snapshot':getattr(entries,'snapshot',{}),
            'empty_confirmed':getattr(entries,'empty_confirmed',False),'rejected_entries':getattr(entries,'rejected',[])}
        origins,hosts=article_scope(config)
        for entry in entries[:2]:
            with acquisition(db,config,origins=origins,hosts=hosts):
                source,_=await read_link(entry['url'])
            if not article_allowed(source.get('origin',{}).get('url',entry['url']),config):
                raise HTTPException(422,'试读正文超出授权范围')
            result['articles'].append({'url':entry['url'],'title':source.get('origin',{}).get('title') or entry['title'],
                'sha256':source['sha256'],'status':source['status'],'coverage':coverage(source)})
        result['can_apply']=bool(result['articles']) and all(x['status']=='ok' for x in result['articles'])
        if not result['articles']:result['errors'].append('栏目确认为空，但尚无正文样本验证此规则；暂不安装新规则')
    except HTTPException as exc:result['errors'].append(str(exc.detail))
    trial_id=ident()
    with db.connect(write=True) as conn:
        owned(conn,sid,uid)
        conn.execute('INSERT INTO source_rule_trials VALUES(?,?,?,?,?,?)',(trial_id,sid,version,dumps(config),dumps(result),int(time.time())))
        conn.execute('DELETE FROM source_rule_trials WHERE source_id=? AND id NOT IN (SELECT id FROM source_rule_trials WHERE source_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20)',(sid,sid))
    return {'trial_id':trial_id,'version':version,'config':config,**result}


def apply_trial(conn,sid,uid,payload):
    catalog=json.loads(owned(conn,sid,uid)['data'])
    previous=conn.execute('SELECT * FROM source_subscriptions WHERE source_id=? AND user_id=?',(sid,uid)).fetchone()
    trial=conn.execute('SELECT * FROM source_rule_trials WHERE id=? AND source_id=?',(payload.trial_id,sid)).fetchone()
    if payload.version!=(previous['version'] if previous else 0):
        if (previous and trial and previous['version']==payload.version+1 and trial['version']==payload.version
                and previous['config']==trial['config'] and bool(previous['enabled'])==payload.enabled
                and verified_config(conn,sid,json.loads(trial['config']),applied_version=previous['version'],trial_version=payload.version)):
            return status(conn,sid,uid)
        raise HTTPException(409,'订阅规则已变化，请重新试读')
    if not trial or trial['version']!=payload.version or trial['created_at']<int(time.time())-3600:
        raise HTTPException(409,'试读回执不存在、已过期或不对应当前规则版本')
    config=json.loads(trial['config'])
    if not json.loads(trial['data'])['can_apply']:
        errors=json.loads(trial['data']).get('errors') or ['正文样本仍需人工核对']
        raise HTTPException(422,'规则试读未通过，现有订阅保持不变：'+'；'.join(errors)[:800])
    if not catalog_matches(catalog,config):raise HTTPException(409,'来源授权已变化，请重新核对')
    now=int(time.time())
    if previous:
        conn.execute('INSERT OR IGNORE INTO source_rule_versions VALUES(?,?,?,?)',(sid,previous['version'],previous['config'],now))
        conn.execute('DELETE FROM source_subscription_items WHERE source_id=?',(sid,))
    conn.execute('INSERT INTO source_subscriptions(source_id,user_id,config,enabled) VALUES(?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET config=excluded.config,enabled=excluded.enabled,version=version+1,next_poll=0,running_until=0,error=\'\'',(sid,uid,dumps(config),payload.enabled))
    current=status(conn,sid,uid)
    conn.execute('INSERT INTO source_rule_versions VALUES(?,?,?,?)',(sid,current['version'],dumps(config),now))
    # Source rule history has its own source-scoped receipt; the notice audit
    # table requires a real notice and must not be populated with a fake id.
    applied={**json.loads(trial['data']),'applied_at':now,'applied_version':current['version']}
    conn.execute('UPDATE source_rule_trials SET data=? WHERE id=?',(dumps(applied),trial['id']))
    return current


def same_config(left,right):
    # Empty fields added by later additive versions do not turn a pause into a
    # rule edit. All actual authorization and parser fields still compare.
    try:return Subscription.model_validate(left).model_dump(exclude={'enabled','version'})==right
    except ValueError:return False


def verified_config(conn,sid,config,*,applied_version=None,trial_version=None):
    for row in conn.execute('SELECT * FROM source_rule_trials WHERE source_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20',(sid,)):
        data=json.loads(row['data'])
        if (data.get('can_apply') and data.get('applied_version') and same_config(json.loads(row['config']),config)
                and (applied_version is None or data['applied_version']==applied_version)
                and (trial_version is None or row['version']==trial_version)):
            return True
    return False


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
    """Only explicitly authorized originals; feed service never implies trust."""
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
        if root.tag.split('}')[-1] not in {'rss','feed','RDF'}:
            raise HTTPException(422,'订阅地址不是受支持的RSS/Atom文档')
        for entry in root.iter():
            if entry.tag.split('}')[-1] not in {'item', 'entry'}:
                continue
            values = {node.tag.split('}')[-1]: node for node in entry}
            title = ''.join(values['title'].itertext()).strip() if 'title' in values else ''
            links=[node for node in entry if node.tag.split('}')[-1]=='link']
            link = next((node for node in links if node.get('rel','alternate')=='alternate'),None)
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
            external_id=values.get('guid')
            if external_id is None:external_id=values.get('id')
            candidates.append((href, title, published,(external_id.text or '').strip()[:1000] if external_id is not None else ''))
    else:
        parser = ListLinks()
        parser.feed(text)
        candidates = [(href, title, None,'') for href, title in parser.links
                      if urlsplit(urljoin(url, href)).path.startswith(config['article_path_prefix'])]
    result, seen = IndexEntries(empty_confirmed=config['mode']=='feed' and not candidates), set()
    for href, title, published, external_id in candidates:
        target = canonical_url(urljoin(url, href))
        if not target or not article_allowed(target,config):
            result.rejected.append({'url':target or str(href)[:2000],'reason':'原文地址不在已授权公网来源中'})
            continue
        if target in seen or target == canonical_url(url):
            continue
        if not title:
            continue
        seen.add(target)
        item={'url': target, 'title': title[:160], 'published_at': published}
        if external_id:item['feed_entry_id']=external_id
        result.append(item)
    if len(result) > 200:
        raise HTTPException(422, '列表超过 200 条正文链接，请使用更具体的栏目或订阅源')
    if not result and not result.empty_confirmed:
        reason='；订阅中含未授权原文地址' if result.rejected else ''
        raise HTTPException(422, '没有找到符合范围的通知正文，请核对列表地址与正文路径前缀'+reason)
    return result


async def fetch_index(config):
    url = config['url']
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(transport=transport(PublicHTTPTransport), trust_env=False,
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
                    entries=parse_index(text, url, config)
                    if not isinstance(entries,IndexEntries):entries=IndexEntries(entries)
                    entries.snapshot={'url':url,'sha256':hashlib.sha256(content).hexdigest(),
                        'checked_at':int(time.time()),'acquisition':response.headers.get('x-luojia-cache','fetched')}
                    return entries
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
        trial=conn.execute('SELECT id,data,created_at FROM source_rule_trials WHERE source_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(sid,)).fetchone()
        latest={**dict(trial),'data':json.loads(trial['data'])} if trial else None
        return {'source_id':sid,'enabled':False,'state':'manual','error':('；'.join(latest['data'].get('errors') or ['样本尚待核对']) if latest and not latest['data'].get('can_apply') else ''),
            'last_trial':latest,'checked_at':trial['created_at'] if trial else None}
    result = dict(row)
    result['config'] = json.loads(result['config'])
    result['enabled'] = bool(result['enabled'])
    result['state'] = 'paused' if not result['enabled'] else 'syncing' if result['running_until'] > time.time() else 'error' if result['error'] else 'active' if result['succeeded_at'] else 'waiting'
    result['pending_count'] = conn.execute('SELECT count(*) FROM source_subscription_items WHERE source_id=? AND checked_at=0', (sid,)).fetchone()[0]
    result['feed_service_url']=result['config']['url'] if result['config']['mode']=='feed' else None
    result['allowed_article_origins']=result['config'].get('allowed_article_origins') or [origin(result['config']['url'])]
    result['source_identity']=result['config'].get('source_identity','')
    run=conn.execute('SELECT * FROM source_acquisition_runs WHERE source_id=? ORDER BY started_at DESC,rowid DESC LIMIT 1',(sid,)).fetchone()
    result['coverage']=({**json.loads(run['data']),'run_id':run['id'],'rule_version':run['rule_version'],
        'config_hash':run['config_hash'],'started_at':run['started_at'],'finished_at':run['finished_at']} if run else None)
    result['health_state']=('partial' if result['error'] and result['coverage'] and result['coverage'].get('list',{}).get('succeeded') else result['state'])
    result['failure_kind']=failure_kind(result['error'],result['coverage']) if result['error'] else None
    return result


def failure_kind(error,receipt=None):
    if not error:return None
    if any(value in error for value in ('HTTP 401','HTTP 403','权限','登录')):return 'access_denied'
    if any(value in error for value in ('HTTP 404','HTTP 410')):return 'not_available'
    if any(value in error for value in ('HTTP 429','要求稍后重试','同域名采集正在进行')):return 'rate_limited'
    if receipt and receipt.get('list',{}).get('succeeded'):return 'partial_read'
    if any(value in error for value in ('结构','没有找到','解析','RSS','Atom','Feed')):return 'list_rule_or_format'
    if any(value in error for value in ('未授权','授权范围','跳转出了')):return 'scope_rejected'
    return 'connection_or_source_error'


def recent_failures(conn,uid,now=None,max_age=7*86400):
    """Owner-scoped in-app diagnostics; a failure never asserts cancellation.

    Repeating the same error under the same rule keeps its stable problem key.
    Callers decide notification preferences; this helper never sends anything.
    """
    now=int(time.time()) if now is None else int(now)
    result=[]
    for row in conn.execute("SELECT s.source_id,s.version,s.checked_at,s.succeeded_at,s.error,c.data FROM source_subscriptions s JOIN source_catalog c ON c.id=s.source_id WHERE s.user_id=? AND c.user_id=? AND s.enabled=1 AND s.error!='' AND s.checked_at>=? ORDER BY s.checked_at DESC,s.source_id",(uid,uid,now-max_age)):
        catalog=json.loads(row['data']);kind=failure_kind(row['error'])
        result.append({'source_id':row['source_id'],'title':catalog['name'],'error':row['error'],'failure_kind':kind,
            'checked_at':row['checked_at'],'succeeded_at':row['succeeded_at'],'rule_version':row['version'],
            'problem_version':hashlib.sha256(dumps({'rule_version':row['version'],'error':row['error'],
                'last_success':row['succeeded_at']}).encode()).hexdigest()[:24],
            'url':catalog.get('url',''),'in_app_only':True})
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
    if not catalog_matches(catalog,config):
        with db.connect(write=True) as conn:
            conn.execute("UPDATE source_subscriptions SET enabled=0,running_until=0,error='来源已改变，请重新确认订阅范围' WHERE source_id=?",(sid,))
            return status(conn,sid,snapshot['user_id'])
    errors, created, updated = [], 0, 0
    index_succeeded=False
    run_id=ident();config_hash=hashlib.sha256(dumps(config).encode()).hexdigest()
    receipt={'entrypoint':{'url':catalog.get('url',''),'verified_at':None,'state':'registered_only'},
        'list':{'attempted_at':now,'succeeded':False},'articles':{'attempted':0,'succeeded':0,'failed':0,'items':[]},
        'attachments':{'discovered':0,'received':0,'review_required':0,'items':[]},'rejected_entries':[],'errors':[]}
    with db.connect(write=True) as conn:
        conn.execute('INSERT INTO source_acquisition_runs VALUES(?,?,?,?,?,NULL,?)',(run_id,sid,snapshot['version'],config_hash,now,dumps(receipt)))
        conn.execute('INSERT OR IGNORE INTO source_rule_versions VALUES(?,?,?,?)',(sid,snapshot['version'],dumps(config),now))
    def unchanged(conn):
        return conn.execute('SELECT 1 FROM source_subscriptions s JOIN source_catalog c ON c.id=s.source_id WHERE s.source_id=? AND s.enabled=1 AND s.version=? AND c.version=?', (sid, snapshot['version'],snapshot['catalog_version'])).fetchone()
    try:
        with acquisition(db,config,hosts=[urlsplit(config['url']).hostname],max_bytes=1_500_000):
            entries = await fetch_index(config)
        index_succeeded=True
        receipt['list'].update(succeeded=True,entry_count=len(entries),empty_confirmed=getattr(entries,'empty_confirmed',False),snapshot=getattr(entries,'snapshot',{}))
        if canonical_url(catalog.get('url',''))==canonical_url(config['url']):
            receipt['entrypoint'].update(state='read_as_list',verified_at=int(time.time()))
        receipt['rejected_entries']=getattr(entries,'rejected',[])
        if receipt['rejected_entries']:errors.append(f"{len(receipt['rejected_entries'])} 个原文地址未获授权，已拒绝读取")
        with db.connect(write=True) as conn:
            if not unchanged(conn):
                return None
            if not conn.execute('SELECT 1 FROM source_baseline_runs WHERE source_id=?',(sid,)).fetchone():
                conn.executemany('INSERT OR IGNORE INTO source_baseline_items VALUES(?,?)',[(sid,e['url']) for e in entries])
                conn.execute('INSERT INTO source_baseline_runs VALUES(?,?)',(sid,now))
            for entry in entries:
                conn.execute('INSERT INTO source_subscription_items(source_id,url,title,published_at,discovered_at) VALUES(?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET title=excluded.title,published_at=COALESCE(excluded.published_at,source_subscription_items.published_at)',
                             (sid, entry['url'], entry['title'], entry['published_at'], now))
                provenance={'listed_url':entry['url'],'listed_title':entry['title'],'listed_published_at':entry['published_at'],
                    'list_snapshot_sha256':getattr(entries,'snapshot',{}).get('sha256'),
                    'subscription_rule_version':snapshot['version'],'subscription_config_hash':config_hash}
                if config['mode']=='feed':
                    provenance.update(feed_service_url=config['url'],feed_entry_id=entry.get('feed_entry_id',''),
                        source_identity=config.get('source_identity') or catalog['name'],
                        allowed_article_origins=config.get('allowed_article_origins') or [origin(config['url'])])
                conn.execute('INSERT INTO source_entry_provenance VALUES(?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET data=excluded.data',
                    (sid,entry['url'],dumps(provenance)))
            # Retain discovered backlog across polls. Recent known pages are also
            # revisited so a correction at an existing URL is detected.
            pending = [dict(r) for r in conn.execute('SELECT i.*,p.data AS provenance FROM source_subscription_items i LEFT JOIN source_entry_provenance p ON p.source_id=i.source_id AND p.url=i.url WHERE i.source_id=? ORDER BY i.checked_at,i.discovered_at DESC LIMIT 8', (sid,))]
        for item in pending:
            receipt['articles']['attempted']+=1
            try:
                with db.connect(write=True) as conn:
                    if not unchanged(conn):
                        return None
                    conn.execute('UPDATE source_subscriptions SET running_until=? WHERE source_id=?',
                                 (int(time.time()) + 300, sid))
                if not article_allowed(item['url'],config):
                    raise HTTPException(422,'已发现正文不再处于授权范围，未读取')
                origins,hosts=article_scope(config)
                with acquisition(db,config,origins=origins,hosts=hosts):
                    source, _ = await read_link(item['url'])
                if not article_allowed(source.get('origin', {}).get('url', item['url']),config):
                    raise HTTPException(422, '正文跳转出了订阅授权范围')
                source.setdefault('origin',{}).update(json.loads(item['provenance']) if item.get('provenance') else {})
                article_date = source.get('origin', {}).get('published_at')
                if article_date and item['published_at'] and article_date[:10] != item['published_at'][:10]:
                    source['origin']['listed_published_at'] = item['published_at']
                    source['origin'].setdefault('warnings', []).append(
                        f"列表日期 {item['published_at'][:10]} 与正文日期 {article_date[:10]} 不同，已保留两者并采用正文日期，请核对原文")
                from .notice_network import read_network,retain_unavailable
                with acquisition(db,config,origins=origins,hosts=hosts):
                    materials = await read_network(source,config,entries,read=read_link)
                published = article_date or item['published_at']
                with db.connect(write=True) as conn:
                    if not unchanged(conn):
                        return None
                    key='website:'+sid+':'+item['url']
                    materials=retain_unavailable(conn,snapshot['user_id'],key,materials,title=source.get('origin',{}).get('title') or item['title'],published_at=published)
                    result = ingest_notice(conn, snapshot['user_id'], title=source.get('origin',{}).get('title') or item['title'], sources=materials,
                        source_label=catalog['name'], source_url=item['url'], published_at=published,
                        external_key='website:' + sid + ':' + item['url'], materials_complete=False,observed_at=time.time())
                    created += bool(result.get('created'))
                    if result.get('created') and conn.execute('SELECT 1 FROM source_baseline_items WHERE source_id=? AND url=?',(sid,item['url'])).fetchone():
                        conn.execute('INSERT OR IGNORE INTO notice_delivery_suppressions VALUES(?,?)',(result['notice_id'],'initial_website_snapshot'))
                    updated += bool(result.get('updated'))
                    from .source_coverage import coverage
                    incomplete=any(coverage(material)['reading_incomplete'] for material in materials)
                    receipt['articles']['succeeded']+=1
                    receipt['articles']['items'].append({'url':item['url'],'notice_id':result['notice_id'],
                        'checked_at':int(time.time()),'sha256':source['sha256'],'published_at':published,
                        'status':source['status'],'acquisition':source.get('origin',{}).get('acquisition'),'incomplete':incomplete})
                    for material in materials:
                        part=coverage(material)
                        receipt['attachments']['discovered']+=part['attachment_total']
                        receipt['attachments']['received']+=part['attachment_received']
                        receipt['attachments']['review_required']+=int(part['review_required'])
                        material_origin=material.get('origin') or {}
                        for attachment in material_origin.get('attachment_reads',[]):
                            receipt['attachments']['items'].append({**attachment,'article_url':material_origin.get('url'),
                                'recorded_at':int(time.time())})
                    article_error='部分附件或关联内容未完整复查；已有正文和旧证据已保留' if incomplete else ''
                    if article_error:errors.append(article_error)
                    conn.execute('UPDATE source_subscription_items SET checked_at=?,error=? WHERE source_id=? AND url=?', (int(time.time()), article_error, sid, item['url']))
            except HTTPException as exc:
                errors.append(str(exc.detail))
                receipt['articles']['failed']+=1
                receipt['errors'].append({'stage':'article','url':item['url'],'code':exc.status_code,'reason':str(exc.detail)[:500]})
                with db.connect(write=True) as conn:
                    conn.execute('UPDATE source_subscription_items SET checked_at=?,error=? WHERE source_id=? AND url=?', (int(time.time()), str(exc.detail)[:500], sid, item['url']))
    except asyncio.CancelledError:
        errors.append('同步被中断，下次检查会继续；已保存通知保留')
        raise
    except HTTPException as exc:
        errors.append(str(exc.detail))
        receipt['errors'].append({'stage':'list','code':exc.status_code,'reason':str(exc.detail)[:500]})
    except Exception:
        logging.getLogger('campus').exception('source_sync_failed')
        errors.append('同步发生错误，将稍后重试；已保存通知保留')
    finally:
        with db.connect(write=True) as conn:
            if unchanged(conn):
                pending_count = conn.execute('SELECT count(*) FROM source_subscription_items WHERE source_id=? AND checked_at=0', (sid,)).fetchone()[0]
                failed_count=conn.execute("SELECT count(*) FROM source_subscription_items WHERE source_id=? AND error<>''",(sid,)).fetchone()[0]
                if failed_count:errors.append(f'{failed_count} 篇正文或其附件仍需复查，请在来源状态中核对')
                # An old login-restricted article must not progressively defer
                # discovery of NEW public notices for the entire column.
                # Retain its visible failure, while the successful index keeps
                # its ordinary interval (or drains undiscovered articles).
                delay = retry_delay(snapshot,config,pending=bool(pending_count),failed=bool(errors) and not index_succeeded)
                host_delay=conn.execute('SELECT retry_after FROM source_host_limits WHERE hostname=?',(urlsplit(config['url']).hostname,)).fetchone()
                if host_delay:delay=max(delay,int(host_delay[0]-time.time()))
                conn.execute('UPDATE source_subscriptions SET running_until=0,next_poll=?,error=?,succeeded_at=CASE WHEN ? THEN succeeded_at ELSE ? END,received_count=received_count+?,updated_count=updated_count+? WHERE source_id=?',
                             (int(time.time()) + delay, '；'.join(dict.fromkeys(errors))[:1000], bool(errors), int(time.time()), created, updated, sid))
                receipt.update(created=created,updated=updated,pending_count=pending_count,failed_count=failed_count,
                    state='partial' if index_succeeded and errors else 'complete' if index_succeeded else 'failed')
                conn.execute('UPDATE source_acquisition_runs SET finished_at=?,data=? WHERE id=?',(int(time.time()),dumps(receipt),run_id))
                conn.execute('DELETE FROM source_acquisition_runs WHERE source_id=? AND id NOT IN (SELECT id FROM source_acquisition_runs WHERE source_id=? ORDER BY started_at DESC,rowid DESC LIMIT 100)',(sid,sid))
            else:
                conn.execute("UPDATE source_subscriptions SET enabled=0,running_until=0,error='来源设置已变化，请重新确认订阅' WHERE source_id=? AND version=?",(sid,snapshot['version']))
    with db.connect() as conn:
        return status(conn, sid, snapshot['user_id']) if conn.execute('SELECT 1 FROM source_catalog WHERE id=?', (sid,)).fetchone() else None


async def poll_batch(db,rows):
    """A free worker starts the next source immediately; failures stay scoped."""
    slots=asyncio.Semaphore(MAX_CONCURRENT_SOURCES)
    domain_slots={}
    async def poll(row):
        sid=row['source_id']
        config=json.loads(row['config']) if 'config' in row.keys() else {}
        host=urlsplit(config.get('url','')).hostname or sid
        domain=domain_slots.setdefault(host,asyncio.Semaphore(1))
        # Waiting for a busy host must not occupy a global slot that another
        # school's source could use immediately.
        async with domain,slots:
            try:await sync_source(db,sid)
            except HTTPException:
                # A source can be removed or paused after the due list is read.
                logging.getLogger('campus').info('source_subscription_changed_during_poll')
    async with asyncio.TaskGroup() as tasks:
        for row in rows:tasks.create_task(poll(row))


def due_sources(conn,now,limit=8):
    groups={}
    for row in conn.execute('SELECT source_id,config FROM source_subscriptions WHERE enabled=1 AND next_poll<=? AND running_until<=? ORDER BY next_poll,source_id',(now,now)):
        host=urlsplit(json.loads(row['config'])['url']).hostname
        groups.setdefault(host,[]).append(row)
    result=[]
    while groups and len(result)<limit:
        for host in list(groups):
            result.append(groups[host].pop(0))
            if not groups[host]:del groups[host]
            if len(result)>=limit:break
    return result


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
                rows = due_sources(conn,int(time.time()))
            await poll_batch(db,rows)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger('campus').error('source_subscription_worker_failed')
        await asyncio.sleep(POLL_SECONDS)


def install(app, db, user):
    @app.get('/api/source-catalog/{sid}/subscription/rules')
    def rules(sid:str,current=Depends(user)):
        with db.connect() as conn:
            owned(conn,sid,current['id'])
            return {'versions':[{**dict(row),'config':json.loads(row['config'])} for row in conn.execute('SELECT * FROM source_rule_versions WHERE source_id=? ORDER BY version DESC',(sid,))],
                'trials':[{**dict(row),'config':json.loads(row['config']),'data':json.loads(row['data'])} for row in conn.execute('SELECT * FROM source_rule_trials WHERE source_id=? ORDER BY created_at DESC,rowid DESC',(sid,))]}

    @app.post('/api/source-catalog/{sid}/subscription/preview')
    async def preview_rule(sid:str,payload:Subscription,current=Depends(user)):
        rate_limit(db,'source-trial:'+current['id'],20,3600)
        config=payload.model_dump(exclude={'enabled','version'})
        with db.connect() as conn:
            catalog=json.loads(owned(conn,sid,current['id'])['data'])
            if not catalog_matches(catalog,config):raise HTTPException(422,'试读规则不属于已登记的来源授权范围')
            previous=conn.execute('SELECT version FROM source_subscriptions WHERE source_id=?',(sid,)).fetchone()
            if payload.version!=(previous[0] if previous else 0):raise HTTPException(409,'订阅规则已变化，请刷新后试读')
        return await trial_rule(db,sid,current['id'],config,payload.version)

    @app.post('/api/source-catalog/{sid}/subscription/apply')
    def install_rule(sid:str,payload:RuleApply,current=Depends(user)):
        with db.connect(write=True) as conn:return apply_trial(conn,sid,current['id'],payload)

    @app.post('/api/source-catalog/{sid}/subscription/rollback')
    async def rollback_rule(sid:str,payload:RuleRollback,current=Depends(user)):
        rate_limit(db,'source-trial:'+current['id'],20,3600)
        with db.connect() as conn:
            catalog=json.loads(owned(conn,sid,current['id'])['data'])
            previous=conn.execute('SELECT version,enabled FROM source_subscriptions WHERE source_id=?',(sid,)).fetchone()
            if not previous or previous['version']!=payload.version:raise HTTPException(409,'当前规则已变化，请重新选择回滚版本')
            row=conn.execute('SELECT config FROM source_rule_versions WHERE source_id=? AND version=?',(sid,payload.restore_version)).fetchone()
            if not row:raise HTTPException(404,'规则历史不存在')
            config=json.loads(row[0])
            if not catalog_matches(catalog,config):raise HTTPException(422,'历史规则已不在当前授权范围内')
        trial=await trial_rule(db,sid,current['id'],config,payload.version)
        with db.connect(write=True) as conn:return apply_trial(conn,sid,current['id'],RuleApply(version=payload.version,trial_id=trial['trial_id'],enabled=bool(previous['enabled'])))

    @app.get('/api/source-presets')
    def presets(current=Depends(user)):
        return PRESETS

    @app.post('/api/source-presets/{preset_id}/subscribe')
    async def subscribe_preset(preset_id: str, current=Depends(user)):
        from .usage_limits import check_count
        from .workspace import CatalogItem
        preset = get_preset(preset_id)
        if not preset:
            raise HTTPException(404, '此学校栏目不存在，请重新选择')
        # Registering a source is not a working connection. First activation
        # must read real list/body samples; failure retains a manual source and
        # its diagnostic trial, never an active subscription.
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
            if previous:return {'source_id':sid,'created':created,'subscription':status(conn,sid,current['id'])}
        rate_limit(db,'source-trial:'+current['id'],20,3600)
        config=Subscription(url=preset['url'],article_path_prefix=preset['article_path_prefix'],
            preset_id=preset_id).model_dump(exclude={'enabled','version'})
        trial=await trial_rule(db,sid,current['id'],config,0)
        with db.connect(write=True) as conn:
            # Concurrent repeated subscription cannot resume a source that was
            # paused or reconfigured while this request was reading.
            previous=conn.execute('SELECT 1 FROM source_subscriptions WHERE source_id=?',(sid,)).fetchone()
            result=status(conn,sid,current['id']) if previous else apply_trial(conn,sid,current['id'],RuleApply(version=0,trial_id=trial['trial_id']))
            return {'source_id':sid,'created':created,'subscription':result}

    @app.get('/api/source-subscriptions')
    def subscriptions(current=Depends(user)):
        with db.connect() as conn:
            return [status(conn, row['id'], current['id']) for row in conn.execute('SELECT id FROM source_catalog WHERE user_id=?', (current['id'],))]

    @app.put('/api/source-catalog/{sid}/subscription')
    async def configure(sid: str, payload: Subscription, current=Depends(user)):
        with db.connect() as conn:
            catalog = json.loads(owned(conn, sid, current['id'])['data'])
            if catalog['platform'] != 'website':
                raise HTTPException(422, '仅公开网站使用网页订阅；公众号和群需要各自的平台授权')
            config = payload.model_dump(exclude={'enabled','version'})
            if not catalog_matches(catalog,config):
                raise HTTPException(422, '订阅地址须属于登记网站；跨域Feed须明确真实发布方并将登记网站加入允许原文来源')
            previous = conn.execute('SELECT config,version,enabled FROM source_subscriptions WHERE source_id=?', (sid,)).fetchone()
            same=bool(previous and same_config(json.loads(previous['config']),config))
            if payload.version != (previous['version'] if previous else 0):
                if (previous and previous['version']==payload.version+1 and same and bool(previous['enabled'])==payload.enabled
                        and (not payload.enabled or verified_config(conn,sid,config,applied_version=previous['version'],trial_version=payload.version))):
                    return status(conn,sid,current['id'])
                raise HTTPException(409,'订阅设置已在另一处修改，请刷新后再保存')
            if same and bool(previous['enabled'])==payload.enabled and (not payload.enabled or verified_config(conn,sid,config)):
                return status(conn,sid,current['id'])
            requires_trial=not previous or not same or payload.enabled
        if requires_trial:
            rate_limit(db,'source-trial:'+current['id'],20,3600)
            trial=await trial_rule(db,sid,current['id'],config,payload.version)
            with db.connect(write=True) as conn:
                return apply_trial(conn,sid,current['id'],RuleApply(version=payload.version,trial_id=trial['trial_id'],enabled=payload.enabled))
        # Only pausing an unchanged current rule reaches this path. No request
        # to an unavailable source can prevent the owner from stopping it.
        with db.connect(write=True) as conn:
            owned(conn,sid,current['id'])
            previous=conn.execute('SELECT * FROM source_subscriptions WHERE source_id=? AND user_id=?',(sid,current['id'])).fetchone()
            if not previous or previous['version']!=payload.version:raise HTTPException(409,'订阅设置已变化，请重新读取后暂停')
            conn.execute('INSERT OR IGNORE INTO source_rule_versions VALUES(?,?,?,?)',(sid,previous['version'],previous['config'],int(time.time())))
            conn.execute("UPDATE source_subscriptions SET enabled=0,version=version+1,running_until=0,error='' WHERE source_id=?",(sid,))
            version=conn.execute('SELECT version FROM source_subscriptions WHERE source_id=?',(sid,)).fetchone()[0]
            conn.execute('INSERT OR IGNORE INTO source_rule_versions VALUES(?,?,?,?)',(sid,version,dumps(config),int(time.time())))
            return status(conn, sid, current['id'])

    @app.post('/api/source-catalog/{sid}/refresh')
    async def refresh(sid: str, current=Depends(user)):
        rate_limit(db, 'source-refresh:' + current['id'], 20, 3600)
        with db.connect() as conn:
            owned(conn, sid, current['id'])
        return await sync_source(db, sid, current['id'], force=True)
