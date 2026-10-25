"""Synthetic source/permission contracts; no network or real platform credentials."""
import json

from fastapi import HTTPException
import pytest

from app import source_sync
from app.documents import text_source
from tests.test_workflow import env, account
from tests.test_integrations import configured, event, bind


def website(c):
    response=c.post('/api/source-catalog',json={'name':'学院通知','platform':'website','url':'https://school.example.edu.cn/notices/'})
    assert response.status_code==200,response.text
    return response.json()['id']


def enable(c,sid,**overrides):
    payload={'url':'https://school.example.edu.cn/notices/','mode':'html','article_path_prefix':'/info/','enabled':True,'interval_minutes':30,**overrides}
    result=c.put('/api/source-catalog/'+sid+'/subscription',json=payload)
    assert result.status_code==200,result.text
    return result.json()


def test_subscription_discovers_updates_and_deduplicates_with_owner_isolation(env,monkeypatch):
    a,b=account(env),account(env,'bob');sid=website(a);enable(a,sid)
    assert b.post('/api/source-catalog/'+sid+'/refresh').status_code==404
    content=['报名截止 2027年10月20日，请提交申请表。']
    async def index(config):return [{'url':'https://school.example.edu.cn/info/100/1.htm','title':'报名通知','published_at':None}]
    async def read(url):
        source=text_source(content[0]);source['origin']={'url':url,'retrieved_at':1,'attachments':[],'warnings':[]}
        return source,'报名通知'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    r=a.post('/api/source-catalog/'+sid+'/refresh');assert r.status_code==200,r.text
    assert r.json()['received_count']==1 and r.json()['state']=='active'
    first=a.get('/api/notices').json();assert len(first)==1 and b.get('/api/notices').json()==[]
    assert a.post('/api/source-catalog/'+sid+'/refresh').json()['received_count']==1
    content[0]='报名截止改为 2027年10月22日，请提交申请表。'
    r=a.post('/api/source-catalog/'+sid+'/refresh');assert r.json()['updated_count']==1
    updated=a.get('/api/notices').json();assert len(updated)==1 and updated[0]['id']==first[0]['id']
    assert updated[0]['pending_intake_updates']==1
    assert a.get('/api/tasks').json()==[]
    content[0]='报名截止 2027年10月20日，请提交申请表。'
    reverted=a.post('/api/source-catalog/'+sid+'/refresh')
    assert reverted.json()['updated_count']==2
    assert len(a.get('/api/notices').json())==1


def test_subscription_error_pause_and_no_stale_write(env,monkeypatch):
    a=account(env);sid=website(a);enable(a,sid)
    async def broken(config):raise HTTPException(502,'来源维护中')
    monkeypatch.setattr(source_sync,'fetch_index',broken)
    r=a.post('/api/source-catalog/'+sid+'/refresh');assert r.status_code==200
    assert r.json()['state']=='error' and r.json()['error']=='来源维护中'
    assert not r.json()['succeeded_at']
    async def paused(config):
        with env[0].state.db.connect(write=True) as conn:
            conn.execute('UPDATE source_subscriptions SET enabled=0,version=version+1 WHERE source_id=?',(sid,))
        return [{'url':'https://school.example.edu.cn/info/1.htm','title':'迟到的通知','published_at':None}]
    monkeypatch.setattr(source_sync,'fetch_index',paused)
    assert a.post('/api/source-catalog/'+sid+'/refresh').status_code==200
    assert a.get('/api/notices').json()==[]
    assert a.get('/api/source-subscriptions').json()[0]['enabled'] is False
    # A previously open settings form cannot turn a newer paused setting on.
    stale=a.put('/api/source-catalog/'+sid+'/subscription',json={'url':'https://school.example.edu.cn/notices/','article_path_prefix':'/info/','version':1})
    assert stale.status_code==409


