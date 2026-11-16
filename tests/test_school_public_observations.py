"""Shared anonymous school data must never share user state or credentials."""
import asyncio

import httpx

from app import notice_intake,source_fetch,source_sync
from app.official_sources import get_preset
from tests.test_workflow import account,env
from tests.source_trial_fixture import successful_rule_trial


def test_two_users_share_anonymous_school_reads_but_keep_independent_notices(env,monkeypatch):
    app,_=env;a,b=account(env),account(env,'second')
    p=get_preset('whu-unit-xgbnew');seen=[]
    list_body='''<ul><li><a href="/2025/content.jsp?urltype=news.NewsContentUrl&amp;wbtreeid=4201&amp;wbnewsid=1">学校公开通知一</a>2026-11-01</li>
      <li><a href="/2025/content.jsp?urltype=news.NewsContentUrl&amp;wbtreeid=4201&amp;wbnewsid=2">学校公开通知二</a>2026-11-02</li></ul>'''
    def handler(request):
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        seen.append(str(request.url))
        if request.url.path.endswith('list1.jsp'):text=list_body
        else:text='<meta name="ArticleTitle" content="学校公开通知"><meta name="PubDate" content="2026-11-01"><div id="vsb_content_1"><p>公开正文，请核对。</p></div>'
        return httpx.Response(200,headers={'content-type':'text/html; charset=utf-8','set-cookie':'JSESSIONID=anonymous-only; Path=/'},text=text)
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(source_fetch,'WHU_GROUP_INTERVAL',0)
    first=a.post('/api/source-presets/'+p['id']+'/subscribe',json={})
    second=b.post('/api/source-presets/'+p['id']+'/subscribe',json={})
    assert first.status_code==second.status_code==200,(first.text,second.text)
    assert len(seen)==3 # one list and two article samples, not once per user
    for client,result in [(a,first.json()),(b,second.json())]:
        uid=client.get('/api/session').json()['user']['id']
        outcome=asyncio.run(source_sync.sync_source(app.state.db,result['source_id'],uid))
        assert outcome['received_count']>=1
        assert not client.get('/api/notice-automation').json()['enabled']
    an=a.get('/api/notices').json();bn=b.get('/api/notices').json()
    assert an and bn and an[0]['id']!=bn[0]['id']
    assert a.get('/api/notices/'+bn[0]['id']).status_code==404
    with app.state.db.connect() as conn:
        rows=conn.execute('SELECT data FROM school_public_observations').fetchall()
        assert len(rows)>=3
        assert all(b'JSESSIONID' not in row['data'] and b'anonymous-only' not in row['data'] for row in rows)
        assert conn.execute('SELECT count(*) FROM source_public_cache').fetchone()[0]==0


def test_no_store_response_is_not_shared(env,monkeypatch):
    app,_=env;p=get_preset('whu-unit-xgbnew');calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,headers={'content-type':'text/html','cache-control':'no-store','set-cookie':'JSESSIONID=anonymous'},
            text='<ul><li><a href="/info/4201/1.htm">学校公开通知一</a></li></ul>')
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(source_fetch,'WHU_GROUP_INTERVAL',0)
    config=source_sync.Subscription(url=p['url'],article_path_prefix=p['article_path_prefix'],preset_id=p['id']).model_dump(exclude={'enabled','version'})
    async def run():
        for _ in range(2):
            with source_fetch.acquisition(app.state.db,config,hosts=['xgbnew.whu.edu.cn']):
                assert len(await source_sync.fetch_index(config))==1
    asyncio.run(run())
    assert len(calls)==2
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM school_public_observations').fetchone()[0]==0


def test_tokenized_urls_never_enter_shared_observations(env):
    from app.school_public_observations import safe_value
    assert not safe_value({'url':'https://xgbnew.whu.edu.cn/info/1/1.htm?token=secret'})
    assert not safe_value({'url':'https://xgbnew.whu.edu.cn/file.pdf?apiKey=secret'})
    assert not safe_value({'url':'HTTPS://xgbnew.whu.edu.cn/%74oken/secret'})
    assert not safe_value({'url':'https://[invalid'})
    assert safe_value({'url':'https://xgbnew.whu.edu.cn/content.jsp?urltype=news.NewsContentUrl&wbtreeid=1&wbnewsid=2'})


