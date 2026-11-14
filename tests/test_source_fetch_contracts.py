"""Public source transport tests use synthetic HTTP; no external delivery."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi import HTTPException

from app import notice_intake,source_sync
from app.source_fetch import CachedPublicTransport,acquisition,CONTEXT
from tests.test_source_subscriptions import website
from tests.test_workflow import account,env
from tests.source_trial_fixture import successful_rule_trial

FEED='https://feeds.example.org/whu/notices'
ARTICLE='https://school.example.edu.cn/info/one'


def enable_feed(client,sid,**changes):
    payload={'url':FEED,'mode':'feed','allowed_article_origins':['https://school.example.edu.cn'],
        'source_identity':'合成学院官网','article_path_prefix':'/info/',**changes}
    with successful_rule_trial():return client.put('/api/source-catalog/'+sid+'/subscription',json=payload)


def mock_readers(monkeypatch,handler):
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))


def test_trusted_cross_origin_feed_public_cache_and_304_owner_separation(env,monkeypatch):
    a,b=account(env),account(env,'second');sa,sb=website(a),website(b)
    assert enable_feed(a,sa).status_code==enable_feed(b,sb).status_code==200
    seen=[]
    def handler(request):
        seen.append((str(request.url),dict(request.headers)))
        if request.headers.get('if-none-match')=='"v1"':return httpx.Response(304,headers={'etag':'"v1"'})
        body=f'<rss><channel><item><title>合成通知</title><guid>item-one</guid><link>{ARTICLE}</link></item></channel></rss>' if str(request.url)==FEED else '<html><title>合成通知</title><body>请核对报名材料。</body></html>'
        return httpx.Response(200,headers={'content-type':'application/rss+xml' if str(request.url)==FEED else 'text/html','etag':'"v1"'},text=body)
    mock_readers(monkeypatch,handler)
    first=a.post('/api/source-catalog/'+sa+'/refresh')
    assert first.status_code==200 and first.json()['state']=='active',first.text
    second=b.post('/api/source-catalog/'+sb+'/refresh')
    assert second.json()['state']=='active',second.text
    assert len(seen)==2 # one anonymous list + original, shared across subscribers
    na,nb=a.get('/api/notices').json()[0],b.get('/api/notices').json()[0]
    assert na['id']!=nb['id'] and b.get('/api/notices/'+na['id']).status_code==404
    provenance=a.get('/api/notices/'+na['id']).json()['sources'][0]['origin']
    assert provenance['feed_entry_id']=='item-one' and provenance['feed_service_url']==FEED
    assert provenance['source_identity']=='合成学院官网' and len(provenance['list_snapshot_sha256'])==64
    assert first.json()['feed_service_url']==FEED and first.json()['source_identity']=='合成学院官网'
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE source_public_cache SET checked_at=checked_at-60')
        conn.execute('UPDATE source_host_limits SET next_allowed=0')
    again=a.post('/api/source-catalog/'+sa+'/refresh')
    assert again.json()['state']=='active' and again.json()['updated_count']==0,again.text
    assert len(seen)==4 and all(h.get('if-none-match')=='"v1"' for _,h in seen[2:])
    assert again.json()['coverage']['list']['snapshot']['acquisition']=='revalidated'


def test_feed_scope_rejections_and_redirect_are_blocked_before_network(env,monkeypatch):
    a=account(env);sid=website(a)
    assert enable_feed(a,sid,allowed_article_origins=[]).status_code==422
    assert enable_feed(a,sid,allowed_article_origins=['https://*.edu.cn']).status_code==422
    assert enable_feed(a,sid,allowed_article_origins=['http://127.0.0.1']).status_code==422
    assert enable_feed(a,sid).status_code==200
    seen=[]
    def handler(request):
        url=str(request.url);seen.append(url)
        if url==FEED:
            return httpx.Response(200,headers={'content-type':'application/rss+xml'},text=f'<rss><channel><item><title>授权通知</title><link>{ARTICLE}</link></item><item><title>越界通知</title><link>https://other.example.net/private</link></item></channel></rss>')
        if url==ARTICLE:return httpx.Response(302,headers={'location':'https://other.example.net/redirected'})
        pytest.fail('Unauthorised redirect was fetched: '+url)
    mock_readers(monkeypatch,handler)
    response=a.post('/api/source-catalog/'+sid+'/refresh')
    assert response.status_code==200,response.text
    data=response.json()
    assert data['health_state']=='partial' and data['coverage']['articles']['failed']==1
    assert len(data['coverage']['rejected_entries'])==1 and seen==[FEED,ARTICLE]
    assert a.get('/api/notices').json()==[]


def test_valid_empty_feed_differs_from_broken_html():
    config={'url':FEED,'mode':'feed'}
    rows=source_sync.parse_index('<rss><channel><title>空栏目</title></channel></rss>',FEED,config)
    assert rows==[] and rows.empty_confirmed
    with pytest.raises(HTTPException):source_sync.parse_index('<html>维护</html>',FEED,config)
    with pytest.raises(HTTPException):source_sync.parse_index('<html>没有正文</html>',FEED,{'url':FEED,'mode':'html','article_path_prefix':'/info/'})


def test_atom_uses_alternate_link_and_retains_entry_identity():
    xml=f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>urn:whu:one</id><title>标题</title><link rel="self" href="https://feeds.example.org/api/one"/><link rel="alternate" href="{ARTICLE}"/></entry></feed>'
    result=source_sync.parse_index(xml,FEED,{'url':FEED,'mode':'feed','allowed_article_origins':['https://school.example.edu.cn']})
    assert result[0]['url']==ARTICLE and result[0]['feed_entry_id']=='urn:whu:one'


def test_retry_after_is_durable_and_not_reset_by_force_refresh(env,monkeypatch):
    a=account(env);sid=website(a);enable_feed(a,sid);seen=[]
    def handler(request):seen.append(str(request.url));return httpx.Response(429,headers={'Retry-After':'7200'},text='later')
    mock_readers(monkeypatch,handler)
    first=a.post('/api/source-catalog/'+sid+'/refresh').json()
    assert first['next_poll']>=int(time.time())+7100 and first['state']=='error'
    a.post('/api/source-catalog/'+sid+'/refresh')
    assert seen==[FEED]


def test_same_domain_waiter_does_not_block_other_domain(monkeypatch):
    async def scenario():
        release=asyncio.Event();started=[]
        async def sync(db,sid):
            started.append(sid)
            if sid=='slow':await release.wait()
            if sid=='other':release.set()
        monkeypatch.setattr(source_sync,'sync_source',sync)
        rows=[{'source_id':sid,'config':json.dumps({'url':host})} for sid,host in [('slow','https://a.example.edu.cn'),('same','https://a.example.edu.cn'),('other','https://b.example.edu.cn')]]
        await asyncio.wait_for(source_sync.poll_batch(None,rows),1)
        assert started.index('other')<started.index('same')
    asyncio.run(scenario())


def test_rule_trial_apply_rollback_are_isolated_versioned_and_owner_scoped(env,monkeypatch):
    from app.documents import text_source
    from tests.test_source_subscriptions import enable
    a,b=account(env),account(env,'rule-outsider');sid=website(a);current=enable(a,sid)
    base='/api/source-catalog/'+sid+'/subscription'
    async def index(config):return [{'url':ARTICLE,'title':'合成规则样本','published_at':None}]
    async def read(url):
        source=text_source('合成原文：请本人核对要求。');source['origin']={'url':url,'attachments':[]}
        return source,'合成规则样本'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    payload={**current['config'],'version':current['version'],'interval_minutes':60,'enabled':False}
    trial=a.post(base+'/preview',json=payload)
    assert trial.status_code==200 and trial.json()['can_apply'],trial.text
    assert a.get('/api/notices').json()==[] and a.get('/api/source-subscriptions').json()[0]['version']==1
    approval={'trial_id':trial.json()['trial_id'],'version':1,'enabled':False}
    assert b.post(base+'/apply',json=approval).status_code==404
    assert a.post(base+'/apply',json={**approval,'version':0}).status_code==409
    applied=a.post(base+'/apply',json=approval)
    assert applied.status_code==200 and applied.json()['version']==2 and not applied.json()['enabled'],applied.text
    replay=a.post(base+'/apply',json=approval)
    assert replay.status_code==200 and replay.json()['version']==2
    assert a.post(base+'/apply',json={**approval,'enabled':True}).status_code==409
    assert [item['version'] for item in a.get(base+'/rules').json()['versions']]==[2,1]
    async def broken(config):raise HTTPException(502,'栏目改版，原规则尚不能读取')
    monkeypatch.setattr(source_sync,'fetch_index',broken)
    assert a.post(base+'/rollback',json={'version':2,'restore_version':1}).status_code==422
    assert a.get('/api/source-subscriptions').json()[0]['version']==2
    monkeypatch.setattr(source_sync,'fetch_index',index)
    restored=a.post(base+'/rollback',json={'version':2,'restore_version':1})
    assert restored.status_code==200,restored.text
    assert restored.json()['version']==3 and restored.json()['config']['interval_minutes']==30
    assert not restored.json()['enabled'] and a.get('/api/notices').json()==[]


def test_empty_feed_trial_does_not_claim_an_article_rule_is_verified(env,monkeypatch):
    a=account(env);sid=website(a)
    async def empty(config):return source_sync.IndexEntries(empty_confirmed=True)
    monkeypatch.setattr(source_sync,'fetch_index',empty)
    payload={'url':FEED,'mode':'feed','allowed_article_origins':['https://school.example.edu.cn'],'source_identity':'合成学校'}
    base='/api/source-catalog/'+sid+'/subscription'
    trial=a.post(base+'/preview',json=payload)
    assert trial.status_code==200,trial.text
    assert not trial.json()['can_apply'] and trial.json()['list']['empty_confirmed']
    assert a.post(base+'/apply',json={'version':0,'trial_id':trial.json()['trial_id']}).status_code==422
    assert a.get('/api/source-subscriptions').json()[0]['state']=='manual'


def test_source_failure_projection_is_owner_scoped_stable_and_paused_sources_stop(env,monkeypatch):
    from tests.test_source_subscriptions import enable
    a,b=account(env),account(env,'source-health-other');sid=website(a);enable(a,sid)
    async def failed(config):raise HTTPException(502,'来源返回 HTTP 403，本次未完成同步')
    monkeypatch.setattr(source_sync,'fetch_index',failed)
    a.post('/api/source-catalog/'+sid+'/refresh')
    uid=a.get('/api/session').json()['user']['id'];other=b.get('/api/session').json()['user']['id']
    with env[0].state.db.connect() as conn:
        first=source_sync.recent_failures(conn,uid)
        assert len(first)==1 and first[0]['in_app_only'] and first[0]['failure_kind']=='access_denied'
        assert not source_sync.recent_failures(conn,other)
    current=a.post('/api/source-catalog/'+sid+'/refresh').json()
    with env[0].state.db.connect() as conn:assert source_sync.recent_failures(conn,uid)[0]['problem_version']==first[0]['problem_version']
    from app.documents import text_source
    async def recovered(config):return [{'url':ARTICLE,'title':'合成恢复样本','published_at':None}]
    async def read(url):
        source=text_source('来源恢复后的合成原文');source['origin']={'url':url,'attachments':[]}
        return source,'合成恢复样本'
    monkeypatch.setattr(source_sync,'fetch_index',recovered);monkeypatch.setattr(source_sync,'read_link',read)
    assert a.post('/api/source-catalog/'+sid+'/refresh').json()['state']=='active'
    monkeypatch.setattr(source_sync,'fetch_index',failed)
    current=a.post('/api/source-catalog/'+sid+'/refresh').json()
    with env[0].state.db.connect() as conn:assert source_sync.recent_failures(conn,uid)[0]['problem_version']!=first[0]['problem_version']
    a.put('/api/source-catalog/'+sid+'/subscription',json={**current['config'],'version':current['version'],'enabled':False})
    with env[0].state.db.connect() as conn:assert not source_sync.recent_failures(conn,uid)


def test_direct_configuration_requires_real_trial_and_failed_change_keeps_active_rule(env,monkeypatch):
    from tests.test_source_subscriptions import enable
    a=account(env);sid=website(a);base='/api/source-catalog/'+sid+'/subscription'
    called=[]
    async def broken(config):called.append(config['url']);raise HTTPException(502,'来源无法读取，合成失败')
    monkeypatch.setattr(source_sync,'fetch_index',broken)
    config={'url':'https://school.example.edu.cn/notices/','mode':'html','article_path_prefix':'/info/','interval_minutes':30}
    failed=a.put(base,json=config)
    assert failed.status_code==422 and len(called)==1,failed.text
    before=a.get('/api/source-subscriptions').json()[0]
    assert not before['enabled'] and before['state']=='manual' and before['last_trial']
    verified=enable(a,sid)
    assert verified['version']==1 and verified['enabled']
    # A lost successful response can be retried without another fetch/version.
    replay=a.put(base,json={**config,'version':0})
    assert replay.status_code==200 and replay.json()['version']==1 and len(called)==1
    changed=a.put(base,json={**config,'version':1,'interval_minutes':60})
    assert changed.status_code==422 and len(called)==2
    current=a.get('/api/source-subscriptions').json()[0]
    assert current['version']==1 and current['enabled'] and current['config']['interval_minutes']==30
    paused=a.put(base,json={**config,'version':1,'enabled':False})
    assert paused.status_code==200 and not paused.json()['enabled'] and len(called)==2
    resumed=a.put(base,json={**config,'version':2,'enabled':True})
    assert resumed.status_code==422 and len(called)==3
    assert not a.get('/api/source-subscriptions').json()[0]['enabled']


def test_first_preset_activation_does_not_bypass_failed_body_trial(env,monkeypatch):
    a=account(env)
    async def broken(config):raise HTTPException(502,'合成官网连接失败')
    monkeypatch.setattr(source_sync,'fetch_index',broken)
    result=a.post('/api/source-presets/whu-notices/subscribe',json={})
    assert result.status_code==422,result.text
    sources=a.get('/api/source-subscriptions').json()
    assert len(sources)==1 and not sources[0]['enabled'] and sources[0]['state']=='manual'
    assert a.get('/api/notices').json()==[]
