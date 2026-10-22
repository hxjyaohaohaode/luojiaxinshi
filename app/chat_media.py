"""Private, bounded playback references; model transport lives in media_input."""
import hashlib
import re
from pathlib import Path
from urllib.parse import quote
from fastapi import Response
from .db import ident
from .documents import file_source, MAX_FILE

VIDEO_MIME={'mp4':'video/mp4','webm':'video/webm','mov':'video/quicktime','avi':'video/x-msvideo','wmv':'video/x-ms-wmv'}
IMAGE_KINDS={'png','jpg','jpeg','webp'}


def chat_file_source(filename,data,max_file=MAX_FILE):
    name=re.split(r'[/\\]',filename)[-1][:160]
    kind=Path(name).suffix.lower().lstrip('.')
    if kind not in VIDEO_MIME:return file_source(filename,data)
    if not data or len(data)>max_file:raise ValueError(f'每份附件须大于 0 字节且不超过 {max_file//1024//1024} MB')
    valid=(kind=='mp4' and len(data)>=24 and data[4:8]==b'ftyp' and int.from_bytes(data[:4],'big')>=16)
    valid=valid or (kind=='webm' and data[:4]==b'\x1aE\xdf\xa3' and b'webm' in data[:4096])
    if not valid:raise ValueError('视频格式与内容不符，请上传 MP4 或 WebM 原文件')
    return {'id':ident(),'name':name,'kind':kind,'content':data,'sha256':hashlib.sha256(data).hexdigest(),
            'sections':[],'status':'review','warning':'视频仅供本机播放，模型未观看视频。请补充文字说明或字幕作为对话依据。'}


def resource_index(sources):
    result=[]
    for s in sources:
        cid,sid=s.get('conversation_id',''),s.get('id','')
        if s.get('status')=='failed' or s.get('kind') not in IMAGE_KINDS|VIDEO_MIME.keys():continue
        if not re.fullmatch('[a-f0-9]{32}',cid) or not re.fullmatch('[a-f0-9]{32}',sid):continue
        result.append({'id':sid,'kind':'image' if s['kind'] in IMAGE_KINDS else 'video','name':s['name'],
                       'src':f'/api/conversations/{cid}/sources/{sid}/download?preview=true'})
    return result


def video_response(content,kind,name,range_header=None,inline=True):
    headers={'Accept-Ranges':'bytes','Content-Disposition':('inline' if inline else 'attachment')+"; filename*=UTF-8''"+quote(name)}
    size=len(content)
    if not range_header:return Response(content,media_type=VIDEO_MIME[kind],headers=headers)
    match=re.fullmatch(r'bytes=(\d{0,12})-(\d{0,12})',range_header)
    if match and any(match.groups()):
        left,right=match.groups()
        start=int(left) if left else max(0,size-int(right))
        end=min(size-1,int(right)) if left and right else size-1
        if start<=end and start<size and (left or int(right)>0):
            headers['Content-Range']=f'bytes {start}-{end}/{size}'
            return Response(content[start:end+1],status_code=206,media_type=VIDEO_MIME[kind],headers=headers)
    headers['Content-Range']=f'bytes */{size}'
    return Response(status_code=416,headers=headers)
