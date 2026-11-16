"""Small, explicit adapters for public notice columns.

Dates keep the precision supplied by the publisher. No login or browser script
execution is used to obtain an article.
"""
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from fastapi import HTTPException

from .evidence_web import public_url


PRESETS = [
    {'id': 'whu-sres-notices', 'name': '资环院通知公告',
     'institution': '武汉大学资源与环境科学学院',
     'url': 'https://sres.whu.edu.cn/xxgk/tzgg.htm', 'article_path_prefix': '/info/3771/',
     'purpose': '资源与环境科学学院通知公告当前列表；保留原文、发布日期和附件，需校内权限的页面明确提示'},
    {'id': 'whu-notices', 'name': '武汉大学通知公告', 'institution': '武汉大学',
     'url': 'https://www.whu.edu.cn/tzgg.htm', 'article_path_prefix': '/info/5231/',
     'purpose': '学校通知公告当前列表中的公开原文；需要校内权限的文章会提示未能读取'},
    {'id': 'whu-undergrad-student', 'name': '本科生院学生通知', 'institution': '武汉大学本科生院',
     'url': 'https://uc.whu.edu.cn/tzgg/xstz.htm', 'article_path_prefix': '/info/1517/',
     'purpose': '本科生院发布的学生通知，包括退课、教学评价、竞赛和相关事项'},
    {'id': 'whu-undergrad-teaching', 'name': '本科生院教务安排', 'institution': '武汉大学本科生院',
     'url': 'https://uc.whu.edu.cn/tzgg/zhyw.htm', 'article_path_prefix': '/info/1520/',
     'purpose': '本科生院综合业务通知，包括考试、教学安排和其他教务事项'},
    {'id': 'whu-student-aid', 'name': '学生资助通知公告', 'institution': '武汉大学学生资助管理中心',
     'url': 'https://zzgl.whu.edu.cn/tzgg.htm', 'article_path_prefix': '/info/1019/',
     'purpose': '学校奖助学金、勤工助学和困难资助相关的公开通知与公示'},
    {'id': 'whu-employment', 'name': '学生就业通知公告', 'institution': '武汉大学学生就业指导与服务中心',
     'url': 'https://xsjy.whu.edu.cn/frontpage/whu/html/newsList.html?id=739BEBB72A0B2B25E0538713470A6C41',
     'article_path_prefix': '/frontpage/whu/html/newsDetail.html',
     'purpose': '学校就业中心发布的就业通知和活动公告，保留来源原文与发布日期'},
    {'id': 'whu-employment-jobs', 'name': '校园招聘岗位', 'institution': '武汉大学学生就业指导与服务中心',
     'url': 'https://xsjy.whu.edu.cn/frontpage/whu/html/recruitmentinfoList.html?type=1',
     'article_path_prefix': '/f/recruitmentinfo/show',
     'purpose': '就业信息网的校园招聘信息，保留用人单位、职位要求和原文；内容由用人单位发布'},
    {'id': 'whu-employment-internships', 'name': '校园实习招聘', 'institution': '武汉大学学生就业指导与服务中心',
     'url': 'https://xsjy.whu.edu.cn/frontpage/whu/html/recruitmentinfoList.html?type=2',
     'article_path_prefix': '/f/recruitmentinfo/show',
     'purpose': '就业信息网的实习招聘信息，保留职位、申请要求和原文；内容由用人单位发布'},
    {'id': 'whu-employment-fairs', 'name': '校园宣讲会', 'institution': '武汉大学学生就业指导与服务中心',
     'url': 'https://xsjy.whu.edu.cn/frontpage/whu/html/recruitmentFairList.html',
     'article_path_prefix': '/f/recruitmentFair/show',
     'purpose': '就业信息网的宣讲会，保留举办时间、地点、用人单位和招聘原文'},
    {'id': 'whu-journal-affairs', 'name': '新闻与传播学院学生事务',
     'institution': '武汉大学新闻与传播学院',
     'url': 'https://journal.whu.edu.cn/undergraduate/affairs/index',
     'article_path_prefix': '/undergraduate/',
     'purpose': '学院学生事务栏目当前列表，包含该栏目实际发布的本科生和研究生通知'},
    {'id': 'whu-library-notices', 'name': '武汉大学图书馆通知公告',
     'institution': '武汉大学图书馆',
     'url': 'https://www.lib.whu.edu.cn/engine2/general/more?appId=4627353&wfwfid=25295&pageId=740716&websiteId=425039&currentBranch=0',
     'article_path_prefix': '/engine2/d/',
     'purpose': '图书馆通知公告当前列表，接收本馆官网的开放、服务等通知；跳往其他平台的文章会提示未接收'},
]
for _preset in PRESETS:
    _preset['group'] = ('理学部' if _preset['id']=='whu-sres-notices' else
                        '人文科学学部' if _preset['id']=='whu-journal-affairs' else '校级部门')
