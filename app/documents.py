import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

from .config import ROOT
from .db import ident

MAX_FILE = 5*1024*1024
MAX_CHARS = 10000
PARSER_SLOTS=threading.BoundedSemaphore(2)


def text_source(text, name='通知正文'):
    sections = [{'locator':f'第 {i} 段','text':line.strip()} for i,line in enumerate(text.splitlines(),1) if line.strip()]
    return {'id':ident(),'name':name,'kind':'text','content':None,'sha256':hashlib.sha256(text.encode()).hexdigest(),
            'sections':sections,'status':'ok','warning':''}


def file_source(filename, data):
    name = re.split(r'[/\\]', filename)[-1][:160]
    suffix = Path(name).suffix.lower().lstrip('.')
    if suffix in {'mp4','webm'}:
        from .chat_media import chat_file_source
        return chat_file_source(filename,data)
    if suffix not in {'pdf','docx','txt','md','csv','xlsx','png','jpg','jpeg','webp'}:
        raise ValueError('支持 PDF、DOCX、XLSX、CSV、TXT、Markdown、图片、MP4 和 WebM；DOC / XLS 请另存为新版格式')
    if not data or len(data)>MAX_FILE:
        raise ValueError('每份附件须大于 0 字节且不超过 5 MB')
    if not PARSER_SLOTS.acquire(timeout=2):
        return {'id':ident(),'name':name,'kind':suffix,'content':data,'sha256':hashlib.sha256(data).hexdigest(),
                'sections':[],'status':'failed','warning':'附件解析当前繁忙，请稍后补传；原件已保存'}
    try:
        proc = subprocess.run([sys.executable,'-m','app.parser_worker',suffix], input=data, capture_output=True,
                              timeout=20, cwd=ROOT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode or len(proc.stdout)>300000:
            raise ValueError('解析程序未正常返回')
        result = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        result = {'sections':[],'status':'failed','warning':'文件解析超时或失败，请补充文字或更换文件'}
    finally:
        PARSER_SLOTS.release()
    return {'id':ident(),'name':name,'kind':suffix,'content':data,'sha256':hashlib.sha256(data).hexdigest(),**result}


def total_chars(sources):
    return sum(len(section['text']) for source in sources for section in source['sections'])


def blockers(notice, sources):
    result=[]
    if not any(source['sections'] or source['kind'] in {'png','jpg','jpeg','webp'} and source['status']!='failed' for source in sources):
        result.append('当前没有可核对的有效材料，请补充正文或可解析附件')
    if not notice['materials_complete']:
        result.append('尚未确认通知及关键附件完整')
    for source in sources:
        if source['status'] != 'ok':
            result.append(f"{source['name']}：{source['warning']}")
    if total_chars(sources)>MAX_CHARS:
        result.append('正文与附件合计超过 10000 字，请删除无关内容或拆分通知')
    return result
