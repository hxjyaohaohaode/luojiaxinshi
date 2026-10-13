"""Add-only, owner-scoped import of the application's portable text export."""
import hashlib
import json
import time
from fastapi import Depends,HTTPException
from pydantic import Field,ValidationError
from .db import dumps,ident
from .models import Strict,Profile,TaskData,safe_url
from .schedule import Arrangement
from .security import rate_limit


class ImportRequest(Strict):
    data: dict
    confirm: bool = False
    digest: str = Field(default='',max_length=64)
    apply_profile: bool = False


def bounded(value,depth=0,counter=None):
    if counter is None:counter=[0]
    counter[0]+=1
    if depth>24 or counter[0]>150000:raise ValueError('导入结构过深或内容过多')
    if isinstance(value,dict):
        if any(k in {'__proto__','constructor','prototype'} for k in value):raise ValueError('导入数据包含不允许的键')
        for item in value.values():bounded(item,depth+1,counter)
    elif isinstance(value,list):
        for item in value:bounded(item,depth+1,counter)
    elif isinstance(value,str) and len(value)>1048576:raise ValueError('导入单项文字过长')


def text(value,maximum,default=''):
    if value is None:value=default
    if not isinstance(value,str) or len(value)>maximum:raise ValueError('导入文字字段格式或长度不正确')
    return value


def collection(data,name,maximum):
    items=data.get(name,[])
    if not isinstance(items,list) or len(items)>maximum or any(not isinstance(x,dict) for x in items):raise ValueError('导入列表格式不正确或条数超限：'+name)
    return items


def key(kind,item):
    identity=item.get('id') or dumps(item)
    return hashlib.sha256((kind+':'+str(identity)).encode()).hexdigest()


def sources(items):
    result=[];total=0
    if not isinstance(items,list) or len(items)>100:raise ValueError('单份记录的材料过多')
    for s in items:
        sections=[]
        for section in collection(s,'sections',2000):
            value=text(section.get('text'),10000);total+=len(value)
            if total>100000:raise ValueError('单份记录的材料文字过多')
            sections.append({'locator':text(section.get('locator'),80),'text':value,**({'table':True} if section.get('table') is True else {})})
        result.append({'old_id':text(s.get('id'),100),'name':text(s.get('name'),160,'导入材料'),
                       'sections':sections,'warning':'从备份导入的提取文字，原始附件未包含在 JSON 中，请按需要重新补充。'})
    return result


def validate(data):
    from .workspace import CatalogItem
    bounded(data)
    if data.get('format_version')!=1:raise ValueError('仅支持本系统导出的第 1 版数据文件')
    profile=Profile.model_validate(data.get('profile',{})).model_dump()
    notices=[];chats=[]
    for n in collection(data,'notices',200):
        task_items=[]
        for task in collection(n,'tasks',100):
            details=TaskData.model_validate(task.get('data',{})).model_dump()
            # Imported backup text is not new evidence of a verified official deadline.
            details.update(deadline_confirmed=False,reminder_at=None)
            if task.get('status') not in {'pending','done','cancelled'}:raise ValueError('待办状态无效')
            task_items.append({'data':details,'status':task['status']})
        notices.append({'key':key('notice',n),'title':text(n.get('title'),160),'source_label':text(n.get('source_label'),100),
                        'source_url':safe_url(text(n.get('source_url'),2000)),'sources':sources(n.get('sources',[])),'tasks':task_items})
    for c in collection(data,'conversations',100):
        messages=[]
        for m in collection(c,'messages',2000):
            if m.get('role') not in {'user','assistant'}:raise ValueError('对话角色无效')
            timestamp=m.get('created_at')
            if type(timestamp) is not int or not 0<=timestamp<=253402300799:raise ValueError('消息时间无效')
            status=m.get('status','complete')
            if status not in {'complete','failed','cancelled','pending','processing'}:raise ValueError('消息状态无效')
            # An interrupted export is never evidence of a completed model reply.
            if status in {'pending','processing'}:status='cancelled'
            messages.append({'role':m['role'],'content':text(m.get('content'),1048576),'created_at':timestamp,'status':status})
        chats.append({'key':key('chat',c),'title':text(c.get('title'),100),'sources':sources(c.get('sources',[])),'messages':messages})
    arrangements=[{'key':key('arrangement',x),'data':Arrangement.model_validate(x.get('data',{})).model_dump()} for x in collection(data,'arrangements',1000)]
    catalog=[{'key':key('catalog',x),'data':CatalogItem.model_validate(x).model_dump()} for x in collection(data,'source_catalog',500)]
    return {'profile':profile,'notices':notices,'conversations':chats,'arrangements':arrangements,'source_catalog':catalog}