from .whu_generic_sources import CATALOG as COLLEGE_AND_UNIT_PRESETS
PRESETS.extend(COLLEGE_AND_UNIT_PRESETS)
_HOSTS = {'sres.whu.edu.cn': 'whu-sres-notices', 'www.whu.edu.cn': 'whu-notices',
          'journal.whu.edu.cn': 'whu-journal-affairs',
          'www.lib.whu.edu.cn': 'whu-library-notices',
          'uc.whu.edu.cn': 'whu-undergrad', 'zzgl.whu.edu.cn': 'whu-student-aid'}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_BLOCKED = {'script', 'style', 'noscript', 'svg', 'iframe', 'template'}
_BLOCKS = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr', 'article', 'section'}
_FILES = re.compile(r'\.(pdf|docx?|xlsx?|csv|txt|md|zip|png|jpe?g|webp)(?:[?#]|$)', re.I)
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
    elif preset_id == 'whu-sres-notices':
        query = parse_qs(parts.query)
        allowed = bool(re.fullmatch(r'/info/3771/\d+\.htm', parts.path)) or (
            parts.path == '/xzcontent.jsp' and query.get('wbtreeid') == ['3771']
            and len(query.get('wbnewsid', [])) == 1 and query['wbnewsid'][0].isdigit())
    elif preset_id in {'whu-undergrad-student', 'whu-undergrad-teaching'}:
        column = '1517' if preset_id == 'whu-undergrad-student' else '1520'
        allowed = bool(re.fullmatch(r'/info/' + column + r'/\d+\.htm', parts.path)) and not parts.query
    elif preset_id == 'whu-student-aid':
        query = parse_qs(parts.query)
        allowed = bool(re.fullmatch(r'/info/1019/\d+\.htm', parts.path)) or (
            parts.path == '/content.jsp' and query.get('wbtreeid') == ['1019']
            and len(query.get('wbnewsid', [])) == 1 and query['wbnewsid'][0].isdigit())
    else:
        # The column contains articles from both undergraduate and graduate paths.
        allowed = bool(re.fullmatch(r'/(?:undergraduate|graduate|notice)/(?:[A-Za-z0-9_-]+/)*\d{8}[A-Za-z0-9]+', parts.path))
    return target if allowed else None


