"""Bounded, anonymous public acquisition shared only by website subscriptions.

The cache contains public HTTP responses, never private notices, authorization
headers or user progress. Every network request still uses pinned public DNS.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from .db import dumps, ident
from .evidence_web import public_url
from .public_http import PublicHTTPTransport

TABLES={'source_public_cache','source_host_limits'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS source_public_cache(
 cache_key TEXT PRIMARY KEY, scope TEXT NOT NULL, url TEXT NOT NULL,
 headers TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL,
 fetched_at REAL NOT NULL, checked_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS source_public_cache_age ON source_public_cache(checked_at);
CREATE TABLE IF NOT EXISTS source_host_limits(
 hostname TEXT PRIMARY KEY, lease_id TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
 next_allowed REAL NOT NULL DEFAULT 0, retry_after REAL NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO meta VALUES('source_fetch_schema_version','1');
"""
CONTEXT=ContextVar('public_source_acquisition',default=None)
FRESH_SECONDS=30
DOMAIN_INTERVAL=.25
MAX_CACHE_BYTES=64*1024*1024
# These are the only negotiated request fields the anonymous reader can reuse.
# Values (including absence, distinct from an empty value) are always in the key.
CACHE_REQUEST_FIELDS=('accept','accept-encoding','accept-language','user-agent','referer','host')
CACHE_POLICY_VERSION='2'


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='source_fetch_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('公开来源缓存版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)
    policy=conn.execute("SELECT value FROM meta WHERE key='source_fetch_policy_version'").fetchone()
    if not policy or policy[0]!=CACHE_POLICY_VERSION:
        # Old entries did not retain enough negotiation/privacy information to
        # prove that they can be shared. User-owned evidence is a separate store.
        conn.execute('DELETE FROM source_public_cache')
        conn.execute("INSERT OR REPLACE INTO meta VALUES('source_fetch_policy_version',?)",(CACHE_POLICY_VERSION,))


def origin(value):
    safe=public_url(value)
    if not safe:return None
    parsed=urlsplit(safe)
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    default=443 if parsed.scheme=='https' else 80
    return parsed.scheme.lower()+'://'+parsed.hostname.lower()+((':'+str(port)) if port!=default else '')


def allowed(value,origins,hosts=()):
    return bool(public_url(value) and (origin(value) in origins or urlsplit(value).hostname in hosts))


@contextmanager
def acquisition(db,config,*,origins=(),hosts=(),max_bytes=5*1024*1024):
    scope=hashlib.sha256(dumps({'mode':config.get('mode'),'url':config.get('url'),
        'allowed_article_origins':sorted(config.get('allowed_article_origins') or []),
        'article_path_prefix':config.get('article_path_prefix',''),'preset_id':config.get('preset_id',''),
        'parser_version':'2'}).encode()).hexdigest()
    token=CONTEXT.set({'db':db,'scope':scope,'origins':set(origins),'hosts':set(hosts),'max_bytes':max_bytes})
    try:yield
    finally:CONTEXT.reset(token)


def transport(fallback=PublicHTTPTransport):
    context=CONTEXT.get()
    return CachedPublicTransport(context,inner=fallback()) if context else fallback()


def retry_until(value,now):
    try:
        if str(value).strip().isdigit():return now+min(int(value),86400)
        parsed=parsedate_to_datetime(value)
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        return max(now,min(now+86400,parsed.timestamp()))
    except (ValueError,TypeError,OverflowError):return now+60


def cache_directives(value):
    result={}
    for part in str(value or '').split(','):
        name,separator,argument=part.strip().partition('=')
        if name:result.setdefault(name.lower(),[]).append(argument.strip().strip('"') if separator else None)
    return result


def http_date(value):
    try:
        parsed=parsedate_to_datetime(value)
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError,TypeError,OverflowError):return None


