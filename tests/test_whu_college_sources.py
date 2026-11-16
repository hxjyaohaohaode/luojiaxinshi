"""Synthetic contracts for the official university college source catalogue."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import HTTPException

from app import notice_intake, source_sync
from app.documents import text_source
from app.official_sources import PRESETS, get_preset, parse_official_article, parse_official_index
from tests.source_trial_fixture import successful_rule_trial
from tests.test_source_subscriptions import website
from tests.test_workflow import account, env


def test_catalog_covers_official_colleges_and_keeps_restricted_sites_manual():
    presets={p['id']:p for p in PRESETS}
    assert {'whu-college-sim','whu-college-physics','whu-college-robotics',
            'whu-college-whuss','whu-college-rmhospital','whu-college-znhospital',
            'whu-unit-gs','whu-unit-future','whu-unit-nic'}.issubset(presets)
    assert presets['whu-college-rmhospital']['adapter']=='clinical'
    assert presets['whu-college-znhospital']['adapter']=='clinical'
    for p in presets.values():
        host=urlsplit(p['url']).hostname
        assert host.endswith('.whu.edu.cn') or host in {'www.whuss.com','www.rmhospital.com','www.znhospital.cn'}
    directory=json.loads((Path(__file__).resolve().parents[1]/'fixtures/official-sources/whu-college-directory-2026-11.json').read_text(encoding='utf-8'))
    assert len(directory)==43
    for unit in directory:
        name=unit['name'] if unit['name'].startswith('武汉大学') else '武汉大学'+unit['name']
        host=urlsplit(unit['home']).hostname
        assert any(p['institution']==name and urlsplit(p['url']).hostname==host for p in presets.values()),unit['name']


def test_college_list_limits_links_to_the_verified_list_and_host():
    preset=get_preset('whu-college-sim');url=preset['url']
    page='''<nav><ul><li><a href="/info/1775/999.htm">导航里的文章不能混入</a></li></ul></nav>
      <ul><li><a href="/info/1775/111.htm" title="真实通知一">短标题</a><span>2026-11-12</span></li>
      <li><a href="/content.jsp?urltype=news.NewsContentUrl&amp;wbtreeid=1775&amp;wbnewsid=222">真实通知二</a>2026.11.13</li>
      <li><a href="/content.jsp?urltype=news.NewsContentUrl&amp;wbtreeid=1775&amp;wbnewsid=111">真实通知一的另一地址</a></li>
      <li><a href="https://other.example/info/1775/3.htm">校外文章不能混入</a></li></ul>'''
    rows=parse_official_index(page,url,preset['id'])
    assert [x['title'] for x in rows]==['真实通知一','真实通知二']
    assert [x['published_at'] for x in rows]==['2026-11-12','2026-11-13']
    assert all(urlsplit(x['url']).hostname=='sim.whu.edu.cn' for x in rows)


def test_college_body_extracts_original_attachment_without_navigation():
    url='https://sim.whu.edu.cn/info/1775/111.htm'
    page='''<meta name="ArticleTitle" content="学院通知"><meta name="PubDate" content="2026-11-12 08:00">
      <nav>不能混入的导航</nav><div id="vsb_content_100"><div class="v_news_content">
      <p>请同学核对申请要求。</p><a href="/system/_content/download.jsp?id=1">申请表.docx</a></div></div>'''
    result=parse_official_article(page,url)
    assert result['title']=='学院通知' and result['published_at']=='2026-11-12'
    assert '请同学核对申请要求' in result['text'] and '不能混入' not in result['text']
    assert result['attachments']==['https://sim.whu.edu.cn/system/_content/download.jsp?id=1']
    pdf=page.replace('<p>请同学核对申请要求。</p><a href="/system/_content/download.jsp?id=1">申请表.docx</a>',
                     '<script>showVsbpdfIframe("/__local/notice.pdf","100%","600","0","",[]);</script>')
    result=parse_official_article(pdf,url)
    assert result['attachment_only'] and result['attachments']==['https://sim.whu.edu.cn/__local/notice.pdf']


@pytest.mark.parametrize(('location','reason'),[
    ('/system/resource/code/auth/caslogin.jsp','需要登录'),
    ('/system/resource/visitcode/visitcode.jsp?backUrl=abc','要求访问验证'),
])
def test_login_or_verification_redirect_is_not_collected_as_a_public_notice(monkeypatch,location,reason):
    requested=[]
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302,headers={'location':location})
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    with pytest.raises(HTTPException,match=reason):
        asyncio.run(notice_intake.read_link('https://gs.whu.edu.cn/info/1065/1.htm'))
    assert len(requested)==1


def test_list_verification_redirect_is_reported_before_reading_it(monkeypatch):
    requested=[]
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302,headers={'location':'/system/resource/visitcode/visitcode.jsp?backUrl=abc'})
    monkeypatch.setattr(source_sync,'transport',lambda _:httpx.MockTransport(handler))
    with pytest.raises(HTTPException,match='要求访问验证'):
        asyncio.run(source_sync.fetch_index({'url':'https://xgbnew.whu.edu.cn/2025/list.jsp','mode':'html','article_path_prefix':'/2025/content.jsp'}))
    assert len(requested)==1


def test_trial_skips_restricted_samples_but_records_their_reason(env,monkeypatch):
    client=account(env);sid=website(client);uid=client.get('/api/session').json()['user']['id']
    entries=[{'url':f'https://school.example.edu.cn/info/{i}.htm','title':f'通知{i}','published_at':None} for i in range(3)]
    async def index(config):return entries
    async def read(url):
        if url==entries[0]['url']:raise HTTPException(422,'这则通知需要登录')
        source=text_source('公开通知正文');source['origin']={'url':url,'attachments':[]};return source,'公开通知'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    result=asyncio.run(source_sync.trial_rule(env[0].state.db,sid,uid,
        {'url':'https://school.example.edu.cn/notices/','mode':'html','article_path_prefix':'/info/'},0))
    assert result['can_apply'] and len(result['articles'])==2
    assert result['sample_errors'][0]['reason']=='这则通知需要登录'
    assert client.get('/api/notices').json()==[]


def test_bulk_subscription_trials_each_source_without_enabling_ai(env,monkeypatch):
    a,b=account(env),account(env,'second')
    async def index(config):
        host=urlsplit(config['url']).hostname
        return [{'url':f'https://{host}/info/1/{i}.htm','title':f'公开通知{i}','published_at':None} for i in (1,2)]
    async def read(url):
        source=text_source('公开通知正文');source['origin']={'url':url,'attachments':[]};return source,'公开通知'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    ids=['whu-college-sim','whu-college-physics','whu-college-sim-zszp','missing']
    response=a.post('/api/source-presets/bulk-subscribe',json={'preset_ids':ids})
    assert response.status_code==200,response.text
    results={item['id']:item for item in response.json()['results']}
    assert results[ids[0]]['state']==results[ids[1]]['state']=='added'
    assert results[ids[2]]['state']=='manual' and results[ids[3]]['state']=='failed'
    assert len(a.get('/api/source-catalog').json())==2 and b.get('/api/source-catalog').json()==[]
    assert a.get('/api/notice-automation').json()['enabled'] is False
    again=a.post('/api/source-presets/bulk-subscribe',json={'preset_ids':ids[:2]})
    assert all(item['state']=='existing' for item in again.json()['results'])


def test_first_background_pass_advances_to_other_colleges_before_draining_backlog(env,monkeypatch):
    client=account(env);uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    with successful_rule_trial():
        response=client.post('/api/source-presets/whu-college-sim/subscribe',json={})
    assert response.status_code==200,response.text
    sid=response.json()['source_id']
    entries=[{'url':f'https://sim.whu.edu.cn/info/1775/{i}.htm','title':f'通知{i}','published_at':None} for i in range(10)]
    async def index(config):return entries
    async def read(url):
        source=text_source('通知正文 '+url);source['origin']={'url':url,'attachments':[]};return source,'公开通知'
    monkeypatch.setattr(source_sync,'fetch_index',index);monkeypatch.setattr(source_sync,'read_link',read)
    first=asyncio.run(source_sync.sync_source(db,sid,uid))
    assert first['received_count']==2 and first['pending_count']==8
    with db.connect(write=True) as conn:conn.execute('UPDATE source_subscriptions SET next_poll=0 WHERE source_id=?',(sid,))
    second=asyncio.run(source_sync.sync_source(db,sid,uid))
    assert second['received_count']==10 and second['pending_count']==0