def test_subscription_scope_and_unchanged_old_catalog_are_checked(env,monkeypatch):
    a=account(env);sid=website(a)
    for changes in ({'url':'http://127.0.0.1/'},{'url':'https://different.example.edu.cn/notices/'},{'article_path_prefix':'/'}):
        response=a.put('/api/source-catalog/'+sid+'/subscription',json={'url':'https://school.example.edu.cn/notices/','article_path_prefix':'/info/',**changes})
        assert response.status_code==422
    enable(a,sid)
    with env[0].state.db.connect(write=True) as conn:
        catalog=json.loads(conn.execute('SELECT data FROM source_catalog WHERE id=?',(sid,)).fetchone()[0]);catalog['url']='https://changed.example.edu.cn/'
        conn.execute('UPDATE source_catalog SET data=?,version=version+1 WHERE id=?',(json.dumps(catalog),sid))
    async def no_network(config):pytest.fail('changed source fetched old host')
    monkeypatch.setattr(source_sync,'fetch_index',no_network)
    response=a.post('/api/source-catalog/'+sid+'/refresh')
    assert response.json()['enabled'] is False and '来源已改变' in response.json()['error']


def test_html_and_feed_discovery_do_not_traverse_other_hosts():
    url='https://school.example.edu.cn/notices/'
    config={'url':url,'mode':'html','article_path_prefix':'/info/'}
    rows=source_sync.parse_index('<a href="/info/1.htm">报名通知原文</a><a href="/about/">学校简介</a><a href="https://other.edu.cn/info/x">其他学校通知</a>',url,config)
    assert [r['url'] for r in rows]==['https://school.example.edu.cn/info/1.htm']
    rss='<rss><channel><item><title>学术讲座通知</title><link>https://school.example.edu.cn/info/2.htm</link><pubDate>Tue, 20 Oct 2026 08:00:00 +0800</pubDate></item></channel></rss>'
    rows=source_sync.parse_index(rss,url,{**config,'mode':'feed'})
    assert rows[0]['published_at']=='2026-10-20T00:00:00+00:00'
    with pytest.raises(HTTPException):source_sync.parse_index('<!DOCTYPE x><rss/>',url,{**config,'mode':'feed'})


def group_event(external,cfg,content,member='owner-id',role='owner',mid=None,group='private-group'):
    return event(external,cfg,content,mid=mid,t='GROUP_MESSAGE_CREATE',extra={'group_openid':group,'author':{'member_openid':member,'member_role':role}})


def test_group_requires_group_admin_and_each_members_own_signed_opt_in(env):
    a,b,c=account(env),account(env,'bob'),account(env,'charlie');external=configured(env);cfg=env[1]
    codes=a.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()
    assert group_event(external,cfg,codes['authorize_command'],role='member').status_code==200
    assert a.get('/api/integrations').json()['qq']['groups']==[]
    assert group_event(external,cfg,'未经授权群中的通知',mid='before').status_code==200
    assert a.get('/api/notices').json()==[]
    assert group_event(external,cfg,codes['authorize_command']).status_code==200
    bcode=b.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()
    assert group_event(external,cfg,bcode['command'],member='bob-member',role='member').status_code==200
    assert group_event(external,cfg,'请于2027年10月20日前报名',mid='notice-1').status_code==200
    assert len(a.get('/api/notices').json())==len(b.get('/api/notices').json())==1
    assert c.get('/api/notices').json()==[]
    assert group_event(external,cfg,'请于2027年10月20日前报名',mid='notice-1').status_code==200
    assert len(a.get('/api/notices').json())==1
    assert b.post('/api/integrations/qq/groups/private-group/disable').status_code==404
    assert b.delete('/api/integrations/qq/groups/private-group').status_code==200
    assert group_event(external,cfg,'第二项新通知请核对',mid='notice-2').status_code==200
    assert len(a.get('/api/notices').json())==2 and len(b.get('/api/notices').json())==1
    assert a.post('/api/integrations/qq/groups/private-group/disable').status_code==200
    assert group_event(external,cfg,'停止授权后的通知',mid='notice-3').status_code==200
    assert len(a.get('/api/notices').json())==2


def test_c2c_and_publisher_now_land_in_notice_inbox(env,monkeypatch):
    a=account(env,'admin','admin');external=configured(env);cfg=env[1];bind(a,external,cfg)
    assert event(external,cfg,'测试收件通知：请核对报名条件',mid='direct-1').status_code==200
    assert len(a.get('/api/notices').json())==1
    publisher=env[0].state.publisher_client
    content=['公众号报名通知正文']
    monkeypatch.setattr(publisher,'article',lambda aid,index:('公众号通知',text_source(content[0])))
    payload={'article_id':'fixture-pub','index':0}
    first=a.post('/api/integrations/wechat/import',json=payload);assert first.status_code==200,first.text
    assert first.json()['notice_id']
    repeated=a.post('/api/integrations/wechat/import',json=payload)
    assert repeated.json()['notice_id']==first.json()['notice_id'] and repeated.json()['already_imported']
    content[0]='公众号报名通知正文，更正报名截止时间'
    changed=a.post('/api/integrations/wechat/import',json=payload)
    assert changed.json()['updated'] and changed.json()['notice_id']==first.json()['notice_id']
    assert len(a.get('/api/notices').json())==2