def install_data_transfer(app,db,user):
    with db.connect(write=True) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS import_receipts(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,item_key TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(user_id,item_key))')

    @app.post('/api/import')
    def import_data(payload:ImportRequest,current=Depends(user)):
        rate_limit(db,'data-import:'+current['id'],30,3600)
        raw=dumps(payload.data)
        if len(raw.encode())>10*1024*1024:raise HTTPException(413,'导入文件超过 10 MB，请拆分')
        digest=hashlib.sha256(raw.encode()).hexdigest()
        try:data=validate(payload.data)
        except (ValueError,ValidationError,TypeError,KeyError,OverflowError):raise HTTPException(422,'备份格式、字段或上限不符合要求，请使用本系统导出的 JSON 文件')
        counts={k:len(data[k]) for k in ['notices','conversations','arrangements','source_catalog']}
        warnings=['只新增记录，不覆盖现有记录；重复导入相同记录会跳过。','附件原件不在 JSON 备份内，恢复提取文字；对话恢复为可读文字，互动状态和引用编号不恢复。','导入待办的正式期限需重新核对，提醒时间清空；不会自动向外部日历写入。']
        if not payload.confirm:return {'digest':digest,'counts':counts,'warnings':warnings}
        if payload.digest!=digest:raise HTTPException(409,'文件在预览后发生变化，请重新预览')
        now=int(time.time());added=0;skipped=0
        with db.connect(write=True) as conn:
            for kind in counts:
                for item in data[kind]:
                    if conn.execute('SELECT 1 FROM import_receipts WHERE user_id=? AND item_key=?',(current['id'],item['key'])).fetchone():skipped+=1;continue
                    rid=ident()
                    if kind=='notices':
                        conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,materials_complete,fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?,?,?)',
                                     (rid,current['id'],item['title'],item['source_label'],item['source_url'],item['key'],'confirmed' if item['tasks'] else 'received',now,now))
                        mapping={}
                        for source in item['sources']:
                            sid=ident();mapping[source['old_id']]=sid
                            conn.execute("INSERT INTO sources(id,notice_id,name,kind,sha256,status,sections,warning,created_at) VALUES(?,?,?,'text',?,'review',?,?,?)",(sid,rid,source['name'],hashlib.sha256(dumps(source['sections']).encode()).hexdigest(),dumps(source['sections']),source['warning'],now))
                        for task in item['tasks']:
                            details=task['data']
                            for field in ['evidence','deadline_evidence']:
                                details[field]=[{**e,'source_id':mapping[e['source_id']]} for e in details[field] if e['source_id'] in mapping]
                            conn.execute('INSERT INTO tasks(id,user_id,notice_id,data,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(ident(),current['id'],rid,dumps(details),task['status'],now,now))
                    elif kind=='conversations':
                        conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(rid,current['id'],item['title'],now,now))
                        for source in item['sources']:
                            conn.execute("INSERT INTO conversation_sources(id,conversation_id,name,kind,sha256,status,sections,warning,created_at) VALUES(?,?,?,'text',?,'review',?,?,?)",(ident(),rid,source['name'],hashlib.sha256(dumps(source['sections']).encode()).hexdigest(),dumps(source['sections']),source['warning'],now))
                        parent=None
                        for message in item['messages']:
                            mid=ident()
                            conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at,error) VALUES(?,?,?,?,?,?,?,?)",(mid,rid,message['role'],message['content'],message['status'],parent if message['role']=='assistant' else None,message['created_at'],'从备份恢复的未完成回复，已收到的内容保留。' if message['status']!='complete' else ''))
                            if message['role']=='user':parent=mid
                    elif kind=='arrangements':conn.execute('INSERT INTO arrangements(id,user_id,request_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',(rid,current['id'],'import_'+item['key'],dumps(item['data']),now,now))
                    else:conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,?,?)',(rid,current['id'],dumps(item['data']),now,now))
                    conn.execute('INSERT INTO import_receipts VALUES(?,?,?)',(current['id'],item['key'],now));added+=1
            if payload.apply_profile:conn.execute('UPDATE users SET profile=? WHERE id=?',(dumps(data['profile']),current['id']))
        return {'added':added,'skipped':skipped,'warnings':warnings}
