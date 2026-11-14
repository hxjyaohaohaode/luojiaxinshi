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
CREATE TABLE IF NOT EXISTS collaboration_retained_receipts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, case_id TEXT NOT NULL,
 side TEXT NOT NULL CHECK(side IN ('sender','recipient')),
 college_id TEXT NOT NULL, grade TEXT NOT NULL, class_name TEXT NOT NULL,
 data TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(user_id,case_id));
CREATE INDEX IF NOT EXISTS collaboration_retained_owner
 ON collaboration_retained_receipts(user_id,side,updated_at DESC,case_id);
"""
from .collaboration_followups import SCHEMA as FOLLOWUP_SCHEMA
SCHEMA += FOLLOWUP_SCHEMA

# These are collaboration states. Personal completion and the original
# school's acceptance remain separate records.
TRANSITIONS = {
    'accept': ('recipient', {'sent','resubmitted'}, 'accepted'),
    'request_supplement': ('recipient', {'accepted'}, 'supplement'),
    'resubmit': ('sender', {'supplement'}, 'resubmitted'),
    'resolve': ('recipient', {'accepted'}, 'resolved'),
    'withdraw': ('sender', {'sent','accepted','supplement','resubmitted'}, 'withdrawn'),
    'decline': ('recipient', {'sent','accepted','supplement','resubmitted'}, 'withdrawn'),
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
    action: Literal['accept','request_supplement','resubmit','resolve','withdraw','decline']


class TransferCase(RequestBase):
    version: int = Field(ge=1)
    task_version: int = Field(ge=1)
    recipient_id: str = Field(min_length=1,max_length=40)


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
        (SELECT e.action FROM collaboration_events e WHERE e.case_id=c.id ORDER BY e.version DESC LIMIT 1) AS last_action,
        {IN_SCOPE} AS in_scope FROM collaboration_cases c
        JOIN users s ON s.id=c.sender_id JOIN users r ON r.id=c.recipient_id
        WHERE c.id=? AND (c.sender_id=? OR (c.recipient_id=? AND {IN_SCOPE}))""",(cid,uid,uid)).fetchone()
    if row is None:raise HTTPException(404,'协作事项已移除或不可访问')
    return row


