"""Short-lived, account-independent observations for three public WHU columns.

Only normalized anonymous public results are shared. Browser credentials,
cookies, raw response headers and user progress are never persisted here.
"""
import asyncio
import base64
import copy
import hashlib
import json
import re
import time
from urllib.parse import parse_qsl,unquote,urlsplit

from fastapi import HTTPException

from .db import dumps,ident

HOSTS={'whu-unit-xgbnew':'xgbnew.whu.edu.cn','whu-unit-future':'future.whu.edu.cn',
       'whu-unit-finance':'finance.whu.edu.cn'}
TABLES={'school_public_observations','school_public_leases'}
TTL=300
ITEM_LIMIT=8*1024*1024
TOTAL_LIMIT=64*1024*1024
SENSITIVE_QUERY=re.compile(r'(?:token|session|auth|ticket|password|secret|credential|nonce|key|code|sign)',re.I)


def initialize(conn):
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    marker=conn.execute("SELECT value FROM meta WHERE key='school_public_observation_schema_version'").fetchone()
    if marker and (marker[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('学校公开来源共享记录版本不兼容或缺少数据表')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS school_public_observations(
          cache_key TEXT PRIMARY KEY, data BLOB NOT NULL, observed_at REAL NOT NULL, expires_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS school_public_observations_expiry ON school_public_observations(expires_at);
        CREATE TABLE IF NOT EXISTS school_public_leases(
          cache_key TEXT PRIMARY KEY, lease_id TEXT NOT NULL, lease_until REAL NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('school_public_observation_schema_version','1');
    ''')


def eligible(context,url):
    if not context or context.get('bypass_shared'):return False
    expected=HOSTS.get(context.get('preset_id',''));parts=urlsplit(url)
    from .source_fetch import allowed
    return bool(expected and parts.scheme=='https' and parts.hostname==expected and not parts.username and not parts.password
                and allowed(url,context['origins'],context['hosts']))


def safe_value(value):
    if isinstance(value,str) and value.lower().startswith(('http://','https://')):
        try:
            parts=urlsplit(value)
            sensitive_path=any(part.lower() in {'login','logout','auth','oauth','session','token','ticket','password','secret'}
                               for part in unquote(parts.path).split('/'))
            return not parts.username and not parts.password and not sensitive_path and not any(SENSITIVE_QUERY.search(k) for k,_ in parse_qsl(parts.query,keep_blank_values=True))
        except (ValueError,UnicodeError):return False
    if isinstance(value,dict):return all(safe_value(k) and safe_value(v) for k,v in value.items())
    if isinstance(value,list):return all(safe_value(v) for v in value)
    return True


def key_for(context,kind,url,extra=''):
    return hashlib.sha256(dumps({'scope':context['scope'],'kind':kind,'url':url,'extra':extra,'version':1}).encode()).hexdigest()


def load(conn,key):
    row=conn.execute('SELECT data FROM school_public_observations WHERE cache_key=? AND expires_at>?',(key,time.time())).fetchone()
    if not row:return None
    try:return json.loads(row['data'])
    except (ValueError,TypeError,UnicodeDecodeError):return None


async def singleflight(context,key,compute,pack,unpack):
    db=context['db'];deadline=time.monotonic()+35;lease=ident()
    while True:
        # A shared hit is read-only; large subscriber groups must not all
        # compete for SQLite's write lock just to reuse the same notice.
        with db.connect() as conn:
            cached=load(conn,key)
        if cached is not None:
            try:return unpack(cached)
            except (ValueError,TypeError,KeyError):pass
        with db.connect(write=True) as conn:
            cached=load(conn,key)
            if cached is not None:
                try:return unpack(cached)
                except (ValueError,TypeError,KeyError):
                    conn.execute('DELETE FROM school_public_observations WHERE cache_key=?',(key,))
            now=time.time()
            row=conn.execute('SELECT lease_until FROM school_public_leases WHERE cache_key=?',(key,)).fetchone()
            if not row or row['lease_until']<=now:
                conn.execute('INSERT INTO school_public_leases VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET lease_id=excluded.lease_id,lease_until=excluded.lease_until',
                             (key,lease,now+240))
                break
        if time.monotonic()>=deadline:
            raise HTTPException(503,'此公开栏目正在统一采集，请稍后重试')
        await asyncio.sleep(.2)
    try:
        result=await compute();payload=pack(result)
        if payload is not None and safe_value(payload):
            ttl=max(0,min(TTL,int(payload.pop('_cache_ttl',0))))
            encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            if ttl and len(encoded)<=ITEM_LIMIT:
                with db.connect(write=True) as conn:
                    now=time.time()
                    conn.execute('INSERT INTO school_public_observations VALUES(?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET data=excluded.data,observed_at=excluded.observed_at,expires_at=excluded.expires_at',
                                 (key,encoded,now,now+ttl))
                    conn.execute('DELETE FROM school_public_observations WHERE expires_at<=?',(now,))
                    total=conn.execute('SELECT COALESCE(sum(length(data)),0) FROM school_public_observations').fetchone()[0]
                    for row in conn.execute('SELECT cache_key,length(data) AS size FROM school_public_observations WHERE cache_key<>? ORDER BY observed_at',(key,)).fetchall():
                        if total<=TOTAL_LIMIT:break
                        conn.execute('DELETE FROM school_public_observations WHERE cache_key=?',(row['cache_key'],));total-=row['size']
        return result
    finally:
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM school_public_leases WHERE cache_key=? AND lease_id=?',(key,lease))


async def index(context,config,compute):
    if not eligible(context,config['url']):return await compute()
    key=key_for(context,'index',config['url'])
    def pack(entries):
        snapshot=getattr(entries,'snapshot',{})
        ttl=snapshot.get('public_observation_ttl',0)
        if not ttl:return None
        return {'entries':list(entries),'snapshot':snapshot,'rejected':getattr(entries,'rejected',[]),
                'empty_confirmed':getattr(entries,'empty_confirmed',False),'_cache_ttl':ttl}
    def unpack(data):
        from .source_sync import IndexEntries
        result=IndexEntries(data['entries'],rejected=data['rejected'],empty_confirmed=data['empty_confirmed'])
        result.snapshot={**data['snapshot'],'acquisition':'shared_public_observation'}
        return result
    return await singleflight(context,key,compute,pack,unpack)


async def material(context,url,*,referrer,expanded,compute):
    if not eligible(context,url):return await compute()
    key=key_for(context,'material',url,dumps({'referrer':referrer or '', 'expanded':expanded}))
    def pack(value):
        source,title=value
        ttl=source.get('origin',{}).get('public_observation_ttl',0)
        if not ttl or source.get('status')=='failed':return None
        record=copy.deepcopy(source);content=record.get('content')
        if content is not None:record['content']=base64.b64encode(content).decode('ascii')
        record.pop('id',None)
        return {'source':record,'title':title,'_cache_ttl':ttl}
    def unpack(data):
        source=copy.deepcopy(data['source']);source['id']=ident()
        if source.get('content') is not None:source['content']=base64.b64decode(source['content'],validate=True)
        source['origin']['acquisition']='shared_public_observation'
        return source,data['title']
    return await singleflight(context,key,compute,pack,unpack)
