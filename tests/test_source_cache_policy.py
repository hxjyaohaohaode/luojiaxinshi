"""Anonymous HTTP cache contracts; every response is synthetic and local."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app import source_fetch
from tests.test_workflow import env

URL='https://school.example.edu.cn/info/policy'


@pytest.fixture
def reader(env,monkeypatch):
    clock=[1000.0]
    monkeypatch.setattr(source_fetch,'time',SimpleNamespace(time=lambda:clock[0]))
    monkeypatch.setattr(source_fetch,'DOMAIN_INTERVAL',0)
    db=env[0].state.db
    def read(handler,*,scope='public-rule-a',headers=None):
        context={'db':db,'scope':scope,'origins':{'https://school.example.edu.cn'},'hosts':set(),'max_bytes':1024}
        async def run():
            transport=source_fetch.CachedPublicTransport(context,httpx.MockTransport(handler))
            try:return await transport.handle_async_request(httpx.Request('GET',URL,headers=headers))
            finally:await transport.aclose()
        return asyncio.run(run())
    def count():
        with db.connect() as conn:return conn.execute('SELECT count(*) FROM source_public_cache').fetchone()[0]
    return read,count,clock,db


@pytest.mark.parametrize('prohibition',[
    {'Cache-Control':'no-store'}, {'Cache-Control':'private'},
    {'Cache-Control':'private="X-Identity"'}, {'Set-Cookie':'session=synthetic; Secure'},
    {'Vary':'*'}, {'Vary':'X-Campus-Identity'},
])
@pytest.mark.parametrize('status',[200,304])
def test_privacy_and_unkeyed_vary_never_store_and_clear_old_variants(reader,prohibition,status):
    read,count,clock,db=reader;seen=[]
    def handler(request):
        seen.append(dict(request.headers))
        if len(seen)<=2:return httpx.Response(200,headers={'Cache-Control':'max-age=0','ETag':'"v1"'},text='original')
        return httpx.Response(status if len(seen)==3 else 200,headers=prohibition,text='changed' if status==200 or len(seen)>3 else '')
    read(handler);read(handler,scope='public-rule-b')
    assert count()==2
    checked=read(handler)
    assert checked.text==('original' if status==304 else 'changed')
    assert 'set-cookie' not in checked.headers and count()==0
    assert checked.headers['x-luojia-cache'].endswith('_uncached')
    read(handler,scope='public-rule-b')
    assert count()==0 and len(seen)==4 and 'if-none-match' not in seen[-1]


@pytest.mark.parametrize('control',['no-cache','max-age=0','public, s-maxage=0'])
def test_revalidation_required_each_time_and_304_retains_prior_policy(reader,control):
    read,count,clock,db=reader;seen=[]
    def handler(request):
        seen.append(dict(request.headers))
        if len(seen)==1:return httpx.Response(200,headers={'Cache-Control':control,'ETag':'"v1"','Last-Modified':'Thu, 01 Jan 1970 00:15:00 GMT'},text='original')
        return httpx.Response(304,headers={'ETag':'"v1"'})
    responses=[read(handler) for _ in range(3)]
    assert len(seen)==3 and count()==1
    assert all(response.text=='original' for response in responses)
    assert all(request['if-none-match']=='"v1"' and 'if-modified-since' in request for request in seen[1:])
    assert all(response.headers['cache-control']==control for response in responses)


@pytest.mark.parametrize(('headers','fresh_for'),[
    ({'Cache-Control':'max-age=2'},2),
    ({'Cache-Control':'max-age=3600'},30),
    ({'Cache-Control':'max-age=6','Age':'5'},1),
    ({'Cache-Control':'max-age=10','Date':'Thu, 01 Jan 1970 00:16:35 GMT'},5),
    ({'Expires':'Thu, 01 Jan 1970 00:16:42 GMT'},2),
])
def test_freshness_obeys_origin_age_and_deployment_cap(reader,headers,fresh_for):
    read,count,clock,db=reader;seen=[]
    def handler(request):
        seen.append(dict(request.headers))
        return httpx.Response(200,headers={**headers,'ETag':'"v1"'},text='original')
    read(handler);clock[0]+=fresh_for/2
    assert read(handler).headers['x-luojia-cache']=='shared' and len(seen)==1
    clock[0]+=fresh_for/2+.01
    assert read(handler).headers['x-luojia-cache']=='fetched' and len(seen)==2
    assert seen[-1]['if-none-match']=='"v1"'


def test_supported_vary_distinguishes_languages_absence_and_empty_header(reader):
    read,count,clock,db=reader;seen=[]
    def handler(request):
        value=request.headers.get('accept-language');seen.append(value)
        return httpx.Response(200,headers={'Vary':'Accept-Language, Accept-Encoding','Cache-Control':'max-age=30'},text=repr(value))
    for headers in ({'Accept-Language':'zh-CN'},{'Accept-Language':'en'},None,{'Accept-Language':''}):
        first=read(handler,headers=headers);second=read(handler,headers=headers)
        assert first.text==second.text and second.headers['x-luojia-cache']=='shared'
    assert seen==['zh-CN','en',None,''] and count()==4


def test_304_updates_explicit_policy_but_never_drops_previous_vary(reader):
    read,count,clock,db=reader;seen=[]
    def handler(request):
        seen.append(dict(request.headers))
        if len(seen)==1:return httpx.Response(200,headers={'Cache-Control':'no-cache','Vary':'Accept-Language','ETag':'"v1"'},text='original')
        return httpx.Response(304,headers={'Cache-Control':'max-age=1','ETag':'"v2"'})
    read(handler);validated=read(handler)
    assert validated.headers['vary']=='Accept-Language' and validated.headers['etag']=='"v2"'
    assert read(handler).headers['x-luojia-cache']=='shared' and len(seen)==2
    clock[0]+=1.1;read(handler)
    assert len(seen)==3 and seen[-1]['if-none-match']=='"v2"'


def test_policy_upgrade_discards_only_unverifiable_public_cache(reader):
    read,count,clock,db=reader
    read(lambda request:httpx.Response(200,text='old cache'))
    assert count()==1
    with db.connect(write=True) as conn:
        conn.execute("DELETE FROM meta WHERE key='source_fetch_policy_version'")
        source_fetch.initialize(conn)
        assert conn.execute('SELECT count(*) FROM source_public_cache').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM source_host_limits').fetchone()[0]==1
        assert conn.execute("SELECT value FROM meta WHERE key='source_fetch_policy_version'").fetchone()[0]=='2'
