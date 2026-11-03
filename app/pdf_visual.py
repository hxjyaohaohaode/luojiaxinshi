"""Page-level PDF visual evidence, retaining the original source identity.

Page markers are parser metadata, not OCR or official prose. Rendering runs in
a bounded subprocess; only the current authorized PDF's pages reach a model.
"""
import base64
from collections import OrderedDict
import hashlib
import json
import re
import subprocess
import sys
import threading

from .config import ROOT

PAGE_MARKER = re.compile(r'^第 ([1-9][0-9]*) 页（图像待核对）$')
PAGE_NOTE = '本页没有足够的可提取文字，需依据本页完整渲染图核对；这不是通知正文或 OCR。'
PDF_LOCATOR = re.compile(r'^PDF 第 ([1-9][0-9]*) 页（图像观察，非 OCR）$')
MAX_PDF_VISUAL_PAGES = 50  # Same document/parser resource limit; model input is budgeted separately.
MAX_RENDER_BYTES = 5 * 1024 * 1024
_cache = OrderedDict()
_cache_size = 0
_cache_lock = threading.Lock()
_render_slots = threading.BoundedSemaphore(2)


def page_marker(page):
    return {'locator': f'第 {page} 页（图像待核对）', 'text': PAGE_NOTE}


def declared_pages(source):
    if source.get('kind') != 'pdf' or source.get('status') == 'failed':
        return []
    pages = source.get('_pdf_visual_pages')
    if pages is None:
        pages = [int(match[1]) for section in source.get('sections', [])
                 if section.get('text') == PAGE_NOTE and (match := PAGE_MARKER.fullmatch(section.get('locator', '')))]
    if not isinstance(pages, list) or any(type(page) is not int or not 1 <= page <= 50 for page in pages):
        raise ValueError('PDF 图像页索引无效，请重新读取原件')
    return sorted(set(pages))


def needs_visual_pages(source):
    return (source.get('kind')=='pdf' and source.get('status')!='failed'
            and (bool(declared_pages(source)) or '可能是扫描件' in source.get('warning','')))


def pending_pages(source):
    if not needs_visual_pages(source):return []
    if isinstance(source.get('content'),bytes):
        return [page['page'] for page in render_pages(source)]
    return declared_pages(source)


def visual_locator(page):
    return f'PDF 第 {page} 页（图像观察，非 OCR）'


def visual_note(page):
    return f'依据本 PDF 原件第 {page} 页的完整渲染图进行视觉核对；这是页码定位，不是 OCR 或逐字引文。'


def render_pages(source, *, force=False):
    global _cache_size
    if not needs_visual_pages(source) and not (force and source.get('kind')=='pdf'):
        return []
    raw = source.get('content')
    if not isinstance(raw, bytes) or not raw.startswith(b'%PDF-') or len(raw) > MAX_RENDER_BYTES:
        raise ValueError('PDF 原件不可读取或超过图像解析预算，请核对原文件')
    key = (hashlib.sha256(raw).hexdigest(), 'all-pages', 'pdf-pages-v2')
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    if not _render_slots.acquire(timeout=2):
        raise ValueError('PDF 图像解析当前繁忙，原件已保留，请稍后重试')
    try:
        proc = subprocess.run([sys.executable, '-m', 'app.pdf_render_worker', 'null'],
                              input=raw, capture_output=True, timeout=20, cwd=ROOT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if proc.returncode or len(proc.stdout) > 7_500_000:
            raise ValueError('PDF 页面渲染未完整返回，未将部分页面视为全部已读')
        result = json.loads(proc.stdout)
        if result.get('error'):
            raise ValueError(result['error'])
        values = result['pages']
        count=result.get('page_count')
        if type(count) is not int or not 1<=count<=MAX_PDF_VISUAL_PAGES or [item['page'] for item in values] != list(range(1,count+1)):
            raise ValueError('PDF 页码渲染不完整，原件已保留')
        rendered = [{'page': item['page'], 'content': base64.b64decode(item['jpeg'], validate=True)} for item in values]
        size = sum(len(item['content']) for item in rendered)
        if size > MAX_RENDER_BYTES or any(not item['content'].startswith(b'\xff\xd8') for item in rendered):
            raise ValueError('PDF 页面渲染超出预算或格式无效，未发送给模型')
    except (subprocess.TimeoutExpired, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('PDF 页面渲染超时或失败，原件已保留，请重试或补充清晰页面') from error
    finally:
        _render_slots.release()
    with _cache_lock:
        if key not in _cache:
            _cache[key] = rendered
            _cache_size += size
        while _cache_size > 16 * 1024 * 1024:
            _, removed = _cache.popitem(last=False)
            _cache_size -= sum(len(item['content']) for item in removed)
    return rendered
