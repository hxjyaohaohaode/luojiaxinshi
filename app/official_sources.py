"""Small, explicit adapters for two public WHU notice columns.

Dates keep the precision supplied by the publisher. No login, browser script,
URL rewriting, or traversal is used to obtain an article.
"""
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from fastapi import HTTPException

from .evidence_web import public_url


PRESETS = [
    {'id': 'whu-notices', 'name': '武汉大学通知公告', 'institution': '武汉大学',
     'url': 'https://www.whu.edu.cn/tzgg.htm', 'article_path_prefix': '/info/5231/',
     'purpose': '学校通知公告当前列表中的公开原文；需要校内权限的文章会提示未能读取'},
    {'id': 'whu-journal-affairs', 'name': '新闻与传播学院学生事务',
     'institution': '武汉大学新闻与传播学院',
     'url': 'https://journal.whu.edu.cn/undergraduate/affairs/index',
     'article_path_prefix': '/undergraduate/',
     'purpose': '学院学生事务栏目当前列表，包含该栏目实际发布的本科生和研究生通知'},
]
_HOSTS = {'www.whu.edu.cn': 'whu-notices', 'journal.whu.edu.cn': 'whu-journal-affairs'}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_BLOCKED = {'script', 'style', 'noscript', 'svg', 'iframe', 'template'}
_BLOCKS = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr', 'article', 'section'}
_FILES = re.compile(r'\.(pdf|docx?|xlsx?|zip|png|jpe?g)(?:[?#]|$)', re.I)
_PERMISSION = re.compile(r'(?:您|你)?(?:无权|没有权限|无权限)访问|暂无权限|(?:仅限|只限)校内|(?:请|需要|须)(?:先)?登录(?:后)?(?:查看|访问|阅读)|访问受限|权限不足|校外(?:用户)?(?:无法|不能)访问')


def get_preset(preset_id):
    return next((dict(p) for p in PRESETS if p['id'] == preset_id), None)


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def has_class(self, value):
        return value in (self.attrs.get('class') or '').split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self):
        if self.tag in _BLOCKED:
            return ''
        content = ''.join(child.text() if isinstance(child, _Node) else child for child in self.children)
        if self.tag in {'td', 'th'}:
            return content + '\t'
        return '\n' + content + '\n' if self.tag in _BLOCKS else content


class _Tree(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = _Node('root')
        self.stack, self.count = [self.root], 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 30000 or len(self.stack) > 200:
            raise HTTPException(422, '官网页面结构过大或过深，未作为通知接收')
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def _first(node, *, tag=None, cls=None, node_id=None):
    if node is None:
        return None
    return next((n for n in node.walk() if (tag is None or n.tag == tag)
                 and (cls is None or n.has_class(cls))
                 and (node_id is None or n.attrs.get('id') == node_id)), None)


def _clean(value):
    return re.sub(r'\s+', ' ', value).strip()


def _date(value):
    match = re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)', value)
    if match:
        try:
            return date.fromisoformat(match[1]).isoformat()
        except ValueError:
            pass
    return None


def _article_url(href, base, preset_id):
    target = public_url(urldefrag(urljoin(base, href or ''))[0])
    preset = get_preset(preset_id)
    if not target or urlsplit(target).hostname != urlsplit(preset['url']).hostname:
        return None
    parts = urlsplit(target)
    if preset_id == 'whu-notices':
        query = parse_qs(parts.query)
        allowed = bool(re.fullmatch(r'/info/5231/\d+\.htm', parts.path)) or (
            parts.path == '/new2024/tzggnr.jsp' and query.get('wbtreeid') == ['5231']
            and len(query.get('wbnewsid', [])) == 1 and query['wbnewsid'][0].isdigit())
    else:
        # The column contains articles from both undergraduate and graduate paths.
        allowed = bool(re.fullmatch(r'/(?:undergraduate|graduate|notice)/(?:[A-Za-z0-9_-]+/)*\d{8}[A-Za-z0-9]+', parts.path))
    return target if allowed else None