def test_publisher_continuous_sync_keeps_cursor_updates_and_admin_scope(env,monkeypatch):
    a,b=account(env,'admin','admin'),account(env,'bob');cfg=env[1]
    cfg.wechat_publisher_app_id='authorized-publisher';cfg.wechat_publisher_secret='fixture-only'
    publisher=env[0].state.publisher_client
    assert b.get('/api/integrations/wechat/subscription').status_code==403
    assert b.put('/api/integrations/wechat/subscription',json={'enabled':True}).status_code==403
    settings={'enabled':True,'initial_pages':3,'interval_minutes':30,'version':0}
    assert a.put('/api/integrations/wechat/subscription',json=settings).status_code==200
    pages={0:{'items':[{'article_id':'a','index':0,'title':'第一则通知','updated_at':100}],'next_offset':10,'total':3},
           10:{'items':[{'article_id':'b','index':0,'title':'第二则通知','updated_at':101}],'next_offset':20,'total':3},
           20:{'items':[{'article_id':'c','index':0,'title':'第三则通知','updated_at':102}],'next_offset':None,'total':3}}
    calls=[];bodies={'a':'第一则通知原文','b':'第二则通知原文','c':'第三则通知原文'}
    def listing(offset):calls.append(offset);return pages[offset]
    monkeypatch.setattr(publisher,'articles',listing)
    monkeypatch.setattr(publisher,'article',lambda aid,index:(aid+'通知',text_source(bodies[aid])))
    for _ in range(3):
        r=a.post('/api/integrations/wechat/refresh');assert r.status_code==200,r.text
    assert calls==[0,10,20]
    assert len(a.get('/api/notices').json())==3 and b.get('/api/notices').json()==[]
    assert r.json()['remaining_pages']==0 and r.json()['cursor_offset'] is None
    bodies['a']='第一则通知原文已更正截止日期';pages[0]['items'][0]['updated_at']=200
    r=a.post('/api/integrations/wechat/refresh');assert r.json()['updated_count']==1
    assert len(a.get('/api/notices').json())==3
    assert sum(n['pending_intake_updates'] for n in a.get('/api/notices').json())==1
    assert a.put('/api/integrations/wechat/subscription',json=settings).status_code==409
    current=a.get('/api/integrations/wechat/subscription').json()
    assert a.put('/api/integrations/wechat/subscription',json={**settings,'enabled':False,'version':current['version']}).status_code==200
    assert a.post('/api/integrations/wechat/refresh').status_code==409


def test_publisher_failed_authorization_and_changed_app_do_not_silently_succeed(env,monkeypatch):
    a=account(env,'admin','admin');cfg=env[1];cfg.wechat_publisher_app_id='publisher-a';cfg.wechat_publisher_secret='fixture'
    publisher=env[0].state.publisher_client
    assert a.put('/api/integrations/wechat/subscription',json={'enabled':True}).status_code==200
    def failed(offset):raise HTTPException(502,'发布账号没有文章读取权限')
    monkeypatch.setattr(publisher,'articles',failed)
    r=a.post('/api/integrations/wechat/refresh')
    assert r.json()['state']=='error' and not r.json()['succeeded_at']
    assert a.get('/api/notices').json()==[]
    cfg.wechat_publisher_app_id='publisher-b'
    r=a.post('/api/integrations/wechat/refresh')
    assert not r.json()['enabled'] and '账号权限' in r.json()['error']


def test_departing_group_member_loses_future_delivery(env):
    a=account(env);external=configured(env);cfg=env[1]
    code=a.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()['authorize_command']
    group_event(external,cfg,code)
    assert a.get('/api/integrations').json()['qq']['groups']
    assert event(external,cfg,t='GROUP_MEMBER_REMOVE',extra={'group_openid':'private-group','member_openid':'owner-id'}).status_code==200
    assert a.get('/api/integrations').json()['qq']['groups']==[]
    group_event(external,cfg,'退出后不能再收到',mid='after-leave')
    assert a.get('/api/notices').json()==[]