def parse_official_index(text, url, preset_id):
    preset = get_preset(preset_id)
    if not preset or urlsplit(url).hostname != urlsplit(preset['url']).hostname:
        raise HTTPException(422, '官网预设与来源地址不匹配')
    if preset.get('adapter') in {'vsb','oral','journal'}:
        from .whu_generic_sources import parse_index
        return parse_index(text,url,preset)
    root = _Tree(text).root
    if preset_id == 'whu-notices':
        tables = [n for n in root.walk() if n.tag == 'table']
        container = next((n for n in tables if all(label in n.text() for label in ('发布单位', '发布日期'))), None)
        rows = [n for n in container.walk() if n.tag == 'tr'] if container else []
    elif preset_id == 'whu-sres-notices':
        container = _first(root, tag='ul', cls='list-container')
        rows = [n for n in container.children if isinstance(n, _Node) and n.tag == 'li'] if container else []
    elif preset_id in {'whu-undergrad-student', 'whu-undergrad-teaching'}:
        section = _first(root, cls='list_txt')
        container = _first(section, tag='ul', cls='am-list')
        rows = [n for n in container.children if isinstance(n, _Node) and n.tag == 'li'] if container else []
    elif preset_id == 'whu-student-aid':
        section = _first(root, cls='list-box')
        container = _first(_first(section, cls='list'), tag='ul')
        rows = [n for n in container.children if isinstance(n, _Node) and n.tag == 'li'] if container else []
    else:
        container = _first(root, tag='ul', cls='p-list5')
        rows = [n for n in container.children if isinstance(n, _Node) and n.tag == 'li'] if container else []
    if container is None:
        raise HTTPException(422, '官网通知列表结构已变化，未抓取导航或整站链接，请重新核对来源')
    entries, seen = [], set()
    for row in rows:
        for link in (n for n in row.walk() if n.tag == 'a'):
            target = _article_url(link.attrs.get('href'), url, preset_id)
            title_node = (_first(link, cls='content') if preset_id == 'whu-sres-notices' else
                          _first(link, tag='span') if preset_id in {'whu-undergrad-student', 'whu-undergrad-teaching'} else
                          _first(link, tag='p') if preset_id == 'whu-student-aid' else None)
            title = _clean(title_node.text() if title_node else link.text())
            if not target or not title or target in seen:
                continue
            if preset_id == 'whu-notices':
                cells = [n for n in row.children if isinstance(n, _Node) and n.tag == 'td']
                published = _date(cells[2].text()) if len(cells) >= 3 else None
            elif preset_id == 'whu-sres-notices':
                stamp = _first(row, cls='time')
                published = _date(stamp.text()) if stamp else None
            elif preset_id in {'whu-undergrad-student', 'whu-undergrad-teaching'}:
                stamp = _first(row, tag='i')
                published = _date(stamp.text()) if stamp else None
            elif preset_id == 'whu-student-aid':
                stamp = _first(row, cls='time')
                published = _date(stamp.text()) if stamp else None
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
    from .whu_generic_sources import matching_article,parse_article
    generic=matching_article(url)
    if generic:return parse_article(text,url,generic)
    preset_id = _HOSTS.get(urlsplit(url).hostname)
    if not preset_id:
        return None
    parts = urlsplit(url)
    if preset_id == 'whu-undergrad':
        match = re.fullmatch(r'/info/(1517|1520)/\d+\.htm', parts.path)
        if not match:
            return None
        preset_id = 'whu-undergrad-student' if match[1] == '1517' else 'whu-undergrad-teaching'
    if preset_id == 'whu-student-aid' and not _article_url(url, url, preset_id):
        return None
    if preset_id == 'whu-library-notices':
        article_match = re.fullmatch(r'/engine2/d/(\d+)/5619257/0', parts.path)
        if not article_match:
            return None
        query = parse_qs(parts.query)
        if query not in ({'t': ['11166542'], 'p': ['740716']}, {'t': ['11166542'], 'p': ['1']}):
            raise HTTPException(422, '图书馆文章不属于已订阅的公告栏目')
        matches = list(re.finditer(r'\bdata\s*:\s*(?=\{\s*"engineInstanceId"\s*:\s*5619257\s*,)', text))
        if len(matches) != 1:
            raise HTTPException(422, '图书馆正文结构已变化，未将页面脚本当作通知')
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[matches[0].end():])
            if (str(payload.get('id')) != article_match[1] or payload.get('engineInstanceId') != 5619257 or
                    payload.get('publicUse') is not True or payload.get('isPublish') != 1 or
                    payload.get('pageType') != 1 or payload.get('isOuter') is not False or
                    (payload.get('typeId') is not None and str(payload['typeId']) != '11166542') or
                    not isinstance(payload.get('content'), str)):
                raise ValueError('unexpected article')
            title = _clean(payload['1']['value'])
            published = _date(payload['6']['value'])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(422, '图书馆公告数据不完整或不属于公开栏目') from None
        root = _Tree(payload['content']).root
        body = material_area = root
    else:
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
    elif preset_id == 'whu-sres-notices':
        article = _first(root, node_id='bgnr')
        title_node = _first(article, cls='news-title')
        body = _first(article, cls='v_news_content')
        material_area = _first(article, cls='news_content') or body
        title = _clean(title_node.text()) if title_node else ''
        stamp = _first(article, cls='time-info')
        published = _date(stamp.text()) if stamp else None
    elif preset_id in {'whu-undergrad-student', 'whu-undergrad-teaching'}:
        header = _first(root, cls='title_nei')
        title_node = _first(header, tag='b')
        body = _first(root, cls='v_news_content')
        material_area = _first(root, cls='news_show') or body
        title = _clean(title_node.text()) if title_node else ''
        stamp = _first(header, tag='i')
        published = _date(stamp.text()) if stamp else None
    elif preset_id == 'whu-student-aid':
        article = _first(root, cls='article')
        title_node = _first(article, tag='h2', cls='title')
        body = _first(article, cls='v_news_content')
        material_area = article or body
        title = _clean(title_node.text()) if title_node else ''
        stamp = _first(article, cls='xinxi')
        published = _date(stamp.text()) if stamp else None
    elif preset_id == 'whu-journal-affairs':
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
    if not body and len(gate_text) < 200 and '无效的访问地址' in gate_text:
        raise HTTPException(422, '学校网站提示原网页地址无效；已有内容保留，请打开原网页核对')
    if _PERMISSION.search(gate_text) and (not body or len(body_text) < 300):
        raise HTTPException(422, '这则通知需要校内权限或登录，未作为公开正文接收；请本人提供原文')
    if not body or not title:
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
    if preset_id in {'whu-sres-notices', 'whu-undergrad-student', 'whu-undergrad-teaching'}:
        # VSB embeds some notices as a PDF rather than visible paragraphs. Read
        # only the literal URL argument of this observed call; never run script.
        for script in (n for n in body.walk() if n.tag == 'script'):
            raw = ''.join(child for child in script.children if isinstance(child, str))
            for match in re.finditer(r'''showVsbpdfIframe\(\s*(["'])([^"'\r\n]+\.pdf(?:\?[^"'\r\n]*)?)\1\s*,''', raw):
                target = public_url(urldefrag(urljoin(url, match[2]))[0])
                if target and target not in attachments and len(attachments) < 30:
                    attachments.append(target)
                    names[target] = title[:150] + '.pdf'
    attachment_only = not body_text and bool(attachments)
    if not body_text and not attachment_only:
        raise HTTPException(422, '官网正文结构不匹配或没有公开文字，未把导航和权限页当作通知；请核对原文')
    # A title is publisher text, not a reconstruction of an unread attachment.
    if attachment_only:
        body_text = title
    has_media = any(n.tag in {'video', 'audio', 'iframe'} or (
        n.tag == 'img' and not urlsplit(urljoin(url, n.attrs.get('src') or '')).path.startswith(
            '/system/resource/images/fileTypeImages/')) for n in body.walk())
    return {'text': body_text, 'title': title[:160], 'published_at': published,
            'published_at_precision': 'date' if published else None,
            'attachments': attachments, 'attachment_names': names,
            'related_links':[{'url':target,'title':_clean(link.text())[:300]} for link in material_area.walk() if link.tag=='a'
                if (target:=public_url(urldefrag(urljoin(url,link.attrs.get('href','')))[0])) and target not in attachments][:100],
            'has_media': has_media, 'attachment_only': attachment_only,
            'warnings': ['网页正文以附件形式发布，当前文字仅为标题；请核对附件读取结果'] if attachment_only else [],
            'parser_id': preset_id}