def cache_policy(headers,received_at):
    """Return storage permission and freshness after conservative HTTP policy.

    This reader's shared freshness is capped at 30 seconds. It never serves a
    stale response on network failure; validators only authorize the current
    request until the origin's response permits a later reuse.
    """
    headers={k.lower():v for k,v in headers.items()}
    directives=cache_directives(headers.get('cache-control'))
    vary={field.strip().lower() for field in headers.get('vary','').split(',') if field.strip()}
    if ('no-store' in directives or 'private' in directives or 'set-cookie' in headers
            or not vary.issubset(CACHE_REQUEST_FIELDS)):
        return False,0
    if 'no-cache' in directives:return True,0
    lifetimes=[]
    for name in ('max-age','s-maxage'):
        for value in directives.get(name,[]):
            if value is None or not value.isascii() or not value.isdigit():return True,0
            # A malformed duplicate is not a reason to extend freshness.
            lifetimes.append(min(int(value[:12]),2**31) if len(value)<=12 else 2**31)
    date=http_date(headers.get('date'))
    if not lifetimes and 'expires' in headers:
        expires=http_date(headers['expires'])
        if expires is None:return True,0
        lifetimes.append(max(0,expires-(date if date is not None else received_at)))
    age=headers.get('age','0').strip()
    if not age.isascii() or not age.isdigit():return True,0
    initial_age=max(min(int(age[:12]),2**31) if len(age)<=12 else 2**31,
                    max(0,received_at-date) if date is not None else 0)
    return True,max(0,min(FRESH_SECONDS,min(lifetimes or [FRESH_SECONDS])-initial_age))


def stored_headers(headers):
    # HTTPX has already decoded body bytes; hop-by-hop metadata and cookies
    # cannot describe the stored representation or enter a shared response.
    blocked={'content-encoding','content-length','set-cookie','transfer-encoding',
             'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','upgrade'}
    blocked.update(field.strip().lower() for field in headers.get('connection','').split(','))
    return {k.lower():v for k,v in headers.items() if k.lower() not in blocked}