def project(row,uid):
    direction='sender' if row['sender_id']==uid else 'recipient'
    actions=[name for name,(side,states,_) in TRANSITIONS.items()
             if direction==side and row['state'] in states and (row['in_scope'] or name=='withdraw')]
    public_state='declined' if row['state']=='withdrawn' and row['last_action']=='decline' else row['state']
    return {**{k:row[k] for k in ('id','title','version','created_at','updated_at','sender','recipient','task_version')},
            'state':public_state,
            'side':direction,'task_id':row['task_id'] if direction=='sender' else None,
            'recipient_id':row['recipient_id'] if direction=='sender' else None,
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
    from .collaboration_followups import view as followup_view
    result['personal_followup']=followup_view(conn,row,uid)
    return result


def reminders(conn,uid,now):
    result = [dict(row) for row in conn.execute(f"""SELECT id,title,
        CASE WHEN state='withdrawn' THEN 'declined' ELSE state END AS state,
        version,updated_at FROM collaboration_cases c
        WHERE (c.recipient_id=? AND c.state IN ('sent','resubmitted') AND {IN_SCOPE})
        OR (c.sender_id=? AND (c.state='supplement' OR c.state='resolved' AND c.updated_at>=?))
        OR (c.sender_id=? AND c.state='withdrawn' AND c.updated_at>=? AND {IN_SCOPE}
          AND EXISTS(SELECT 1 FROM collaboration_events e WHERE e.case_id=c.id
              AND e.version=c.version AND e.action='decline'))
        ORDER BY c.updated_at DESC,c.id""",(uid,uid,now-7*86400,uid,now-7*86400))]
    from .collaboration_followups import due_reminders
    return result+due_reminders(conn,uid,now)


def file_choices(conn,uid,tid):
    return [dict(row) for row in conn.execute("""SELECT v.material_id,v.version,v.name,m.requirement,length(v.content) AS size
        FROM task_materials m JOIN task_material_versions v ON v.material_id=m.id AND v.version=m.version
        WHERE m.user_id=? AND m.task_id=? ORDER BY m.created_at,m.id""",(uid,tid))]


RETAINED_SCOPE = """(r.side='sender' OR EXISTS(SELECT 1 FROM campus_members m
    WHERE m.user_id=r.user_id AND m.college_id=r.college_id
      AND (m.role='college_admin' OR m.role='counselor' AND EXISTS(
        SELECT 1 FROM campus_counselor_scopes s WHERE s.user_id=m.user_id
          AND (s.grade='' OR s.grade=r.grade AND (s.class_name='' OR s.class_name=r.class_name))))))"""


def retained_receipts(conn,uid,side=None,cid=None):
    """Return only the survivor's minimal receipt, rechecking staff scope."""
    sql='SELECT r.data FROM collaboration_retained_receipts r WHERE r.user_id=? AND '+RETAINED_SCOPE
    values=[uid]
    if side:sql+=' AND r.side=?';values.append(side)
    if cid:sql+=' AND r.case_id=?';values.append(cid)
    return [json.loads(row['data']) for row in conn.execute(sql+' ORDER BY r.updated_at DESC,r.case_id DESC',values)]


def preserve_counterparty_receipts(conn,deleted_uid):
    """Minimize before CASCADE: no copied files, private notes or deleted IDs.

    The surviving student retains their own title/note. A surviving staff
    member gets an anonymous action/timestamp receipt and their own notes.
    A revoked recipient receives nothing they cannot read before deletion.
    """
    rows=conn.execute(f'''SELECT c.*,{IN_SCOPE} AS in_scope FROM collaboration_cases c
        WHERE sender_id=? OR recipient_id=?''',(deleted_uid,deleted_uid)).fetchall()
    now=int(time.time())
    retained=0
    for row in rows:
        side='recipient' if row['sender_id']==deleted_uid else 'sender'
        if side=='recipient' and not row['in_scope']:continue
        survivor=row['recipient_id'] if side=='recipient' else row['sender_id']
        student=conn.execute('SELECT grade,class_name FROM campus_members WHERE user_id=?',(row['sender_id'],)).fetchone()
        owner=conn.execute('SELECT display_name FROM users WHERE id=?',(survivor,)).fetchone()
        events=[]
        for event in conn.execute('SELECT * FROM collaboration_events WHERE case_id=? ORDER BY version',(row['id'],)):
            own_event=event['actor_id']==survivor
            events.append({'version':event['version'],'action':event['action'],
                'note':event['note'] if own_event else '', 'created_at':event['created_at'],
                'actor':owner['display_name'] if own_event else '已注销账号','files':[]})
        events.append({'version':row['version']+1,'action':'account_deleted','note':'对方账号已注销，附件分享已关闭，仅保留本人的最小协作回执。',
                       'created_at':now,'actor':'系统','files':[]})
        data={'id':row['id'],'title':row['title'] if side=='sender' else '已注销账号的协作回执',
              'state':'retained','previous_state':row['state'],'version':row['version']+1,
              'created_at':row['created_at'],'updated_at':now,'task_version':row['task_version'],
              'sender':owner['display_name'] if side=='sender' else '已注销账号',
              'recipient':owner['display_name'] if side=='recipient' else '已注销账号',
              'side':side,'task_id':row['task_id'] if side=='sender' else None,
              'recipient_available':False,'actions':[],'events':events,'retained':True,
              'retention_note':'仅保存参与事项的必要动作、时间及自己填写的说明；对方身份、私人说明和文件授权已移除。'}
        conn.execute('INSERT OR REPLACE INTO collaboration_retained_receipts VALUES(?,?,?,?,?,?,?,?)',
                     (survivor,row['id'],side,row['college_id'],student['grade'] if student else '',
                      student['class_name'] if student else '',dumps(data),now))
        retained+=1
    return retained


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
    from .collaboration_followups import install as install_followups
    install_followups(app,db,user)
    @app.get('/api/collaboration')
    def inbox(side:Literal['sender','recipient']='recipient',page:int=Query(1,ge=1,le=10000),current=Depends(user)):
        uid=current['id']
        condition='c.sender_id=?' if side=='sender' else f'c.recipient_id=? AND {IN_SCOPE}'
        with db.connect() as conn:
            # Page the union in SQL so account-deletion receipts neither hide
            # live cases nor turn each inbox refresh into a full history read.
            rows=conn.execute(f"""SELECT c.id,c.updated_at,'active' AS kind
                FROM collaboration_cases c WHERE {condition}
                UNION ALL SELECT r.case_id AS id,r.updated_at,'retained' AS kind
                FROM collaboration_retained_receipts r WHERE r.user_id=? AND r.side=? AND {RETAINED_SCOPE}
                ORDER BY updated_at DESC,id DESC LIMIT 31 OFFSET ?""",(uid,uid,side,(page-1)*30)).fetchall()
            items=[]
            for row in rows[:30]:
                item=(project(owned_case(conn,uid,row['id']),uid) if row['kind']=='active' else
                      retained_receipts(conn,uid,cid=row['id'])[0])
                # Large receipt histories are read only when its detail opens.
                items.append({k:v for k,v in item.items() if k!='events'})
        return {'items':items,'has_more':len(rows)>30,'page':page}

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
            if not payload.note.strip():raise HTTPException(422,'请填写需要对方处理的事情')
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
            retained=retained_receipts(conn,current['id'],cid=cid)
            if retained:return retained[0]
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
            if payload.action in {'request_supplement','resubmit','resolve','decline'} and not payload.note.strip():
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

    @app.post('/api/collaboration/{cid}/transfer')
    def transfer(cid:str,payload:TransferCase,current=Depends(user)):
        """Sender confirms a new recipient and exact file versions afresh."""
        uid=current['id']
        transfer_digest=hashlib.sha256(dumps({'case_id':cid,'payload':payload.model_dump()}).encode()).hexdigest()
        with db.connect(write=True) as conn:
            old=owned_case(conn,uid,cid)
            if old['sender_id']!=uid:raise HTTPException(403,'只有发起人可以重新确认材料分享对象')
            previous=conn.execute('SELECT id,request_digest FROM collaboration_cases WHERE sender_id=? AND request_id=?',
                                  (uid,payload.request_id)).fetchone()
            if previous:
                if previous['request_digest']!=transfer_digest:raise HTTPException(409,'转交编号已用于其他内容')
                return {**case_view(conn,owned_case(conn,uid,previous['id']),uid),'previous_case_id':cid}
            if old['version']!=payload.version or old['state'] in {'resolved','withdrawn'}:
                raise HTTPException(409,'原协作已变化或关闭，请重新核对')
            if not payload.note.strip():raise HTTPException(422,'请填写交给新负责人的具体说明')
            if payload.recipient_id==old['recipient_id']:
                raise HTTPException(422,'请选择新的授权负责人；原协作可以继续办理')
            task=own_task(conn,uid,old['task_id'])
            if task['version']!=payload.task_version or task['status']=='cancelled':
                raise HTTPException(409,'本人事项版本或状态已变化，请重新核对')
            if not any(item['id']==payload.recipient_id for item in targets(conn,uid)):
                raise HTTPException(403,'新的接收人不在当前授权办理范围')
            if conn.execute("""SELECT 1 FROM collaboration_cases WHERE sender_id=? AND recipient_id=?
                    AND task_id=? AND state NOT IN ('resolved','withdrawn')""",(uid,payload.recipient_id,task['id'])).fetchone():
                raise HTTPException(409,'该负责人已有此事项的未办结协作，请先核对已有记录')
            new_id,now=ident(),int(time.time())
            college_id=conn.execute('SELECT college_id FROM campus_members WHERE user_id=?',(uid,)).fetchone()[0]
            conn.execute('INSERT INTO collaboration_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (new_id,uid,payload.recipient_id,college_id,task['id'],task['version'],
                 json.loads(task['data'])['title'],'sent',1,now,now,payload.request_id,transfer_digest))
            save_event(conn,new_id,1,uid,'send',payload,task['id'],now)
            # The prior case keeps its own evidence, but its recipient's file
            # access is withdrawn. No old attachments or private notes copy.
            conn.execute("UPDATE collaboration_cases SET state='withdrawn',version=version+1,updated_at=? WHERE id=?",(now,cid))
            conn.execute('INSERT INTO collaboration_events VALUES(?,?,?,?,?,?,?,?)',
                (cid,old['version']+1,uid,'transfer','发起人已重新确认另一位负责人；原材料分享关闭。',
                 now,payload.request_id,transfer_digest))
            result=case_view(conn,owned_case(conn,uid,new_id),uid)
            result['previous_case_id']=cid
            return result
