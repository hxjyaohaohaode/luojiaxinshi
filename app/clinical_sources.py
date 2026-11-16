"""Parsers for the two hospitals' public education columns.

These parsers do not solve or bypass access verification. Activation still
requires a successful anonymous server-side list and article trial.
"""
import re
from urllib.parse import urldefrag,urljoin,urlsplit

from fastapi import HTTPException

from .evidence_web import public_url
from .official_sources import _FILES,_PERMISSION,_Tree,_clean,_date,_first


def article_url(value,base):
    target=public_url(urldefrag(urljoin(base,value or ''))[0])
    if not target:return None
    parts=urlsplit(target);host=urlsplit(base).hostname
    if parts.scheme!='https' or parts.hostname!=host or parts.query:return None
    if host=='www.rmhospital.com' and re.fullmatch(r'/article/id/\d+\.html',parts.path):return target
    if host=='www.znhospital.cn' and re.fullmatch(r'/graduate_student_notice_detail/\d+\.html',parts.path):return target
    return None


def parse_index(text,url,preset):
    if urlsplit(url).hostname!=urlsplit(preset['url']).hostname:
        raise HTTPException(422,'院方栏目地址与已确认的官网不一致')
    root=_Tree(text).root;first=urlsplit(url).hostname=='www.rmhospital.com'
    container=_first(root,cls='innoticelist') if first else _first(root,node_id='datalist')
    if not container:raise HTTPException(422,'院方通知列表结构不匹配，未读取导航')
    rows=([n for n in container.walk() if n.tag=='li'] if first else
          [n for n in container.walk() if n.has_class('item')])
    result=[];seen=set()
    for row in rows:
        link=next((n for n in row.walk() if n.tag=='a' and article_url(n.attrs.get('href'),url)),None)
        if not link:continue
        target=article_url(link.attrs.get('href'),url)
        title_node=link if first else _first(link,cls='t1')
        title=_clean(title_node.text()) if title_node else ''
        if not title or target in seen:continue
        if first:
            month=_first(row,cls='mon');day=_first(row,cls='day')
            published=_date(_clean(month.text())+'-'+_clean(day.text())) if month and day else None
        else:
            stamp=_first(link,cls='t3');published=_date(stamp.text()) if stamp else None
        result.append({'url':target,'title':title[:160],'published_at':published});seen.add(target)
    if not result:raise HTTPException(422,'院方栏目没有可识别的公开通知')
    if len(result)>200:raise HTTPException(422,'院方栏目超过读取范围')
    return result


def parse_article(text,url):
    root=_Tree(text).root;first=urlsplit(url).hostname=='www.rmhospital.com'
    wrapper=_first(root,cls='contentout' if first else 'article-page')
    title=_first(wrapper,cls='title' if first else 't')
    body=_first(wrapper,cls='content' if first else 'article-cont')
    info=_first(wrapper,cls='newsinfo' if first else 'article-head')
    body_text='\n'.join(_clean(line) for line in body.text().splitlines() if _clean(line)) if body else ''
    if not title or not body or not body_text or _PERMISSION.search(body_text) and len(body_text)<300:
        raise HTTPException(422,'院方正文为空或需要权限，未将验证页面作为通知')
    attachments=[];names={};related=[]
    for link in (n for n in body.walk() if n.tag=='a'):
        target=public_url(urldefrag(urljoin(url,link.attrs.get('href','')))[0]);label=_clean(link.text())
        if not target:continue
        if _FILES.search(target) or _FILES.search(label):
            if target not in attachments and len(attachments)<30:attachments.append(target);names[target]=label[:160]
        elif len(related)<100:related.append({'url':target,'title':label[:300]})
    published=_date(info.text()) if info else None
    has_media=any(n.tag in {'img','iframe','audio','video'} for n in body.walk())
    return {'text':body_text,'title':_clean(title.text())[:160],'published_at':published,
        'published_at_precision':'date' if published else None,'attachments':attachments,
        'attachment_names':names,'related_links':related,'has_media':has_media,
        'warnings':[],'parser_id':'whu-clinical-education'}
