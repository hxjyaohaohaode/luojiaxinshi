import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app import source_fetch,source_sync
from app.official_sources import get_preset,parse_official_article,parse_official_index
from tests.test_workflow import env


def test_first_clinical_column_and_body_keep_scope_date_and_attachment():
    preset=get_preset('whu-college-rmhospital');url=preset['url']
    page='''<nav><a href="/article/id/9.html">不能混入导航</a></nav><div class="innoticelist">
      <li><div class="date"><span class="day">05</span><span class="mon">2026-11</span></div>
      <a href="/article/id/17304.html" title="查看详细">临床学院招生通知</a></li>
      <li><a href="https://other.example/article/id/2.html">站外链接</a></li></div>'''
    entries=parse_official_index(page,url,preset['id'])
    assert entries==[{'url':'https://www.rmhospital.com/article/id/17304.html','title':'临床学院招生通知','published_at':'2026-11-05'}]
    body='''<nav>不能混入导航</nav><div class="contentout"><div class="title">临床学院招生通知</div>
      <div class="newsinfo">时间：2026-11-05</div><div class="content"><p>请核对招生要求。</p>
      <a href="/files/application.pdf">申请表.pdf</a></div></div>'''
    source=parse_official_article(body,entries[0]['url'])
    assert source['title']=='临床学院招生通知' and source['published_at']=='2026-11-05'
    assert '不能混入导航' not in source['text']
    assert source['attachments']==['https://www.rmhospital.com/files/application.pdf']


def test_second_clinical_column_and_body_keep_scope_date_and_attachment():
    preset=get_preset('whu-college-znhospital');url=preset['url']
    page='''<div id="datalist"><div class="list"><div class="item">
      <a href="/graduate_student_notice_detail/18090.html"><div class="t1">学院奖学金公示</div>
      <div class="t2">列表摘要不能当成标题或正文</div><div class="t3">2026-11-06</div></a></div></div></div>'''
    entries=parse_official_index(page,url,preset['id'])
    assert entries[0]['title']=='学院奖学金公示' and entries[0]['published_at']=='2026-11-06'
    body='''<div class="article-page"><div class="article-head"><div class="t">学院奖学金公示</div>
      <span class="s4">2026-11-06</span></div><div class="article-cont"><p>请核对公示信息。</p>
      <a href="/Uploads/result.xlsx">名单.xlsx</a></div></div>'''
    source=parse_official_article(body,entries[0]['url'])
    assert source['title']=='学院奖学金公示' and source['published_at']=='2026-11-06'
    assert source['attachments']==['https://www.znhospital.cn/Uploads/result.xlsx']


@pytest.mark.parametrize(('pid','status'),[('whu-college-rmhospital',521),('whu-college-znhospital',412)])
def test_hospital_restriction_is_not_reported_as_a_working_subscription(pid,status,monkeypatch):
    preset=get_preset(pid)
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(lambda request:httpx.Response(status)))
    config=source_sync.Subscription(url=preset['url'],article_path_prefix=preset['article_path_prefix'],preset_id=pid).model_dump(exclude={'enabled','version'})
    with pytest.raises(HTTPException,match='需院方允许'):
        asyncio.run(source_sync.fetch_index(config))


def test_blocked_hospital_is_not_repeatedly_hit_for_other_subscribers(env,monkeypatch):
    preset=get_preset('whu-college-rmhospital');seen=[]
    def handler(request):
        seen.append(str(request.url));return httpx.Response(521)
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    config=source_sync.Subscription(url=preset['url'],article_path_prefix=preset['article_path_prefix'],preset_id=preset['id']).model_dump(exclude={'enabled','version'})
    async def run():
        for _ in range(2):
            with source_fetch.acquisition(env[0].state.db,config,hosts=['www.rmhospital.com']):
                with pytest.raises(HTTPException,match='需院方允许'):
                    await source_sync.fetch_index(config)
    asyncio.run(run())
    assert len(seen)==1
