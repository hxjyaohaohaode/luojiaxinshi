"""Bounded research inside an authorized public source, with explicit edges.

Links prove a page referred to another page, not that both sets of rules apply.
Title matches are only candidate edges. Never merge different annual rounds or
replace original requirements using a candidate's newer collection timestamp.
"""
import asyncio
import re
from urllib.parse import urlsplit
from fastapi import HTTPException
from .documents import MAX_CHARS,MAX_FILE,total_chars
from .notice_ingest import _distinct_round
from .notice_intake import read_link,read_notice_materials
from .evidence_web import public_url

MAX_RELATED=2
RESEARCH_SECONDS=35


def within_budget(materials):
    # Match the existing notice extractor/reviewer: six sources, five file
    # attachments. Image pages share their parent source; token budgets count
    # every rendered page. Never fetch seven sources and fail only after paying
    # for a review whose source_index schema cannot represent the seventh.
    return (len(materials)<=6 and sum(s.get('kind')!='text' for s in materials)<=5
        and total_chars(materials)<=MAX_CHARS
        and sum(len(s.get('content') or b'') for s in materials)<=MAX_FILE)


def subject(title):
    title=re.sub(r'关于|开展|组织|举办|公布|发布|通知|公告|公示|补充|延期|更正|结果|名单|报名|申请|工作|有关|事宜|的|第[一二三四五六七八九十百\d]+(?:批|轮|期)|20\d{2}年度?', '',title)
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]','',title.casefold())


def relation(left,right):
    if _distinct_round(left,right['title'],right.get('published_at')):return 0
    a,b=subject(left['title']),subject(right['title'])
    if min(len(a),len(b))<5:return 0
    grams=lambda text:{text[i:i+2] for i in range(len(text)-1)}
    x,y=grams(a),grams(b)
    overlap=len(x&y)
    score=overlap/max(len(x),len(y))
    # Generic "2026 年度活动" similarities cannot link unrelated activities.
    return score if overlap>=4 and score>=0.65 else 0


def candidates(primary,config,entries):
    origin=primary.get('origin') or {};base=origin.get('url','')
    host=urlsplit(config['url']).hostname;prefix=config.get('article_path_prefix','/')
    current={'title':primary.get('name',''),'published_at':origin.get('published_at')}
    choices={}
    for item in origin.get('related_links',[]):
        if not isinstance(item,dict):continue
        url=public_url(item.get('url'));label=item.get('title','')
        if not url or url==base or urlsplit(url).hostname!=host or not urlsplit(url).path.startswith(prefix):continue
        # Require a matter-specific title even for a direct link, avoiding menus.
        score=relation(current,{'title':label,'published_at':None})
        if score:choices[url]={'url':url,'title':label,'relationship':'linked_candidate','score':score+1}
    for item in entries:
        url=public_url(item.get('url'))
        if not url or url==base or urlsplit(url).hostname!=host or not urlsplit(url).path.startswith(prefix):continue
        score=relation(current,item)
        if score and url not in choices:choices[url]={**item,'relationship':'index_candidate','score':score}
    return sorted(choices.values(),key=lambda item:(-item['score'],item['url']))[:MAX_RELATED]


