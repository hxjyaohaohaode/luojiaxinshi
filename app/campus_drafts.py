"""Private server-side publication drafts, separate from delivered notices."""
import json
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import Field, field_validator

from .db import dumps
from .documents import MAX_CHARS, total_chars
from .models import Strict
from .campus_policy import PublicationPolicy

SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_drafts(
 id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 college_id TEXT NOT NULL REFERENCES campus_colleges(id), data TEXT NOT NULL,
 version INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,id));
CREATE TABLE IF NOT EXISTS campus_draft_files(
 draft_id TEXT NOT NULL, user_id TEXT NOT NULL, position INTEGER NOT NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL,
 sections TEXT NOT NULL, status TEXT NOT NULL, warning TEXT NOT NULL,
 PRIMARY KEY(user_id,draft_id,position),
 FOREIGN KEY(user_id,draft_id) REFERENCES campus_drafts(user_id,id) ON DELETE CASCADE);
"""


class Draft(PublicationPolicy):
    version: int = Field(default=0, ge=0)
    title: str = Field(default='', max_length=160)
    body: str = Field(default='', max_length=MAX_CHARS)
    audience: str = Field(default='', pattern=r'^(|college|grade|class)$')
    grade: str = Field(default='', max_length=40)
    class_name: str = Field(default='', max_length=80)
    keep_attachments: bool = True
    pending_attachment_names: list[Annotated[str,Field(min_length=1,max_length=255)]] = Field(default_factory=list,max_length=3)

    @field_validator('pending_attachment_names')
    @classmethod
    def meaningful_attachment_names(cls, names):
        if any(not name.strip() for name in names):
            raise ValueError('待重新选择的附件名称不能为空白')
        return names


def view(conn, row):
    data=json.loads(row['data'])
    return {'id':row['id'], **data, 'pending_attachment_names':data.get('pending_attachment_names',[]), 'version':row['version'],
            'updated_at':row['updated_at'], 'state':'draft',
            'attachments':[dict(f) for f in conn.execute('''SELECT name,kind,sha256,status,warning,
                length(content) AS size FROM campus_draft_files WHERE user_id=? AND draft_id=? ORDER BY position''',
                (row['user_id'],row['id']))]}


def draft_files(conn, uid, draft_id):
    return [{**dict(row), 'sections':json.loads(row['sections'])} for row in conn.execute(
        'SELECT * FROM campus_draft_files WHERE user_id=? AND draft_id=? ORDER BY position',(uid,draft_id))]


def install(app, db, user):
    from .campus import publisher, request_materials

    @app.get('/api/campus/drafts')
    def drafts(current=Depends(user)):
        with db.connect() as conn:
            own = publisher(conn,current['id'])
            rows=conn.execute('SELECT * FROM campus_drafts WHERE user_id=? AND college_id=? ORDER BY updated_at DESC,id',
                              (current['id'],own['college_id'])).fetchall()
            return {'items':[view(conn,row) for row in rows]}

    @app.get('/api/campus/drafts/{draft_id}')
    def detail(draft_id:str,current=Depends(user)):
        with db.connect() as conn:
            own=publisher(conn,current['id'])
            row=conn.execute('SELECT * FROM campus_drafts WHERE user_id=? AND id=? AND college_id=?',
                             (current['id'],draft_id,own['college_id'])).fetchone()
            if row is None:raise HTTPException(404,'草稿不存在或无权查看')
            return view(conn,row)

    @app.put('/api/campus/drafts/{draft_id}')
    async def save(draft_id:str,request:Request,current=Depends(user)):
        if not 1<=len(draft_id)<=80 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in draft_id):
            raise HTTPException(422,'草稿编号不正确')
        with db.connect() as conn:publisher(conn,current['id'])
        payload,new_files=await request_materials(request,Draft)
        uid=current['id']
        with db.connect(write=True) as conn:
            own=publisher(conn,uid)
            previous=conn.execute('SELECT * FROM campus_drafts WHERE user_id=? AND id=?',(uid,draft_id)).fetchone()
            if previous and previous['college_id']!=own['college_id']:
                raise HTTPException(403,'学院身份已变化，原学院草稿不能转入当前发布范围')
            if payload.version!=(previous['version'] if previous else 0):
                raise HTTPException(409,'草稿已在另一端更新，本次输入未覆盖；请核对服务器草稿')
            if not previous and conn.execute('SELECT count(*) FROM campus_drafts WHERE user_id=?',(uid,)).fetchone()[0]>=50:
                raise HTTPException(413,'最多保留50份发布草稿，请先整理已有草稿')
            files=(draft_files(conn,uid,draft_id) if payload.keep_attachments else [])+new_files
            if len(files)>3 or sum(len(f['content']) for f in files)>8*1024*1024:
                raise HTTPException(422,'草稿最多保留3份附件，附件合计不超过8 MB')
            if len(payload.title)+len(payload.body)+total_chars(files)>MAX_CHARS:
                raise HTTPException(422,'草稿正文和附件提取文字合计不能超过10000字')
            from .campus_assets import check_publication_storage
            check_publication_storage(conn,uid,sum(len(file['content']) for file in files),replace_draft=draft_id)
            data=payload.model_dump(exclude={'version','keep_attachments'})
            # Omission by an older client is not an explicit decision to drop
            # missing originals. Only a supplied empty list resolves the gate.
            if previous and 'pending_attachment_names' not in payload.model_fields_set:
                data['pending_attachment_names']=json.loads(previous['data']).get('pending_attachment_names',[])
            version,now=payload.version+1,int(time.time())
            conn.execute('''INSERT INTO campus_drafts VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,id)
                DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at''',
                (draft_id,uid,own['college_id'],dumps(data),version,now))
            conn.execute('DELETE FROM campus_draft_files WHERE user_id=? AND draft_id=?',(uid,draft_id))
            for position,file in enumerate(files):
                conn.execute('INSERT INTO campus_draft_files VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (draft_id,uid,position,file['name'],file['kind'],file['content'],file['sha256'],
                     dumps(file['sections']),file['status'],file.get('warning','')))
            return view(conn,conn.execute('SELECT * FROM campus_drafts WHERE user_id=? AND id=?',(uid,draft_id)).fetchone())

    @app.delete('/api/campus/drafts/{draft_id}')
    def remove(draft_id:str,version:int,current=Depends(user)):
        with db.connect(write=True) as conn:
            publisher(conn,current['id'])
            row=conn.execute('SELECT version FROM campus_drafts WHERE user_id=? AND id=?',(current['id'],draft_id)).fetchone()
            if row is None:raise HTTPException(404,'草稿不存在')
            if row['version']!=version:raise HTTPException(409,'草稿已更新，请重新核对后删除')
            conn.execute('DELETE FROM campus_drafts WHERE user_id=? AND id=?',(current['id'],draft_id))
            return {'ok':True}

