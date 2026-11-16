"""Verified WHU college/department lists with bounded same-origin parsing.

The catalogue is derived from the university's public institutional directory.
Each enabled entry identifies a specific published list, not a site-wide crawl.
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from fastapi import HTTPException

from .evidence_web import public_url

CATALOG = json.loads((Path(__file__).with_name('whu_college_catalog.json')).read_text(encoding='utf-8'))


def article_url(value, base, preset):
    target=public_url(urldefrag(urljoin(base,value or ''))[0])
    if not target or urlsplit(target).hostname!=urlsplit(preset['url']).hostname:
        return None
    parts=urlsplit(target);query=parse_qs(parts.query);adapter=preset.get('adapter')
    if adapter=='oral':
        allowed=bool(re.fullmatch(r'/article/\d+',parts.path)) and not parts.query
    elif adapter=='journal':
        allowed=bool(re.fullmatch(r'/(?:\d{8}[A-Za-z0-9]+|(?:undergraduate|graduate|notice)/(?:[A-Za-z0-9_-]+/)*\d{8}[A-Za-z0-9]+)',parts.path)) and not parts.query
    else:
        allowed=bool(re.fullmatch(r'/info/\d+/\d+\.htm',parts.path)) and not parts.query
        if not allowed and re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.jsp',parts.path):
            allowed=(query.get('urltype')==['news.NewsContentUrl'] and
                len(query.get('wbtreeid',[]))==len(query.get('wbnewsid',[]))==1 and
                query['wbtreeid'][0].isdigit() and query['wbnewsid'][0].isdigit())
    return target if allowed else None


def _date(value):
    match=re.search(r'(?<!\d)(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})(?:日)?(?!\d)',value)
    if not match:return None
    try:return date(*(int(x) for x in match.groups())).isoformat()
    except ValueError:return None


def _identity(url):
    parts=urlsplit(url);query=parse_qs(parts.query)
    match=re.fullmatch(r'/info/(\d+)/(\d+)\.htm',parts.path)
    if match:return (parts.hostname,match[1],match[2])
    if query.get('wbtreeid') and query.get('wbnewsid'):
        return (parts.hostname,query['wbtreeid'][0],query['wbnewsid'][0])
    return url


def parse_index(text,url,preset):
    from .official_sources import _Node,_Tree,_clean
    if urlsplit(url).hostname!=urlsplit(preset['url']).hostname:
        raise HTTPException(422,'学院栏目地址与已确认的官网不一致')
    root=_Tree(text).root;options=[]
    for node in root.walk():
        if node.tag!=preset.get('list_tag','ul'):continue
        identity=set((node.attrs.get('class') or '').split())|{node.attrs.get('id','')}
        if not set(preset.get('list_tokens') or []).issubset(identity):continue
        if node.tag=='ul':rows=[n for n in node.children if isinstance(n,_Node) and n.tag=='li']
        elif node.tag=='dl':rows=[n for n in node.children if isinstance(n,_Node) and n.tag=='dt']
        else:
            rows=[n for n in node.walk() if n.tag=='li']
            if not rows:rows=[n for n in node.walk() if n.tag=='a']
        entries=[];seen=set()
        for row in rows:
            for link in (n for n in row.walk() if n.tag=='a'):
                target=article_url(link.attrs.get('href'),url,preset)
                title=_clean(link.attrs.get('title') or link.text())
                identity=_identity(target) if target else None
                if not target or not title or len(title)<5 or identity in seen:continue
                # Some templates include the date inside the title link.
                title=re.sub(r'\s*(?:20\d{2}[-./]\d{1,2}[-./]\d{1,2})\s*$','',title).strip()
                entries.append({'url':target,'title':title[:160],'published_at':_date(row.text())})
                seen.add(identity);break
        if entries:options.append(entries)
    if not options:
        raise HTTPException(422,'学院通知列表没有可识别的公开原文，请核对栏目结构')
    selected=options if preset.get('list_multi') else [max(options,key=len)]
    entries=[];seen=set()
    for group in selected:
        for item in group:
            identity=_identity(item['url'])
            if identity not in seen:entries.append(item);seen.add(identity)
    if len(entries)>200:raise HTTPException(422,'学院通知栏目超过 200 条，请核对列表范围')
    return entries


def matching_article(url):
    """Match only exact official hosts and known article URL shapes."""
    host=urlsplit(url).hostname
    return next((p for p in CATALOG if p.get('adapter') in {'vsb','oral'} and
                 urlsplit(p['url']).hostname==host and article_url(url,p['url'],p)),None)


def parse_article(text,url,preset):
    from .official_sources import _FILES,_Node,_PERMISSION,_Tree,_clean,_first
    root=_Tree(text).root
    meta={(n.attrs.get('name') or n.attrs.get('property') or '').lower():n.attrs.get('content') or ''
          for n in root.walk() if n.tag=='meta'}
    title=_clean(meta.get('articletitle') or meta.get('pagetitle') or meta.get('og:title') or '')
    if preset.get('adapter')=='oral':
        body=next((n for n in root.walk() if n.tag=='div' and n.has_class('content') and _first(n,tag='h1')),None)
        heading=_first(body,tag='h1')
        title=title or (_clean(heading.text()) if heading else '')
    else:
        body=next((n for n in root.walk() if (n.attrs.get('id') or '').startswith('vsb_content')),None)
        if not body:body=_first(root,cls='v_news_content')
        if not title:
            heading=_first(root,tag='h1');title=_clean(heading.text()) if heading else ''
    body_text='\n'.join(_clean(line) for line in body.text().splitlines() if _clean(line)) if body else ''
    gate=body_text if body else _clean(root.text())
    if _PERMISSION.search(gate) and (not body or len(body_text)<300):
        raise HTTPException(422,'这则通知需要校内权限或登录，未作为公开正文接收；请本人提供原文')
    if not body or not title:
        raise HTTPException(422,'学院官网正文结构不匹配，未将导航或权限页面当作通知')
    attachments=[];names={}
    for link in (n for n in body.walk() if n.tag=='a'):
        target=public_url(urldefrag(urljoin(url,link.attrs.get('href','')))[0]);label=_clean(link.text())
        if target and (_FILES.search(target) or _FILES.search(label)) and target not in attachments:
            attachments.append(target);names[target]=label[:160]
            if len(attachments)>=30:break
    for script in (n for n in body.walk() if n.tag=='script'):
        raw=''.join(c for c in script.children if isinstance(c,str))
        for match in re.finditer(r'''showVsbpdfIframe\(\s*(["'])([^"'\r\n]+\.pdf(?:\?[^"'\r\n]*)?)\1\s*,''',raw):
            target=public_url(urldefrag(urljoin(url,match[2]))[0])
            if target and target not in attachments and len(attachments)<30:
                attachments.append(target);names[target]=title[:150]+'.pdf'
    attachment_only=not body_text and bool(attachments)
    if not body_text and not attachment_only:
        raise HTTPException(422,'学院网页没有可读取正文或附件，请打开原网页核对')
    if attachment_only:body_text=title
    has_media=any(n.tag in {'video','audio','iframe'} or (n.tag=='img' and not urlsplit(
        urljoin(url,n.attrs.get('src') or '')).path.startswith('/system/resource/images/fileTypeImages/')) for n in body.walk())
    published=_date(meta.get('pubdate') or meta.get('publishdate') or '')
    if not published:
        stamp=next((n for n in root.walk() if n.tag in {'span','p','time','div'} and len(_clean(n.text()))<150
                    and re.search(r'发布时间|发布日期|发布于|发表时间',_clean(n.text()))),None)
        published=_date(stamp.text()) if stamp else None
    related=[{'url':target,'title':_clean(link.text())[:300]} for link in body.walk() if link.tag=='a'
             if (target:=public_url(urldefrag(urljoin(url,link.attrs.get('href','')))[0])) and target not in attachments][:100]
    return {'text':body_text,'title':title[:160],'published_at':published,
        'published_at_precision':'date' if published else None,'attachments':attachments,'attachment_names':names,
        'related_links':related,'has_media':has_media,'attachment_only':attachment_only,
        'warnings':['网页正文以附件形式发布，当前文字仅为标题；请核对附件读取结果'] if attachment_only else [],
        'parser_id':preset['id']}
