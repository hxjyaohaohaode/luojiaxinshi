"""The school board is a labelled partial fallback, never a fabricated body."""
import httpx
from fastapi import HTTPException

from app import source_sync
from app.documents import text_source
from app.notice_automation import eligible
from app.whu_school_mirror import parse_page
from tests.test_workflow import account, env


def test_school_board_matches_publisher_not_just_a_title_or_external_link():
    html='''<table><tr><th>标题</th><th>发布单位</th><th>发布日期</th></tr>
    <tr><td><a href="/info/5231/1.htm" title="完整标题">缩略…</a></td><td>党委学生工作部</td><td>2026-11-01</td></tr>
    <tr><td><a href="/info/5231/2.htm">第一临床学院活动</a></td><td>其他单位</td><td>2026-11-02</td></tr>
    <tr><td><a href="/info/5231/3.htm">收费通知</a></td><td>财务部、校团委</td><td>2026-11-03</td></tr>
    <tr><td><a href="https://other.example/info/5231/4.htm">站外公告</a></td><td>财务部</td><td>2026-11-04</td></tr></table>
    <a href="/tzgg/260.htm">2</a><a href="https://other.example/tzgg/259.htm">3</a>'''
    entries,pages=parse_page(html,'https://www.whu.edu.cn/tzgg.htm')
    assert [item['title'] for item in entries]==['完整标题','收费通知']
    assert entries[0]['publisher']=='党委学生工作部' and entries[1]['published_at']=='2026-11-03'
    assert pages=={2:'https://www.whu.edu.cn/tzgg/260.htm'}


def test_list_only_receipt_recovers_body_and_never_overwrites_it(env,monkeypatch):
    client=account(env);app,cfg=env;uid=client.get('/api/session').json()['user']['id']
    url='https://www.whu.edu.cn/info/5231/267614.htm'
    entries=source_sync.IndexEntries([{'url':url,'title':'财务通知','published_at':'2026-04-23','publisher':'财务部'}])
    entries.snapshot={'url':'https://www.whu.edu.cn/tzgg.htm','sha256':'test-list','pages_checked':5}
    async def index(config):return entries
    async def unavailable(url):raise HTTPException(422,'网站要求访问验证')
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',unavailable)
    first=client.post('/api/source-presets/whu-school-target-notices/subscribe',json={})
    assert first.status_code==200,first.text
    sid=first.json()['source_id']
    again=client.post('/api/source-presets/whu-school-target-notices/subscribe',json={})
    assert again.json()['source_id']==sid
    refreshed=client.post('/api/source-catalog/'+sid+'/refresh')
    assert refreshed.status_code==200,refreshed.text
    assert refreshed.json()['coverage']['articles']['succeeded']==0
    assert refreshed.json()['coverage']['articles']['failed']==1
    notices=client.get('/api/notices').json();assert len(notices)==1
    detail=client.get('/api/notices/'+notices[0]['id']).json();nid=detail['id']
    stub=next(s for s in detail['sources'] if s['active'])
    assert stub['status']=='review' and stub['origin']['list_only']
    assert '不是通知正文' in ' '.join(s['text'] for s in stub['sections'])
    assert stub['origin']['listed_publisher']=='财务部' and '正文和附件未读取' in stub['warning']
    with app.state.db.connect() as conn:
        notice=conn.execute('SELECT * FROM notices WHERE id=?',(nid,)).fetchone()
        assert not eligible(conn,notice,cfg)
    assert not client.get('/api/notice-automation').json()['enabled']

    async def full(url):
        source=text_source('真实公告正文：请核对缴费安排。')
        source['origin']={'url':url,'attachments':[],'warnings':[]}
        return source,'财务通知'
    monkeypatch.setattr(source_sync,'read_link',full)
    upgraded=client.post('/api/source-catalog/'+sid+'/refresh')
    assert upgraded.status_code==200 and upgraded.json()['updated_count']==1
    detail=client.get('/api/notices/'+nid).json()
    active=next(s for s in detail['sources'] if s['active'])
    assert active['status']=='ok' and '真实公告正文' in active['sections'][0]['text']
    version=detail['version']

    monkeypatch.setattr(source_sync,'read_link',unavailable)
    client.post('/api/source-catalog/'+sid+'/refresh')
    preserved=client.get('/api/notices/'+nid).json()
    assert preserved['version']==version
    assert any(s['active'] and '真实公告正文' in s['sections'][0]['text'] for s in preserved['sources'])
    assert len(client.get('/api/notices').json())==1


def test_filtered_school_board_coexists_with_existing_school_subscription(env,monkeypatch):
    client=account(env)
    async def index(config):
        entries=source_sync.IndexEntries([{'url':'https://www.whu.edu.cn/info/5231/1.htm','title':'公告','published_at':None,'publisher':'财务部'}])
        entries.snapshot={'url':config['url'],'sha256':'sample'}
        return entries
    async def read(url):
        source=text_source('学校公开正文');source['origin']={'url':url,'attachments':[]};return source,'学校公告'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    original=client.post('/api/source-presets/whu-notices/subscribe',json={}).json()
    supplement=client.post('/api/source-presets/whu-school-target-notices/subscribe',json={}).json()
    assert original['source_id']!=supplement['source_id']
    assert len(client.get('/api/source-catalog').json())==2
    assert client.post('/api/source-presets/whu-notices/subscribe',json={}).json()['source_id']==original['source_id']