class CachedPublicTransport(httpx.AsyncBaseTransport):
    def __init__(self,context,inner=None):
        self.context=context
        self.inner=inner or PublicHTTPTransport()

    async def aclose(self):
        await self.inner.aclose()

    def cached(self,key):
        with self.context['db'].connect() as conn:
            row=conn.execute('SELECT * FROM source_public_cache WHERE cache_key=?',(key,)).fetchone()
            if row and len(row['content'])>self.context['max_bytes']:
                raise HTTPException(413,'来源缓存响应超过本次读取上限，未截断')
            row=dict(row) if row else None
        if row and not cache_policy(json.loads(row['headers']),row['checked_at'])[0]:
            self.purge(row['url'])
            return None
        return row

    def purge(self,url):
        # Privacy policy changes invalidate older variants in every public
        # subscription scope, not merely the variant being revalidated now.
        with self.context['db'].connect(write=True) as conn:
            conn.execute('DELETE FROM source_public_cache WHERE url=?',(url,))

    @staticmethod
    def fresh(row,now,request):
        directives=cache_directives(request.headers.get('cache-control'))
        if 'no-cache' in directives or 'no-store' in directives or 'max-age' in directives:return False
        if not row:return False
        permitted,lifetime=cache_policy(json.loads(row['headers']),row['checked_at'])
        return permitted and max(0,now-row['checked_at'])<lifetime

    @staticmethod
    def response(row,request,state):
        headers=json.loads(row['headers'])
        headers.update({'x-luojia-cache':state,'x-luojia-content-sha256':row['sha256']})
        return httpx.Response(200,headers=headers,content=row['content'],request=request)

    async def handle_async_request(self,request):
        context=self.context;db=context['db'];url=str(request.url);now=time.time()
        if request.method!='GET' or any(h in request.headers for h in ('authorization','cookie','proxy-authorization')):
            raise HTTPException(422,'公共来源缓存不接收私有凭证或写入请求')
        if not allowed(url,context['origins'],context['hosts']):
            raise HTTPException(422,'读取目标或重定向超出已授权的来源范围，未发出请求')
        key=hashlib.sha256(dumps({'policy':CACHE_POLICY_VERSION,'scope':context['scope'],'url':url,
            'request':{field:request.headers.get(field) for field in CACHE_REQUEST_FIELDS}}).encode()).hexdigest()
        request_store='no-store' not in cache_directives(request.headers.get('cache-control'))
        cached=self.cached(key)
        if not request_store:self.purge(url);cached=None
        if self.fresh(cached,now,request):
            return self.response(cached,request,'shared')
        host=urlsplit(url).hostname;lease=ident();deadline=now+12
        while True:
            now=time.time()
            with db.connect(write=True) as conn:
                conn.execute('INSERT OR IGNORE INTO source_host_limits(hostname) VALUES(?)',(host,))
                limit=conn.execute('SELECT * FROM source_host_limits WHERE hostname=?',(host,)).fetchone()
                if limit['retry_after']>now:
                    raise HTTPException(429,'来源要求稍后重试，已有内容保留',headers={'Retry-After':str(max(1,int(limit['retry_after']-now)))})
                wait=max(limit['lease_until'],limit['next_allowed'])-now
                if wait<=0:
                    conn.execute('UPDATE source_host_limits SET lease_id=?,lease_until=? WHERE hostname=?',(lease,now+25,host))
                    break
            if now>=deadline:raise HTTPException(503,'同域名采集正在进行，已保留任务等待下轮',headers={'Retry-After':'30'})
            await asyncio.sleep(min(max(wait,.02),.15))
            cached=self.cached(key)
            if self.fresh(cached,time.time(),request):
                return self.response(cached,request,'shared')
        try:
            # Another process may have refreshed the same column while this
            # request waited for the durable domain lease.
            cached=self.cached(key)
            if self.fresh(cached,time.time(),request):
                return self.response(cached,request,'shared')
            if cached:
                headers=json.loads(cached['headers'])
                if headers.get('etag'):request.headers['If-None-Match']=headers['etag']
                if headers.get('last-modified'):request.headers['If-Modified-Since']=headers['last-modified']
            response=await self.inner.handle_async_request(request)
            try:
                if response.status_code in {429,503}:
                    until=retry_until(response.headers.get('retry-after','60'),time.time())
                    with db.connect(write=True) as conn:
                        conn.execute('UPDATE source_host_limits SET retry_after=max(retry_after,?) WHERE hostname=?',(until,host))
                if response.status_code==304:
                    if not cached:raise HTTPException(502,'来源返回304但没有可用快照，请重新检查来源')
                    now=time.time()
                    merged={**json.loads(cached['headers']),**dict(response.headers)}
                    permitted=cache_policy(merged,now)[0] and request_store
                    headers=stored_headers(merged)
                    if permitted:
                        with db.connect(write=True) as conn:
                            conn.execute('UPDATE source_public_cache SET headers=?,checked_at=? WHERE cache_key=?',(dumps(headers),now,key))
                    else:self.purge(url)
                    cached.update({'headers':dumps(headers),'checked_at':now})
                    return self.response(cached,request,'revalidated' if permitted else 'revalidated_uncached')
                permitted=cache_policy(response.headers,time.time())[0] and request_store
                if not permitted:self.purge(url)
                body=bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body)>context['max_bytes']:raise HTTPException(413,'来源响应超过读取上限，旧快照保留；未截断')
                # Bytes are decoded by HTTPX; do not preserve stale compressed
                # length or content-encoding. Cookies never enter the cache.
                headers=stored_headers(response.headers)
                if response.status_code==200:
                    now=time.time();digest=hashlib.sha256(body).hexdigest()
                    if permitted:
                        with db.connect(write=True) as conn:
                            conn.execute('INSERT INTO source_public_cache VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET headers=excluded.headers,content=excluded.content,sha256=excluded.sha256,fetched_at=excluded.fetched_at,checked_at=excluded.checked_at',
                                (key,context['scope'],url,dumps(headers),bytes(body),digest,now,now))
                            # Bounded public cache, independent of users' immutable
                            # evidence retained in their own notice records.
                            total=conn.execute('SELECT COALESCE(sum(length(content)),0) FROM source_public_cache').fetchone()[0]
                            for old in conn.execute('SELECT cache_key,length(content) AS size FROM source_public_cache WHERE cache_key<>? ORDER BY checked_at',(key,)).fetchall():
                                if total<=MAX_CACHE_BYTES:break
                                conn.execute('DELETE FROM source_public_cache WHERE cache_key=?',(old['cache_key'],));total-=old['size']
                    headers.update({'x-luojia-cache':'fetched' if permitted else 'fetched_uncached','x-luojia-content-sha256':digest})
                return httpx.Response(response.status_code,headers=headers,content=bytes(body),request=request)
            finally:await response.aclose()
        finally:
            with db.connect(write=True) as conn:
                conn.execute('UPDATE source_host_limits SET lease_id=\'\',lease_until=0,next_allowed=? WHERE hostname=? AND lease_id=?',(time.time()+DOMAIN_INTERVAL,host,lease))
