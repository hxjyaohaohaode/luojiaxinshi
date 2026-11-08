"""Explicit, scoped campus collaboration with immutable action receipts."""
import hashlib
import json
import time
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, Response
from pydantic import Field

from .db import dumps, ident
from .models import Strict
from .task_materials import SubmittedFile


SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_cases(
 id TEXT PRIMARY KEY, sender_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 recipient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 college_id TEXT NOT NULL REFERENCES campus_colleges(id),
 task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL, task_version INTEGER NOT NULL,
 title TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('sent','accepted','supplement','resubmitted','resolved','withdrawn')),
 version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 request_id TEXT NOT NULL, request_digest TEXT NOT NULL, UNIQUE(sender_id,request_id));
CREATE INDEX IF NOT EXISTS collaboration_sent ON collaboration_cases(sender_id,updated_at DESC,id);
CREATE INDEX IF NOT EXISTS collaboration_received ON collaboration_cases(recipient_id,updated_at DESC,id);
CREATE UNIQUE INDEX IF NOT EXISTS collaboration_open_task ON collaboration_cases(sender_id,recipient_id,task_id)
 WHERE state NOT IN ('resolved','withdrawn');
CREATE TABLE IF NOT EXISTS collaboration_events(
 case_id TEXT NOT NULL REFERENCES collaboration_cases(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, actor_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 action TEXT NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL,
 request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
 PRIMARY KEY(case_id,version), UNIQUE(case_id,actor_id,request_id));
CREATE TABLE IF NOT EXISTS collaboration_files(
 id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_version INTEGER NOT NULL,
 material_id TEXT, material_version INTEGER, name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 FOREIGN KEY(case_id,event_version) REFERENCES collaboration_events(case_id,version) ON DELETE CASCADE,
 FOREIGN KEY(material_id,material_version) REFERENCES task_material_versions(material_id,version) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS collaboration_files_case ON collaboration_files(case_id,event_version);
CREATE INDEX IF NOT EXISTS collaboration_files_material ON collaboration_files(material_id,material_version);
"""

# These are collaboration states. Personal completion and the original
# school's acceptance remain separate records.
TRANSITIONS = {
    'accept': ('recipient', {'sent','resubmitted'}, 'accepted'),
    'request_supplement': ('recipient', {'accepted'}, 'supplement'),
    'resubmit': ('sender', {'supplement'}, 'resubmitted'),
    'resolve': ('recipient', {'accepted'}, 'resolved'),
    'withdraw': ('sender', {'sent','accepted','supplement','resubmitted'}, 'withdrawn'),
}

# Re-evaluate the current assignment for reads and writes. Sharing one case
# does not grant access to the sender's other documents or tasks.
IN_SCOPE = """EXISTS(SELECT 1 FROM campus_members student
    JOIN campus_members staff ON staff.college_id=student.college_id
    WHERE student.user_id=c.sender_id AND staff.user_id=c.recipient_id
      AND student.college_id=c.college_id AND student.role='student'
      AND (staff.role='college_admin' OR staff.role='counselor' AND EXISTS(
        SELECT 1 FROM campus_counselor_scopes s WHERE s.user_id=staff.user_id
        AND (s.grade='' OR s.grade=student.grade AND (s.class_name='' OR s.class_name=student.class_name)))))"""


class RequestBase(Strict):
    request_id: str = Field(min_length=16,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    note: str = Field(max_length=2000)
    files: list[SubmittedFile] = Field(default_factory=list,max_length=20)


class CreateCase(RequestBase):
    task_id: str = Field(min_length=1,max_length=40)
    task_version: int = Field(ge=1)
    recipient_id: str = Field(min_length=1,max_length=40)


class Act(RequestBase):
    version: int = Field(ge=1)
    action: Literal['accept','request_supplement','resubmit','resolve','withdraw']


def digest(payload):
    return hashlib.sha256(dumps(payload.model_dump()).encode()).hexdigest()


def targets(conn,uid):
    return [dict(row) for row in conn.execute("""SELECT u.id,u.display_name,m.role
        FROM campus_members student JOIN campus_members m ON m.college_id=student.college_id
        JOIN users u ON u.id=m.user_id
        WHERE student.user_id=? AND student.role='student'
          AND (m.role='college_admin' OR m.role='counselor' AND EXISTS(
            SELECT 1 FROM campus_counselor_scopes s WHERE s.user_id=m.user_id
              AND (s.grade='' OR s.grade=student.grade AND (s.class_name='' OR s.class_name=student.class_name))))
        ORDER BY CASE WHEN m.role='counselor' THEN 0 ELSE 1 END,u.display_name,u.id""",(uid,))]


def own_task(conn,uid,tid):
    task=conn.execute('SELECT * FROM tasks WHERE user_id=? AND id=?',(uid,tid)).fetchone()
    if task is None:raise HTTPException(404,'此个人事项已移除或不可访问')
    return task


def owned_case(conn,uid,cid):
    row=conn.execute(f"""SELECT c.*,s.display_name AS sender,r.display_name AS recipient,
        {IN_SCOPE} AS in_scope FROM collaboration_cases c
        JOIN users s ON s.id=c.sender_id JOIN users r ON r.id=c.recipient_id
        WHERE c.id=? AND (c.sender_id=? OR (c.recipient_id=? AND {IN_SCOPE}))""",(cid,uid,uid)).fetchone()
    if row is None:raise HTTPException(404,'协作事项已移除或不可访问')
    return row


def project(row,uid):
    direction='sender' if row['sender_id']==uid else 'recipient'
    actions=[name for name,(side,states,_) in TRANSITIONS.items()
             if direction==side and row['state'] in states and (row['in_scope'] or name=='withdraw')]
    return {**{k:row[k] for k in ('id','title','state','version','created_at','updated_at','sender','recipient','task_version')},
            'side':direction,'task_id':row['task_id'] if direction=='sender' else None,
            'recipient_available':bool(row['in_scope']),'actions':actions}


def case_view(conn,row,uid):
    result=project(row,uid)
    files={}
    for item in conn.execute('SELECT * FROM collaboration_files WHERE case_id=? ORDER BY event_version,rowid',(row['id'],)):
        url=f"/api/collaboration/{row['id']}/files/{item['id']}"
        available=item['material_id'] is not None and (result['side']=='sender' or row['state']!='withdrawn')
        files.setdefault(item['event_version'],[]).append({
            'name':item['name'],'size':item['size'],'sha256':item['sha256'],
            'download_url':url if available else None})
    result['events']=[{**dict(event),'files':files.get(event['version'],[])} for event in conn.execute(
        """SELECT e.version,e.action,e.note,e.created_at,u.display_name AS actor
        FROM collaboration_events e JOIN users u ON u.id=e.actor_id WHERE e.case_id=? ORDER BY e.version""",(row['id'],))]
    if 'resubmit' in result['actions'] and row['task_id']:
        result['file_choices']=file_choices(conn,uid,row['task_id'])
    return result


def reminders(conn,uid,now):
    return [dict(row) for row in conn.execute(f"""SELECT id,title,state,version,updated_at FROM collaboration_cases c
        WHERE (c.recipient_id=? AND c.state IN ('sent','resubmitted') AND {IN_SCOPE})
        OR (c.sender_id=? AND (c.state='supplement' OR c.state='resolved' AND c.updated_at>=?))
        ORDER BY c.updated_at DESC,c.id""",(uid,uid,now-7*86400))]


def file_choices(conn,uid,tid):
    return [dict(row) for row in conn.execute("""SELECT v.material_id,v.version,v.name,m.requirement,length(v.content) AS size
        FROM task_materials m JOIN task_material_versions v ON v.material_id=m.id AND v.version=m.version
        WHERE m.user_id=? AND m.task_id=? ORDER BY m.created_at,m.id""",(uid,tid))]


def save_event(conn,cid,version,uid,action,payload,tid,now):
    conn.execute('INSERT INTO collaboration_events VALUES(?,?,?,?,?,?,?,?)',
                 (cid,version,uid,action,payload.note,now,payload.request_id,digest(payload)))
    seen=set()
    for selection in payload.files:
        key=(selection.material_id,selection.version)
        if key in seen:raise HTTPException(422,'同一材料版本只能分享一次')
        seen.add(key)
        material=conn.execute("""SELECT v.name,v.sha256,length(v.content) AS size FROM task_material_versions v
            JOIN task_materials m ON m.id=v.material_id
            WHERE m.user_id=? AND m.task_id=? AND v.material_id=? AND v.version=?""",(uid,tid,*key)).fetchone()
        if material is None:raise HTTPException(409,'所选材料版本已移除或不可访问，请重新选择')
        conn.execute('INSERT INTO collaboration_files VALUES(?,?,?,?,?,?,?,?)',
                     (ident(),cid,version,*key,material['name'],material['sha256'],material['size']))


def install(app,db,user):
    @app.get('/api/collaboration')
    def inbox(side:Literal['sender','recipient']='recipient',page:int=Query(1,ge=1,le=10000),current=Depends(user)):
        uid=current['id']
        condition='c.sender_id=?' if side=='sender' else f'c.recipient_id=? AND {IN_SCOPE}'
        with db.connect() as conn:
            rows=conn.execute(f"""SELECT c.*,s.display_name AS sender,r.display_name AS recipient,
                {IN_SCOPE} AS in_scope FROM collaboration_cases c JOIN users s ON s.id=c.sender_id
                JOIN users r ON r.id=c.recipient_id WHERE {condition}
                ORDER BY c.updated_at DESC,c.id DESC LIMIT 31 OFFSET ?""",(uid,(page-1)*30)).fetchall()
        return {'items':[project(r,uid) for r in rows[:30]],'has_more':len(rows)>30,'page':page}

    @app.get('/api/collaboration/tasks/{tid}/options')
    def options(tid:str,current=Depends(user)):
        uid=current['id']
        with db.connect() as conn:
            task=own_task(conn,uid,tid)
            return {'task_id':tid,'version':task['version'],'title':json.loads(task['data'])['title'],
                    'recipients':targets(conn,uid),'files':file_choices(conn,uid,tid)}

    @app.post('/api/collaboration')
    def create(payload:CreateCase,current=Depends(user)):
        uid=current['id']
        with db.connect(write=True) as conn:
            prior=conn.execute('SELECT id,request_digest FROM collaboration_cases WHERE sender_id=? AND request_id=?',
                               (uid,payload.request_id)).fetchone()
            if prior:
                if prior['request_digest']!=digest(payload):raise HTTPException(409,'同一提交编号已有不同内容')
                return case_view(conn,owned_case(conn,uid,prior['id']),uid)
            if not payload.note:raise HTTPException(422,'请填写需要对方处理的事情')
            task=own_task(conn,uid,payload.task_id)
            if task['version']!=payload.task_version or task['status']=='cancelled':
                raise HTTPException(409,'事项版本或状态已变，请重新核对后发起')
            if not any(item['id']==payload.recipient_id for item in targets(conn,uid)):
                raise HTTPException(403,'该接收人当前不在本站授权办理范围')
            existing=conn.execute("""SELECT id FROM collaboration_cases WHERE sender_id=? AND recipient_id=? AND task_id=?
                AND state NOT IN ('resolved','withdrawn')""",(uid,payload.recipient_id,task['id'])).fetchone()
            if existing:
                raise HTTPException(409,{'code':'case_open','message':'此事项已有未办结协作，可以继续查看。','case_id':existing['id']})
            college_id=conn.execute('SELECT college_id FROM campus_members WHERE user_id=?',(uid,)).fetchone()[0]
            cid,now=ident(),int(time.time())
            conn.execute('INSERT INTO collaboration_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (cid,uid,payload.recipient_id,college_id,task['id'],task['version'],
                          json.loads(task['data'])['title'],'sent',1,now,now,payload.request_id,digest(payload)))
            save_event(conn,cid,1,uid,'send',payload,task['id'],now)
            return case_view(conn,owned_case(conn,uid,cid),uid)

    @app.get('/api/collaboration/{cid}')
    def detail(cid:str,current=Depends(user)):
        with db.connect() as conn:
            conn.execute('BEGIN')
            return case_view(conn,owned_case(conn,current['id'],cid),current['id'])

    @app.post('/api/collaboration/{cid}/actions')
    def act(cid:str,payload:Act,current=Depends(user)):
        uid=current['id']
        with db.connect(write=True) as conn:
            case=owned_case(conn,uid,cid)
            prior=conn.execute('SELECT request_digest FROM collaboration_events WHERE case_id=? AND actor_id=? AND request_id=?',
                               (cid,uid,payload.request_id)).fetchone()
            if prior:
                if prior['request_digest']!=digest(payload):raise HTTPException(409,'同一提交编号已有不同内容')
                return case_view(conn,case,uid)
            if case['version']!=payload.version:
                raise HTTPException(409,'协作状态已在另一端更新，请核对最新记录后再提交')
            if payload.action not in project(case,uid)['actions']:
                raise HTTPException(403,'当前身份、范围或流程状态不允许此操作')
            if payload.action in {'request_supplement','resubmit','resolve'} and not payload.note:
                raise HTTPException(422,'请填写补件说明、补交情况或办结回执')
            if payload.files and payload.action!='resubmit':
                raise HTTPException(422,'仅发起人补交时可以选择新的个人材料')
            state=TRANSITIONS[payload.action][2]
            version,now=case['version']+1,int(time.time())
            conn.execute('UPDATE collaboration_cases SET state=?,version=?,updated_at=? WHERE id=?',(state,version,now,cid))
            save_event(conn,cid,version,uid,payload.action,payload,case['task_id'],now)
            return case_view(conn,owned_case(conn,uid,cid),uid)

    @app.get('/api/collaboration/{cid}/files/{fid}')
    def download(cid:str,fid:str,current=Depends(user)):
        uid=current['id']
        with db.connect() as conn:
            conn.execute('BEGIN')
            case=owned_case(conn,uid,cid)
            if uid!=case['sender_id'] and case['state']=='withdrawn':
                raise HTTPException(404,'材料分享已撤回')
            item=conn.execute("""SELECT f.name,v.content FROM collaboration_files f
                JOIN task_material_versions v ON v.material_id=f.material_id AND v.version=f.material_version
                WHERE f.case_id=? AND f.id=?""",(cid,fid)).fetchone()
            if item is None:raise HTTPException(404,'材料已移除或不可访问')
            return Response(item['content'],media_type='application/octet-stream',headers={
                'Content-Disposition':"attachment; filename*=UTF-8''"+quote(item['name'],safe='')})
