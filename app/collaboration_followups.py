"""Private, optional follow-up clocks; never school-imposed deadlines."""
from datetime import datetime, timezone
import hashlib
import time

from fastapi import Depends, HTTPException
from pydantic import Field, field_validator

from .db import dumps
from .models import Strict, TaskData


SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_followups(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 case_id TEXT NOT NULL REFERENCES collaboration_cases(id) ON DELETE CASCADE,
 due_at INTEGER, version INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
 PRIMARY KEY(user_id,case_id));
CREATE INDEX IF NOT EXISTS collaboration_followups_due
 ON collaboration_followups(user_id,due_at);
"""


class Followup(Strict):
    version: int = Field(ge=0)
    due_at: str | None = Field(default=None,max_length=50)
    request_id: str = Field(min_length=16,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('due_at')
    @classmethod
    def time_zone(cls,value):
        result=TaskData.valid_datetime(value)
        if result is not None:
            parsed=datetime.fromisoformat(result)
            if not 2000<=parsed.year<=2100:raise ValueError('跟进时间须在2000至2100年之间')
            return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
        return None


def view(conn,case,uid,now=None):
    row=conn.execute('SELECT * FROM collaboration_followups WHERE user_id=? AND case_id=?',
                     (uid,case['id'])).fetchone()
    can_set=bool(case['in_scope'] and case['state'] not in {'resolved','withdrawn'})
    due=row['due_at'] if row else None
    return {'case_id':case['id'],'title':case['title'],'version':row['version'] if row else 0,
            'due_at':datetime.fromtimestamp(due,timezone.utc).isoformat(timespec='seconds') if due is not None else None,
            'active':bool(can_set and due is not None),'can_set':can_set,
            'overdue':bool(can_set and due is not None and due<=(int(time.time()) if now is None else now)),
            'private':True,'kind':'personal_followup',
            'note':'仅提醒本人核对进展，不修改校方截止或对方安排。协作关闭或当前授权失效后停止提醒。'}


def due_reminders(conn,uid,now):
    from .collaboration import IN_SCOPE
    return [dict(row) for row in conn.execute(f"""SELECT c.id,c.title,'followup' AS state,
        f.version,f.due_at AS updated_at FROM collaboration_followups f
        JOIN collaboration_cases c ON c.id=f.case_id
        WHERE f.user_id=? AND f.due_at<=? AND c.state NOT IN ('resolved','withdrawn')
          AND (c.sender_id=f.user_id OR c.recipient_id=f.user_id) AND {IN_SCOPE}
        ORDER BY f.due_at,c.id""",(uid,now))]


def install(app,db,user):
    from .collaboration import owned_case

    @app.get('/api/collaboration/{cid}/followup')
    def detail(cid:str,current=Depends(user)):
        with db.connect() as conn:
            return view(conn,owned_case(conn,current['id'],cid),current['id'])

    @app.put('/api/collaboration/{cid}/followup')
    def save(cid:str,payload:Followup,current=Depends(user)):
        uid=current['id']
        request_digest=hashlib.sha256(dumps(payload.model_dump()).encode()).hexdigest()
        with db.connect(write=True) as conn:
            case=owned_case(conn,uid,cid)
            previous=conn.execute('SELECT * FROM collaboration_followups WHERE user_id=? AND case_id=?',(uid,cid)).fetchone()
            if previous and previous['request_id']==payload.request_id:
                if previous['request_digest']!=request_digest:raise HTTPException(409,'同一跟进编号已用于其他内容')
                return view(conn,case,uid)
            if payload.version!=(previous['version'] if previous else 0):
                raise HTTPException(409,'本人的跟进安排已在另一端更新，本次输入未覆盖；请核对最新时间')
            now=int(time.time())
            due=int(datetime.fromisoformat(payload.due_at).timestamp()) if payload.due_at else None
            if due is not None:
                if not case['in_scope'] or case['state'] in {'resolved','withdrawn'}:
                    raise HTTPException(409,'协作已关闭或当前授权失效，不能继续安排跟进')
                if due<=now:raise HTTPException(422,'请选择未来的本人跟进时间')
            if due==(previous['due_at'] if previous else None):return view(conn,case,uid)
            conn.execute('''INSERT INTO collaboration_followups VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_id,case_id) DO UPDATE SET due_at=excluded.due_at,
                version=excluded.version,updated_at=excluded.updated_at,
                request_id=excluded.request_id,request_digest=excluded.request_digest''',
                (uid,cid,due,payload.version+1,now,payload.request_id,request_digest))
            return view(conn,case,uid)