def test_concurrent_subscribers_coalesce_and_explicit_refresh_fetches_again(env,monkeypatch):
    app,_=env;p=get_preset('whu-unit-xgbnew');calls=[]
    async def handler(request):
        calls.append(str(request.url));await asyncio.sleep(.1)
        return httpx.Response(200,headers={'content-type':'text/html','set-cookie':'JSESSIONID=anonymous'},
            text='<ul><li><a href="/info/4201/1.htm">学校公开通知一</a></li></ul>')
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(source_fetch,'WHU_GROUP_INTERVAL',0)
    config=source_sync.Subscription(url=p['url'],article_path_prefix=p['article_path_prefix'],preset_id=p['id']).model_dump(exclude={'enabled','version'})
    async def fetch(*,force=False):
        with source_fetch.acquisition(app.state.db,config,hosts=['xgbnew.whu.edu.cn'],bypass_shared=force):
            return await source_sync.fetch_index(config)
    async def run():
        first,second=await asyncio.gather(fetch(),fetch())
        assert len(first)==len(second)==1 and len(calls)==1
        assert (await fetch(force=True))[0]['title']=='学校公开通知一'
    asyncio.run(run())
    assert len(calls)==2


def test_public_attachment_is_shared_without_sharing_source_ids(env,monkeypatch):
    from app.db import ident
    app,_=env;p=get_preset('whu-unit-future');calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,headers={'content-type':'application/pdf','set-cookie':'JSESSIONID=anonymous'},content=b'%PDF-synthetic')
    def parse(name,data,*,expanded=False):
        return {'id':ident(),'name':name,'kind':'pdf','content':data,'sha256':'sample',
                'sections':[{'locator':'1','text':'公开附件'}],'status':'ok','warning':''}
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(notice_intake,'file_source',parse)
    monkeypatch.setattr(source_fetch,'WHU_GROUP_INTERVAL',0)
    config=source_sync.Subscription(url=p['url'],article_path_prefix=p['article_path_prefix'],preset_id=p['id']).model_dump(exclude={'enabled','version'})
    url='https://future.whu.edu.cn/files/sample.pdf';parent='https://future.whu.edu.cn/content.jsp?urltype=news.NewsContentUrl&wbtreeid=1&wbnewsid=2'
    async def run():
        result=[]
        for _ in range(2):
            with source_fetch.acquisition(app.state.db,config,hosts=['future.whu.edu.cn']):
                source,_=await notice_intake._read_link(url,allowed_host='future.whu.edu.cn',referrer=parent,expanded=True)
                result.append(source)
        assert result[0]['content']==result[1]['content']==b'%PDF-synthetic'
        assert result[0]['id']!=result[1]['id']
    asyncio.run(run())
    assert len(calls)==1


def test_only_the_owner_can_retry_local_verification(env,monkeypatch):
    app,cfg=env;a,b=account(env),account(env,'second')
    with successful_rule_trial():result=a.post('/api/source-presets/whu-unit-future/subscribe',json={})
    assert result.status_code==200,result.text
    sid=result.json()['source_id']
    with app.state.db.connect(write=True) as conn:
        conn.execute('INSERT OR REPLACE INTO source_host_limits(hostname,retry_after) VALUES(?,?)',
                     (source_fetch.WHU_GROUP_KEY,9999999999))
    async def checked(db,source_id,uid,force=False):return {'source_id':source_id,'enabled':True}
    monkeypatch.setattr(source_sync,'sync_source',checked)
    assert b.post('/api/source-catalog/'+sid+'/verification-finished').status_code==404
    cfg.production=True
    assert a.post('/api/source-catalog/'+sid+'/verification-finished').status_code==403
    cfg.production=False
    assert a.post('/api/source-catalog/'+sid+'/verification-finished').status_code==200
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT retry_after FROM source_host_limits WHERE hostname=?',(source_fetch.WHU_GROUP_KEY,)).fetchone()[0]==0


def test_restoring_backup_discards_stale_shared_collection_leases(env,tmp_path):
    from app.backups import restore_database
    app,cfg=env
    with app.state.db.connect(write=True) as conn:
        conn.execute('INSERT INTO school_public_leases VALUES(?,?,?)',('cache-key','old-process',9999999999))
    target=tmp_path/'restored'/'campus.sqlite3'
    restore_database(cfg.data_dir/'campus.sqlite3',target)
    import sqlite3
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT count(*) FROM school_public_leases').fetchone()[0]==0