async def read_network(primary,config,entries,*,read=None):
    reader=read or read_link
    materials=await read_notice_materials(primary,read=reader)
    root=materials[0];origin=root['origin'];warnings=origin.setdefault('warnings',[])
    proposed=candidates(root,config,entries)
    origin['related_search']={'scope':'authorized_source_index_and_links','candidates':proposed,
        'limit':MAX_RELATED,'complete':False,'errors':[]}
    report=origin['related_search'];host=urlsplit(config['url']).hostname
    async def fetch(item):
        try:
            source,_=await reader(item['url'])
            if urlsplit(source.get('origin',{}).get('url','')).hostname!=host:
                raise HTTPException(422,'关联原文跳转出了授权来源域名')
            # A current original is retained as its own source; this edge is not
            # an assertion of supersession or the user's eligibility.
            source['origin']={**source.get('origin',{}),'parent_url':origin['url'],
                'relationship':item['relationship'],'relationship_verified':False}
            source['warning']='自动找到的关联候选；须核对事项、对象、轮次和效力，不能仅按新日期覆盖原通知。'+source.get('warning','')
            return await read_notice_materials(source,read=reader)
        except (HTTPException,OSError,ValueError,TimeoutError) as exc:
            return {'url':item['url'],'error':str(exc.detail) if isinstance(exc,HTTPException) else '关联来源未读到正文'}
    try:
        async with asyncio.timeout(RESEARCH_SECONDS):
            results=await asyncio.gather(*(fetch(item) for item in proposed))
        for result in results:
            if isinstance(result,dict):report['errors'].append(result);continue
            known={s['sha256'] for s in materials}
            additions=[s for s in result if s['sha256'] not in known]
            if not within_budget(materials+additions):
                report['errors'].append({'url':result[0]['origin']['url'],'error':'关联材料超过本次完整解析预算，未截断加入'})
                continue
            materials.extend(additions)
        report['complete']=True
    except TimeoutError:
        report['errors'].append({'error':'关联查找达到时间上限，已保留主文及其附件'})
    if report['errors']:warnings.append('部分关联信息未完整读取；可在追踪与证据链中查看，不能当作没有后续通知')
    return materials


def provenance(sources):
    from .source_coverage import coverage
    keys=('url','retrieved_at','published_at','parent_url','relationship','relationship_verified','warnings','attachments','received_attachments','related_search','retained_snapshots')
    return [{'source_id':s['id'],'coverage':coverage(s),**{key:s.get('origin',{})[key] for key in keys if key in (s.get('origin') or {})}}
            for s in sources if s.get('origin')]


def retain_unavailable(conn,uid,external_key,materials):
    """A transient auxiliary failure cannot remove a previously read extension.

    The current root records which old snapshots were retained. Reusing a byte
    hash never changes its historical successful retrieval time.
    """
    import json
    origin=materials[0]['origin'];report=origin.get('related_search') or {}
    errors=report.get('errors') or []
    missing=set(origin.get('attachments',[]))-set(origin.get('received_attachments',[]))
    failed=missing|{e['url'] for e in errors if e.get('url')}
    if any(not e.get('url') for e in errors):failed.update(c['url'] for c in report.get('candidates',[]))
    if not failed:return materials
    receipt=conn.execute('SELECT notice_id FROM notice_ingest_receipts WHERE user_id=? AND external_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(uid,external_key)).fetchone()
    if not receipt:return materials
    previous=[]
    # Another collector of the same notice can have obtained a newer snapshot.
    # A failed refresh must retain that current evidence, not resurrect this
    # collector key's older receipt and silently undo the newer attachment.
    for row in conn.execute('''SELECT s.*,o.data AS origin_json FROM sources s JOIN notices n ON n.id=s.notice_id
            JOIN notice_source_origins o ON o.source_id=s.id WHERE s.notice_id=? AND n.user_id=? AND s.active=1
            ORDER BY s.created_at,s.id''',(receipt[0],uid)):
        previous.append({**dict(row),'sections':json.loads(row['sections']),'origin':json.loads(row['origin_json'])})
    known={s['sha256'] for s in materials};retained=[]
    for _ in range(len(previous)):
        changed=False
        for source in previous:
            old=source['origin'];url=old.get('url')
            if source['sha256'] in known or not old.get('relationship'):continue
            if url not in failed and old.get('parent_url') not in failed:continue
            if not within_budget(materials+[source]):
                raise HTTPException(413,'本轮材料与旧证据快照合计过大；保留上次完整版本，待复查后更新')
            materials.append(source);known.add(source['sha256']);failed.add(url);changed=True
            retained.append({'url':url,'sha256':source['sha256'],'retrieved_at':old.get('retrieved_at')})
        if not changed:break
    if retained:
        origin['retained_snapshots']=retained
        origin.setdefault('warnings',[]).append('部分来源本轮读取失败，暂保留最近成功抓取的旧快照；当前适用性待核实')
    return materials
