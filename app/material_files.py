"""Private material library readers. Preserve the full source separately from model excerpts."""
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import PurePosixPath
from html.parser import HTMLParser
from defusedxml import ElementTree as ET
from .config import ROOT
from .db import ident
from .documents import PARSER_SLOTS

MAX_UPLOAD=20*1024*1024
MAX_PREVIEW=1000000
TEXT_KINDS={'txt','md','csv','tsv','json','jsonl','xml','yaml','yml','log','ini','toml','sql','py','js','ts','css','c','cpp','h','java','tex','ics','eml','html','htm','svg','rtf'}
FORMATS=TEXT_KINDS|{'pdf','docx','xlsx','pptx','odt','ods','odp','png','jpg','jpeg','webp','gif','bmp','tiff','tif','mp4','webm','mov','avi','wmv','mp3','wav','m4a','ogg','flac','doc','xls','ppt'}

def safe_path(value):
    value=str(value).replace('\\','/').strip('/')
    parts=value.split('/')
    if not value or len(value)>600 or len(parts)>20 or any(p in {'','.','..'} or ':' in p or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('文件路径无效，请移除路径中的特殊字符后重试')
    return '/'.join(parts)

def decode(data):
    encodings=('utf-16',) if data[:2] in {b'\xff\xfe',b'\xfe\xff'} else ('utf-8-sig','gb18030')
    for encoding in encodings:
        try:return data.decode(encoding)
        except UnicodeError:pass
    raise ValueError('文字编码无法读取，请另存为 UTF-8')

class PlainHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.skip+=1
        if tag in {'p','div','br','tr','li','h1','h2','h3'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.skip=max(0,self.skip-1)
    def handle_data(self,text):
        if not self.skip:self.parts.append(text)

def full_extract(data,kind):
    if kind in TEXT_KINDS:
        text=decode(data)
        if kind in {'html','htm'}:
            parser=PlainHTML();parser.feed(text);text=''.join(parser.parts)
        elif kind=='rtf':
            text=re.sub(r'\\u(-?\d+)\??',lambda m:chr(int(m[1])%65536),text)
            text=re.sub(r"\\'[0-9a-fA-F]{2}",lambda m:bytes.fromhex(m[0][2:]).decode('cp1252'),text)
            text=re.sub(r'\\(?:par|line)\b','\n',text);text=re.sub(r'\\[a-zA-Z]+-?\d* ?|[{}]','',text)
        if len(text)>MAX_PREVIEW:raise ValueError('全文超过 100 万字，请拆分材料；原件可保留下载')
        if kind in {'csv','tsv'}:
            rows=csv.reader(io.StringIO(text),delimiter='\t' if kind=='tsv' else ',')
            sections=[{'locator':f'第 {i} 行','text':'\t'.join(row),'table':True} for i,row in enumerate(rows,1)]
        else:sections=[{'locator':f'第 {i} 段','text':line} for i,line in enumerate(text.splitlines(),1) if line.strip()]
        return {'sections':sections,'status':'ok','warning':''}
    if kind in {'pptx','odt','ods','odp'}:
        sections=[]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos=z.infolist()
            if len(infos)>1500 or sum(x.file_size for x in infos)>80*1024*1024 or any(x.flag_bits&1 for x in infos):raise ValueError('文档解压大小超限或已加密，请拆分或解密后上传')
            if any('vbaproject' in x.filename.lower() for x in infos):raise ValueError('请另存为不含宏的文档')
            names=sorted((x.filename for x in infos if re.fullmatch(r'ppt/slides/slide\d+\.xml',x.filename)),key=lambda n:int(re.search(r'(\d+)\.xml',n)[1])) if kind=='pptx' else ['content.xml']
            for i,name in enumerate(names,1):
                root=ET.fromstring(z.read(name))
                tags={'t'} if kind=='pptx' else {'p','h'}
                text='\n'.join(''.join(n.itertext()) for n in root.iter() if n.tag.split('}')[-1] in tags)
                if text:sections.append({'locator':f'第 {i} 页' if kind=='pptx' else '文档正文','text':text})
        if sum(len(s['text']) for s in sections)>MAX_PREVIEW:raise ValueError('全文超过预览上限，请拆分材料')
        return {'sections':sections,'status':'review','warning':'全文文字预览；版式、图片、图表请对照原件。'}
    if kind in {'mp4','webm','mov','avi','wmv','mp3','wav','m4a','ogg','flac'}:
        from .media_input import inspect_media
        return inspect_media(data,kind)
    if kind in {'doc','xls','ppt'}:
        return {'sections':[],'status':'review','warning':'原件已保存，可下载；尚未读取正文。请另存为 DOCX / XLSX / PPTX 后上传。'}
    if kind in {'gif','bmp','tif','tiff'}:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=20000000
        with Image.open(io.BytesIO(data)) as picture:picture.verify()
        return {'sections':[],'status':'review','warning':'图片原件已保存，当前模型尚未读取这种图片格式；请转为 PNG、JPG 或 WebP 后上传。'}
    from . import parser_worker
    parser_worker.MAX_TEXT=MAX_PREVIEW
    if kind=='docx':
        result=parser_worker.extract(data,kind)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml',name):
                    root=ET.fromstring(archive.read(name));text='\n'.join(''.join(p.itertext()) for p in root.iter() if p.tag.endswith('}p'))
                    if text:result['sections'].append({'locator':name,'text':text})
        result['warning']='全文文字与内嵌图片可预览；段落版式请对照原件。';result['status']='review'
        if sum(len(s['text']) for s in result['sections'])>MAX_PREVIEW:raise ValueError('全文超过 100 万字，请拆分后读取；原件仍可下载')
        return result
    if kind in {'csv','xlsx'}:
        from .spreadsheet import spreadsheet_sections
        return spreadsheet_sections(data,kind,full=True)
    return parser_worker.extract(data,kind)

def library_file(filename,data,path=None):
    path=safe_path(path or filename);name=PurePosixPath(path).name[:160];kind=PurePosixPath(name).suffix.lower().lstrip('.')
    if kind not in FORMATS:raise ValueError(f'{name}：暂不支持这个格式，请转换为 PDF、文字或新版 Office')
    if not data or len(data)>MAX_UPLOAD:raise ValueError(f'{name}：每份文件应为 1 字节至 20 MB')
    if not PARSER_SLOTS.acquire(timeout=2):raise ValueError('正在读取其他材料，请稍后重新上传')
    try:
        proc=subprocess.run([sys.executable,'-m','app.material_files',kind],input=data,capture_output=True,timeout=25,cwd=ROOT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if proc.returncode or len(proc.stdout)>8*1024*1024:raise ValueError('解析未正常返回')
        result=json.loads(proc.stdout)
    except (subprocess.TimeoutExpired,ValueError,OSError):
        result={'sections':[],'status':'failed','warning':'读取失败，原件已保存。请转换格式或补充文字后重试。'}
    finally:PARSER_SLOTS.release()
    sections=result['sections'];excerpt=[];remaining=10000
    for section in sections:
        if remaining<=0:break
        excerpt.append({**section,'text':section['text'][:remaining]});remaining-=len(excerpt[-1]['text'])
    return {'id':ident(),'name':name,'kind':kind,'content':data,'sha256':hashlib.sha256(data).hexdigest(),'path':path,'full_sections':sections,**result,'sections':excerpt}

def expand_files(filename,data,path=None):
    if not filename.lower().endswith('.zip'):return [library_file(filename,data,path)]
    prefix=PurePosixPath(safe_path(path or filename)).with_suffix('').as_posix()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        items=[i for i in z.infolist() if not i.is_dir()]
        if not items or len(items)>100 or sum(i.file_size for i in items)>80*1024*1024 or any(i.flag_bits&1 for i in items):raise ValueError('ZIP 最多 100 个文件、解压后 80 MB；请先解密或拆分')
        paths=[safe_path(prefix+'/'+i.filename) for i in items]
        if len(set(paths))!=len(paths):raise ValueError('ZIP 含重复路径，请整理后重试')
        return [library_file(PurePosixPath(p).name,z.read(i),p) for i,p in zip(items,paths)]

if __name__=='__main__':
    try:result=full_extract(sys.stdin.buffer.read(MAX_UPLOAD+1),sys.argv[1])
    except Exception as error:result={'sections':[],'status':'failed','warning':str(error) if isinstance(error,ValueError) else '文件损坏或结构不受支持，请转换格式或补充文字。'}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode())
