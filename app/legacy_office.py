"""Local-only legacy Office extraction through a pinned Apache Tika process.

Installation is explicit. No request downloads tools, opens URLs or starts a
server. Original bytes stay in the existing private source storage.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from defusedxml import ElementTree as ET
from .config import ROOT

TIKA_VERSION='4.2.0'
OUTPUT_BYTES=4*1024*1024


def tools():
    vendor=Path(os.environ.get('LEGACY_PARSER_DIR',ROOT/'data/vendor')).resolve()
    jar=vendor/'tika'/f'tika-app-{TIKA_VERSION}.jar'
    java=shutil.which('java')
    if not java:
        try:
            manifest=json.loads((vendor/'legacy-parser-manifest.json').read_text(encoding='utf-8'))
            candidate=(vendor/manifest['java']['relative_binary']).resolve()
            if candidate.is_relative_to(vendor/'java') and candidate.is_file():java=str(candidate)
        except (OSError,ValueError,KeyError,TypeError):pass
    if not java or not jar.is_file() or not (jar.parent/'lib').is_dir():
        raise ValueError('旧格式解析服务尚未就绪；可先另存为 DOCX / XLSX，或联系管理员启用旧格式读取')
    return java,jar


def sections_from_xhtml(content,max_chars):
    root=ET.fromstring(content)
    local=lambda node:node.tag.rsplit('}',1)[-1]
    body=next((node for node in root.iter()if local(node)=='body'),None)
    if body is None:raise ValueError('旧文档没有返回可定位的正文')
    sections=[];warnings=[];total=0;tables=0;paragraphs=0
    def add(locator,text,**metadata):
        nonlocal total
        text=text.replace('\x00','').strip()
        if not text:return
        total+=len(text)
        if total>max_chars:raise ValueError(f'旧文档正文超过 {max_chars:,} 字，未截断；请按事项拆分')
        sections.append({'locator':locator,'text':text,**metadata})
    def walk(node):
        nonlocal tables,paragraphs
        tag=local(node)
        if tag=='table':
            tables+=1
            for row_no,row in enumerate((n for n in node.iter()if local(n)=='tr'),1):
                cells=[' '.join(''.join(cell.itertext()).split())for cell in row if local(cell)in {'td','th'}]
                add(f'第 {tables} 表第 {row_no} 行',' | '.join(cells),table=True)
            warnings.append('旧格式表格按行提取；合并单元格及行列对应关系仍需核对原件')
            return
        if tag in {'p','h1','h2','h3','h4','h5','h6','li'}:
            paragraphs+=1;add(f'第 {paragraphs} 段',''.join(node.itertext()))
            return
        for child in node:walk(child)
    walk(body)
    if any(local(node)in {'img','object'}for node in body.iter()):
        warnings.append('旧文档含图片或嵌入对象，当前仅提取正文文字，请补充其中关键信息')
    if not sections:raise ValueError('旧文档没有可提取正文，可能已加密、损坏或仅有图片；原件仍可下载')
    return {'sections':sections,'status':'review' if warnings else 'ok','warning':'；'.join(dict.fromkeys(warnings))}


def extract(data,kind,max_chars=10000):
    if kind not in {'doc','xls'}:raise ValueError('旧格式读取仅适用于 DOC / XLS')
    ole=data.startswith(bytes.fromhex('D0CF11E0A1B11AE1'))
    rtf=kind=='doc' and data.lstrip().startswith(b'{\\rtf')
    if not (ole or rtf):raise ValueError('旧文档类型与内容不符，请核对原件格式；未按扩展名猜测正文')
    java,jar=tools()
    command=[java,'-Xmx192m','-XX:MaxMetaspaceSize=96m','-XX:MaxDirectMemorySize=16m',
             '-XX:ReservedCodeCacheSize=32m','-Xss512k','-Djava.awt.headless=true','-Dfile.encoding=UTF-8',
             '-jar',str(jar),'--config='+str(ROOT/'schema/legacy-office-tika.json'),
             '--xml','--encoding=UTF-8','--maxEmbeddedDepth=0','--maxEmbeddedCount=0','-']
    # Do not pass model keys, mailbox credentials, proxy configuration or JVM
    # injection options from the application environment into the parser.
    environment={key:value for key,value in os.environ.items()if key.upper()in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP'}}
    environment.update(LANG='C.UTF-8',LC_ALL='C.UTF-8')
    with tempfile.TemporaryFile()as output,tempfile.TemporaryFile()as errors:
        try:
            result=subprocess.run(command,input=data,stdout=output,stderr=errors,env=environment,
                                  cwd=jar.parent,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired:
            raise ValueError('旧格式解析超时，原件已保留；请拆分文档或提供新版格式')from None
        if result.returncode:raise ValueError('旧格式正文无法可靠提取，可能已加密或损坏；请提供可读取版本')
        if output.tell()>OUTPUT_BYTES:raise ValueError('旧格式提取结果过大，未截断；请按事项拆分')
        output.seek(0);return sections_from_xhtml(output.read(),max_chars)
