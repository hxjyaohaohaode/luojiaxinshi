"""Public evidence fidelity; live model output is never used as page evidence."""
import asyncio
from types import SimpleNamespace

import pytest

from app import evidence_web
from app.genui_ai import evidence_index


def test_utf8_page_survives_a_stale_gb2312_header():
    text='<meta charset="gb2312"><title>图书借阅办法</title><p>本科生借期30天。</p>'
    decoded,charset=evidence_web.decode_page(text.encode('utf-8'),'gb2312')
    assert decoded==text and charset=='utf-8'
    page=evidence_web.PageText();page.feed(decoded)
    assert ''.join(page.title_parts)=='图书借阅办法'
    assert any(p['text']=='本科生借期30天。' for p in page.sections()[0])


def test_real_gbk_and_utf8_bom_pages_keep_exact_chinese_text():
    text='<meta http-equiv="Content-Type" content="text/html; charset=gb2312"><p>续借从当天计算。</p>'
    assert evidence_web.decode_page(text.encode('gb18030'),'utf-8')[0]==text
    assert evidence_web.decode_page(('\ufeff'+text).encode('utf-8'),'gbk')[0]==text


def test_invalid_page_is_not_silently_accepted_as_replacement_text():
    with pytest.raises(ValueError):evidence_web.decode_page(b'\xff\xff\xff')


def test_explicit_public_url_is_read_even_without_search_annotations(monkeypatch):
    calls=[]
    async def read(url):
        calls.append(url);return {'url':url,'title':'官网真实标题','sections':[{'locator':'网页段落 1','text':'原始规则：30天。'}],'charset':'utf-8','limited':False}
    monkeypatch.setattr(evidence_web,'read_page',read)
    sources,report,usage=asyncio.run(evidence_web.search(SimpleNamespace(),[],['https://lib.whu.edu.cn/rules','http://127.0.0.1/private','https://not-in-readable-list.example/']))
    assert calls==['https://lib.whu.edu.cn/rules','https://not-in-readable-list.example/'] and report['pages_read']==2
    assert sources[0]['sections'][0]['text']=='原始规则：30天。'
    assert sources[0]['evidence_kind']=='web_page' and sources[0]['direct']


def test_each_native_query_keeps_its_site_constraint_and_counts_real_usage(monkeypatch):
    requests=[]
    async def complete(settings,request):
        requests.append(request)
        return {'content':'GENERATED_TEXT_IS_NOT_EVIDENCE','annotations':[
            {'type':'url_citation','url':'https://lib.whu.edu.cn/rules','title':'官网规则','summary':'仅搜索摘要'},
            {'type':'url_citation','url':'https://lib.other.edu.cn/rules','title':'他校规则','summary':'不得混入'}]}, {'prompt_tokens':3,'completion_tokens':2,'web_search_usage':{'tool_usage':1}}
    async def read(url):return None
    monkeypatch.setattr(evidence_web,'completion',complete);monkeypatch.setattr(evidence_web,'read_page',read)
    sources,report,usage=asyncio.run(evidence_web.search(SimpleNamespace(ai_model='test'),['site:lib.whu.edu.cn 借阅','site:lib.whu.edu.cn 续借']))
    assert len(requests)==2 and all(p['tools'][0]['max_keyword']==1 for p in requests)
    assert len(sources)==1 and sources[0]['url']=='https://lib.whu.edu.cn/rules'
    assert sources[0]['sections']==[{'locator':'检索摘要','text':'仅搜索摘要'}]
    assert report['excluded_domain_results']==2 and report['tool_usage']==2 and usage['prompt_tokens']==6


def test_direct_page_remains_available_when_native_search_fails(monkeypatch):
    async def fail(*args):raise evidence_web.AIError('temporary')
    async def read(url):return {'url':url,'title':'公开原文','sections':[{'locator':'段落1','text':'直接读取。'}],'limited':False}
    monkeypatch.setattr(evidence_web,'completion',fail);monkeypatch.setattr(evidence_web,'read_page',read)
    sources,report,_=asyncio.run(evidence_web.search(SimpleNamespace(ai_model='test'),['公开主题'],['https://lib.whu.edu.cn/rules']))
    assert report['status']=='searched' and report['failed_queries']==1 and len(sources)==1


def test_navigation_cannot_exhaust_the_index_before_policy_body_and_second_source():
    first={'id':'policy','evidence_kind':'web_page','sections':[
        *[{'locator':f'导航{i}','text':f'站点栏目{i}','_retrieval_score':1} for i in range(500)],
        {'locator':'正文1','text':'本科生借期30天。','_retrieval_score':20},
        {'locator':'正文2','text':'借书限额均为30册。','_retrieval_score':20}]}
    second={'id':'renewal','evidence_kind':'web_page','sections':[{'locator':'续借规则','text':'续借期从续借之日起往后计算。','_retrieval_score':12}]}
    entries=evidence_index([first,second])
    assert len(entries)==120
    assert any(p['source_id']=='renewal' for p in entries[:2])
    assert {p['locator'] for p in entries[:4]} >= {'正文1','正文2','续借规则'}
    assert entries[0]['quote']=='本科生借期30天。'


def test_repeated_web_navigation_does_not_displace_distinct_short_facts():
    entries=evidence_index([{'id':'page','evidence_kind':'web_page','sections':[
        *[{'locator':f'导航{i}','text':'借阅服务'} for i in range(500)],
        {'locator':'时限','text':'截止18:00。'}, {'locator':'地点','text':'总馆一楼'}]}])
    assert len(entries)==3 and any(e['quote']=='总馆一楼' for e in entries)
    assert entries[0]['locator']=='时限'
def test_native_search_today_uses_beijing_date_after_utc_midnight_boundary(monkeypatch):
    from datetime import datetime, timezone
    instant=datetime(2026,10,16,17,30,tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    requests=[]
    async def complete(settings,request):requests.append(request);return {'content':''},{}
    monkeypatch.setattr(evidence_web,'datetime',Clock)
    monkeypatch.setattr(evidence_web,'completion',complete)
    asyncio.run(evidence_web.search(SimpleNamespace(ai_model='test'),['官网今日通知']))
    assert requests[0]['messages'][1]['content'].startswith('当前北京时间日期：2026-10-17\n')
