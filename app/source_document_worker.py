"""Isolated, full-text parser for bounded public-source attachments."""
import json
import sys

from .source_limits import MAX_SOURCE_CHARS, MAX_SOURCE_FILE, MAX_SOURCE_PAGES


def extract(data, kind):
    if not data or len(data) > MAX_SOURCE_FILE:
        raise ValueError('附件超过公开来源文件读取上限，原件未截断')
    if kind in {'doc', 'xls'}:
        from .legacy_office import extract as extract_legacy
        result = extract_legacy(data, kind, max_chars=MAX_SOURCE_CHARS)
    elif kind in {'csv', 'xlsx'}:
        from .spreadsheet import spreadsheet_sections
        result = spreadsheet_sections(data, kind, full=True)
    else:
        from . import parser_worker
        parser_worker.MAX_TEXT = MAX_SOURCE_CHARS
        result = parser_worker.extract(data, kind, max_pages=MAX_SOURCE_PAGES)
    if sum(len(section['text']) for section in result['sections']) > MAX_SOURCE_CHARS:
        raise ValueError(f'附件提取文字超过 {MAX_SOURCE_CHARS:,} 字，未截断；原件仍可下载')
    return result


if __name__ == '__main__':
    try:
        kind = sys.argv[1]
        if sys.platform != 'win32':
            import resource
            # The legacy parser starts its own bounded JVM, so avoid a parent
            # address-space cap that would prevent Java from starting.
            if kind not in {'doc', 'xls'}:
                resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (55, 55))
        result = extract(sys.stdin.buffer.read(MAX_SOURCE_FILE + 1), kind)
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '文件损坏或结构不受支持，原件已保存'
        result = {'sections': [], 'status': 'failed', 'warning': message}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