def parse_official_index(text, url, preset_id):
    preset = get_preset(preset_id)
    if not preset or urlsplit(url).hostname != urlsplit(preset['url']).hostname:
        raise HTTPException(422, '官网预设与来源地址不匹配')
    root = _Tree(text).root
    if preset_id == 'whu-notices':
        tables = [n for n in root.walk() if n.tag == 'table']
        container = next((n for n in tables if all(label in n.text() for label in ('发布单位', '发布日期'))), None)
        rows = [n for n in container.walk() if n.tag == 'tr'] if container else []
    else:
        container = _first(root, tag='ul', cls='p-list5')
        rows = [n for n in container.children if isinstance(n, _Node) and n.tag == 'li'] if container else []
    if container is None:
        raise HTTPException(422, '官网通知列表结构已变化，未抓取导航或整站链接，请重新核对来源')
    entries, seen = [], set()
    for row in rows:
        for link in (n for n in row.walk() if n.tag == 'a'):
            target = _article_url(link.attrs.get('href'), url, preset_id)
            title = _clean(link.text())
            if not target or not title or target in seen:
                continue
            if preset_id == 'whu-notices':
                cells = [n for n in row.children if isinstance(n, _Node) and n.tag == 'td']
                published = _date(cells[2].text()) if len(cells) >= 3 else None
            else:
                stamp = _first(row, cls='date')
                published = _date(stamp.text()) if stamp else None
            entries.append({'url': target, 'title': title[:160], 'published_at': published})
            seen.add(target)
    if not entries:
        raise HTTPException(422, '官网列表没有可识别的通知文章，请检查栏目或页面结构')
    if len(entries) > 200:
        raise HTTPException(422, '官网列表超过 200 条，请使用更具体的通知栏目')
    return entries


def parse_official_article(text, url):
    """Return None for other hosts; known hosts must match an article structure."""
    preset_id = _HOSTS.get(urlsplit(url).hostname)
    if not preset_id:
        return None
    root = _Tree(text).root
    if preset_id == 'whu-notices':
        header = _first(root, cls='ar_tit')
        title_node = _first(header, tag='h3')
        body = _first(root, cls='v_news_content')
        material_area = _first(root, node_id='zoomcon') or body
        meta = {(n.attrs.get('name') or '').lower(): n.attrs.get('content') or ''
                for n in root.walk() if n.tag == 'meta'}
        title = _clean(title_node.text()) if title_node else meta.get('articletitle', '')
        published = _date(meta.get('pubdate', ''))
        if not published and header:
            stamp = next((n for n in header.walk() if n.tag == 'p' and '发布时间' in n.text()), None)
            published = _date(stamp.text()) if stamp else None
    else:
        article = _first(root, cls='m-txt2')
        header = _first(article, cls='con-top')
        title_node = _first(header, tag='h1')
        body = _first(article, cls='m-table4')
        material_area = body
        title = _clean(title_node.text()) if title_node else ''
        stamp = _first(header, cls='date-m')
        published = _date(stamp.text()) if stamp else None
    body_text = '\n'.join(_clean(line) for line in body.text().splitlines() if _clean(line)) if body else ''
    # Inspect the content area, or a short page without a content area, for access gates.
    gate_text = body_text if body else _clean(root.text())
    if _PERMISSION.search(gate_text) and (not body or len(body_text) < 300):
        raise HTTPException(422, '这则通知需要校内权限或登录，未作为公开正文接收；请本人提供原文')
    if not body or not title or not body_text:
        raise HTTPException(422, '官网正文结构不匹配或没有公开文字，未把导航和权限页当作通知；请核对原文')
    attachments, names = [], {}
    for link in (n for n in material_area.walk() if n.tag == 'a'):
        target = public_url(urldefrag(urljoin(url, link.attrs.get('href', '')))[0])
        label = _clean(link.text())
        if target and (_FILES.search(target) or _FILES.search(label)) and target not in attachments:
            attachments.append(target)
            names[target] = label[:160]
            if len(attachments) == 30:
                break
    return {'text': body_text, 'title': title[:160], 'published_at': published,
            'published_at_precision': 'date' if published else None,
            'attachments': attachments, 'attachment_names': names,
            'has_media': any(n.tag in {'img', 'video', 'audio', 'iframe'} for n in body.walk()),
            'parser_id': preset_id}
