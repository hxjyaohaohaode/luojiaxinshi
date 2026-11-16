from fastapi import HTTPException

from app import notice_automation,notice_network,source_sync
from app.documents import text_source
from app.official_sources import get_preset
from tests.test_source_subscriptions import enable,website
from tests.test_workflow import account,env


def test_category_survives_edits_from_an_older_client(env):
    client=account(env)
    added=client.post('/api/source-catalog',json={'name':'资料来源','platform':'website',
        'url':'https://school.example.edu.cn/notice/','category':'教务教学'})
    assert added.status_code==200
    sid=added.json()['id'];item=client.get('/api/source-catalog').json()[0]
    assert item['data']['category']=='教务教学'
    changed=client.put('/api/source-catalog/'+sid,json={'name':'改名后的来源','platform':'website',
        'url':'https://school.example.edu.cn/notice/','version':item['version']})
    assert changed.status_code==200
    item=client.get('/api/source-catalog').json()[0]
    assert item['data']['name']=='改名后的来源' and item['data']['category']=='教务教学'


def test_official_list_link_is_delivered_when_article_is_unreadable(env,monkeypatch):
    client=account(env);app,cfg=env;preset=get_preset('whu-undergrad-student')
    article='https://uc.whu.edu.cn/info/1517/1234.htm'
    entries=[{'url':article,'title':'学生事务通知','published_at':'2026-11-01'}]
    async def index(config):return entries
    async def unreadable(url):raise HTTPException(422,'网站要求访问验证')
    monkeypatch.setattr(source_sync,'fetch_index',index)
    monkeypatch.setattr(source_sync,'read_link',unreadable)
    created=client.post('/api/source-presets/'+preset['id']+'/subscribe',json={})
    assert created.status_code==200,created.text
    sid=created.json()['source_id'];result=client.post('/api/source-catalog/'+sid+'/refresh')
    assert result.status_code==200,result.text
    assert result.json()['delivery_issues'][0]['delivery_kind']=='link_only'
    notices=client.get('/api/notices').json();assert len(notices)==1
    notice=client.get('/api/notices/'+notices[0]['id']).json()
    assert notice['source_url']==article and notice['sources'][0]['origin']['list_only']
    assert '不是通知正文' in notice['sources'][0]['sections'][0]['text']
    current=client.get('/api/notice-automation').json()
    assert client.put('/api/notice-automation',json={'enabled':True,'allow_external_processing':True,
        'daily_limit':10,'version':current['version']}).status_code==200
    assert notice_automation.run_once(app,app.state.db,cfg) is None
    async def readable(url):
        source=text_source('真正从官网读到的正文','学生事务通知')
        source['origin']={'url':url,'attachments':[],'warnings':[]}
        return source,'学生事务通知'
    monkeypatch.setattr(source_sync,'read_link',readable)
    assert client.post('/api/source-catalog/'+sid+'/refresh').status_code==200
    upgraded=client.get('/api/notices/'+notices[0]['id']).json()
    assert any(s['active'] and any('真正从官网读到的正文' in part['text'] for part in s['sections']) for s in upgraded['sources'])
    async def missing_page(url):raise HTTPException(422,'原网页返回 HTTP 404')
    monkeypatch.setattr(source_sync,'read_link',missing_page)
    failed=client.post('/api/source-catalog/'+sid+'/refresh')
    assert failed.status_code==200 and failed.json()['delivery_issues'][0]['delivery_kind']=='unavailable'
    retained=client.get('/api/notices/'+notices[0]['id']).json()
    assert any(s['active'] and any('真正从官网读到的正文' in part['text'] for part in s['sections']) for s in retained['sources'])


def test_related_search_problem_does_not_look_like_failed_delivery(env,monkeypatch):
    client=account(env);sid=website(client);enable(client,sid)
    url='https://school.example.edu.cn/info/100/1.htm'
    async def index(config):return [{'url':url,'title':'正式通知','published_at':None}]
    async def read(target):
        source=text_source('已收到的通知正文','正式通知');source['origin']={'url':target,'attachments':[]}
        return source,'正式通知'
    async def related(source,config,entries,**kwargs):
        source['origin']['related_search']={'errors':[{'error':'关联候选暂时不可用'}]}
        return [source]
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    monkeypatch.setattr(notice_network,'read_network',related)
    response=client.post('/api/source-catalog/'+sid+'/refresh');assert response.status_code==200
    state=response.json()
    assert state['issue_count']==1 and state['delivery_issue_count']==0
    assert state['issues'][0]['delivery_kind']=='supplemental'


def test_known_missing_official_page_is_not_presented_as_a_received_link(env,monkeypatch):
    client=account(env);preset=get_preset('whu-undergrad-student')
    async def index(config):return [{'url':'https://uc.whu.edu.cn/info/1517/9999.htm','title':'失效通知','published_at':None}]
    async def readable(url):
        source=text_source('试读正文','通知');source['origin']={'url':url,'attachments':[]}
        return source,'通知'
    async def missing(url):raise HTTPException(422,'原网页返回 HTTP 404')
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',readable)
    created=client.post('/api/source-presets/'+preset['id']+'/subscribe',json={})
    assert created.status_code==200
    monkeypatch.setattr(source_sync,'read_link',missing)
    result=client.post('/api/source-catalog/'+created.json()['source_id']+'/refresh').json()
    assert result['delivery_issues'][0]['delivery_kind']=='unavailable'
    assert client.get('/api/notices').json()==[]


def test_a_column_with_only_known_dead_links_is_not_activated(env,monkeypatch):
    client=account(env);preset=get_preset('whu-undergrad-student')
    async def index(config):return [{'url':'https://uc.whu.edu.cn/info/1517/9999.htm','title':'失效通知','published_at':None}]
    async def missing(url):raise HTTPException(422,'原网页返回 HTTP 404')
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',missing)
    assert client.post('/api/source-presets/'+preset['id']+'/subscribe',json={}).status_code==422
    assert client.get('/api/notices').json()==[]


def test_missing_original_attachment_is_still_reported(env,monkeypatch):
    client=account(env);sid=website(client);enable(client,sid)
    url='https://school.example.edu.cn/info/100/1.htm';attachment='https://school.example.edu.cn/file.pdf'
    async def index(config):return [{'url':url,'title':'正式通知','published_at':None}]
    async def read(target):
        source=text_source('已收到的通知正文','正式通知');source['origin']={'url':target,'attachments':[attachment],
            'received_attachments':[],'attachment_reads':[{'url':attachment,'label':'材料.pdf','state':'unavailable'}]}
        return source,'正式通知'
    async def materials(source,config,entries,**kwargs):return [source]
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    monkeypatch.setattr(notice_network,'read_network',materials)
    state=client.post('/api/source-catalog/'+sid+'/refresh').json()
    assert state['delivery_issue_count']==1 and state['delivery_issues'][0]['delivery_kind']=='attachment'
    assert state['delivery_issues'][0]['url']==url
