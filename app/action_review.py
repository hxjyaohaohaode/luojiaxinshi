"""Review changed requirements without rewriting the user's historical progress."""
from datetime import date, datetime, timedelta, timezone
import json
import time
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from .db import audit,dumps
from .models import Strict

FORMAL_FIELDS={'details','scope','due_date','due_time','deadline_text','materials','submission','location'}
DATE_FIELDS={'due_date','due_time','deadline_text'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS task_reviews(
 task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
 version INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','reviewed')),
 data TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',updated_at INTEGER NOT NULL,reviewed_at INTEGER);
INSERT OR IGNORE INTO meta VALUES('action_review_schema_version','1');
"""


class Cause(Strict):
    source_id: str = Field(min_length=1,max_length=100)
    title: str = Field(min_length=1,max_length=160)
    source_version: int = Field(ge=1)
    kind: Literal['requirements','schedule','restored','upstream','imported','deleted','progress']
    fields: list[str] = Field(default_factory=list,max_length=16)
    change_id: str = Field(default='',max_length=40)

    @field_validator('fields')
    @classmethod
    def valid_fields(cls, values):
        if any(value not in FORMAL_FIELDS|{'status','progress','dependencies','conditions'} for value in values):
            raise ValueError('办理影响含未知字段')
        return sorted(set(values))


class ReviewDecision(Strict):
    version: int = Field(ge=1)
    task_version: int = Field(ge=1)
    decision: Literal['keep','reopen']
    note: str = Field(min_length=2,max_length=1500)


def public_review(row):
    return {**dict(row),'data':json.loads(row['data'])} if row else None


def pending(conn,tid):
    return bool(conn.execute("SELECT 1 FROM task_reviews WHERE task_id=? AND state='pending'",(tid,)).fetchone())


def require_reviewed(conn,tid):
    if pending(conn,tid):
        raise HTTPException(422,'办理依据已变化，请先在“办理与跟进”核对变更影响，再提交、完成或导出新的提醒')


def schedule_issues(data):
    """A date-only deadline is compared by date, without inventing 23:59."""
    result=[]
    reminder=data.get('reminder_at')
    if reminder and not data.get('due_date') and not data.get('planned_at'):
        result.append({'code':'reminder_without_anchor','message':'正式日期已待定，旧提醒缺少明确的事件时间。请清除旧提醒，或设置本人核实信息的计划与提醒。','blocking':True})
    if data.get('due_date'):
        day=date.fromisoformat(data['due_date']);zone=timezone(timedelta(hours=8))
        deadline=datetime.fromisoformat(data['due_date']+'T'+data['due_time']).replace(tzinfo=zone) if data.get('due_time') else None
        for key,label in [('planned_at','个人计划'),('reminder_at','提醒时间')]:
            if not data.get(key):continue
            value=datetime.fromisoformat(data[key]).astimezone(zone)
            late=value>deadline if deadline else value.date()>day
            if late:result.append({'code':key+'_after_deadline','message':label+'晚于当前正式期限，请重排；事后查询应使用单独的跟进时间。','blocking':key=='reminder_at'})
    return result


def descendants(conn,uid,root):
    children={};items={}
    for row in conn.execute('SELECT t.id,t.status,t.data,w.data AS workflow FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=?',(uid,)):
        items[row['id']]={'id':row['id'],'title':json.loads(row['data'])['title'],'status':row['status']}
        for parent in json.loads(row['workflow'])['dependencies'] if row['workflow'] else []:
            children.setdefault(parent,[]).append(row['id'])
    seen={root};queue=list(children.get(root,[]));result=[]
    while queue:
        tid=queue.pop()
        if tid in seen:continue
        seen.add(tid);result.append(items[tid]);queue.extend(children.get(tid,[]))
    return result


def queue_review(conn,tid,uid,cause):
    cause=Cause.model_validate(cause).model_dump()
    row=conn.execute('SELECT * FROM task_reviews WHERE task_id=?',(tid,)).fetchone()
    old=public_review(row)
    causes=json.loads(row['data'])['causes'] if row and row['state']=='pending' else []
    earlier=next((c for c in causes if c['source_id']==cause['source_id']),None)
    if earlier:cause['fields']=sorted(set(earlier['fields'])|set(cause['fields']))
    causes=[c for c in causes if c['source_id']!=cause['source_id']]+[cause]
    version=(row['version'] if row else 0)+1;now=int(time.time())
    conn.execute("""INSERT INTO task_reviews VALUES(?,?,'pending',?,'',?,NULL)
        ON CONFLICT(task_id) DO UPDATE SET version=excluded.version,state='pending',data=excluded.data,
        note='',updated_at=excluded.updated_at,reviewed_at=NULL""",(tid,version,dumps({'causes':causes}),now))
    notice=conn.execute('SELECT notice_id FROM tasks WHERE id=? AND user_id=?',(tid,uid)).fetchone()
    if not notice:raise ValueError('review task owner mismatch')
    audit(conn,uid,notice['notice_id'],'change_review_required',before=old,after={'version':version,'cause':cause},task_id=tid)


def record_change(conn,uid,tid,before,after,old_status,new_status,change_id=''):
    """Call inside the transaction that has just updated the authoritative task."""
    fields=sorted(k for k in FORMAL_FIELDS if before.get(k)!=after.get(k))
    status_changed=old_status!=new_status and new_status in {'pending','cancelled'}
    if not fields and not status_changed:return
    task=conn.execute('SELECT version FROM tasks WHERE id=? AND user_id=?',(tid,uid)).fetchone()
    row=conn.execute('SELECT data FROM task_workflows WHERE task_id=?',(tid,)).fetchone()
    stage=json.loads(row['data'])['stage'] if row else 'preparing'
    prior_progress=old_status=='done' or stage in {'submitted','accepted','rejected'}
    schedule_changed=bool(DATE_FIELDS.intersection(fields) and (after.get('planned_at') or after.get('reminder_at')))
    needs_own=(fields and (prior_progress or schedule_changed)) or old_status=='cancelled' and new_status=='pending'
    cause={'source_id':tid,'title':after['title'],'source_version':task['version'],
           'kind':'restored' if old_status=='cancelled' else 'schedule' if schedule_changed and not prior_progress else 'requirements',
           'fields':fields+(['status'] if status_changed else []),'change_id':change_id}
    if needs_own:queue_review(conn,tid,uid,cause)
    for child in descendants(conn,uid,tid):
        queue_review(conn,child['id'],uid,{**cause,'kind':'upstream'})


def record_deletion(conn,uid,nid):
    """Invalidate downstream historical completion before removing the source graph."""
    roots=list(conn.execute('SELECT id,version FROM tasks WHERE notice_id=? AND user_id=?',(nid,uid)))
    deleted={r['id'] for r in roots}
    for root in roots:
        for child in descendants(conn,uid,root['id']):
            if child['id'] in deleted:continue
            queue_review(conn,child['id'],uid,{'source_id':root['id'],'source_version':root['version'],
                         'title':'已删除的前置事项','kind':'deleted','fields':['status']})


def record_workflow_change(conn,uid,task,before,after):
    """New adverse outcomes or changed prerequisites can invalidate past progress."""
    if task['status']!='done' and before['stage'] not in {'submitted','accepted','rejected'}:return
    fields=[]
    if set(before['dependencies'])!=set(after['dependencies']):fields.append('dependencies')
    from .action_plans import constraint_key
    if constraint_key(before)!=constraint_key(after):fields.append('conditions')
    if after['stage'] in {'supplement','blocked','rejected'} and (before['stage']!=after['stage'] or before['outcome']!=after['outcome']):fields.append('progress')
    if not fields:return
    cause={'source_id':task['id'],'title':task['data']['title'],'source_version':task['version'],
           'kind':'progress','fields':fields}
    queue_review(conn,task['id'],uid,cause)
    for child in descendants(conn,uid,task['id']):
        queue_review(conn,child['id'],uid,{**cause,'kind':'upstream'})


def install(app,db,user,own_task,expect_version,get_task):
    from fastapi import Depends

    @app.post('/api/tasks/{tid}/change-review')
    def decide(tid:str,payload:ReviewDecision,current=Depends(user)):
        with db.connect(write=True) as conn:
            task=own_task(conn,tid,current['id'])
            row=conn.execute('SELECT * FROM task_reviews WHERE task_id=?',(tid,)).fetchone()
            if not row:raise HTTPException(404,'没有需要核对的办理变更')
            data=json.loads(row['data'])
            if row['state']=='reviewed' and row['version']==payload.version+1 and row['note']==payload.note and data.get('decision')==payload.decision:
                return get_task(conn,tid,current['id'])
            expect_version(task,payload.task_version);expect_version(row,payload.version)
            if row['state']!='pending':raise HTTPException(409,'这次影响已核对，请刷新查看最新状态')
            workflow=conn.execute('SELECT * FROM task_workflows WHERE task_id=?',(tid,)).fetchone()
            value=json.loads(task['data']);flow=json.loads(workflow['data']) if workflow else None
            if payload.decision=='keep' and (task['status']=='done' or flow and flow['stage'] in {'submitted','accepted'}):
                from .action_plans import require_gates
                require_gates(flow or {})
            for dep in flow['dependencies'] if flow else []:
                if pending(conn,dep):raise HTTPException(422,'请先核对前置步骤的变更，再确认本步骤是否仍适用')
            if task['status']!='cancelled' and any(i['blocking'] for i in schedule_issues(value)):
                raise HTTPException(422,'原提醒已不适用，请先编辑个人计划或清除／重排提醒，再完成复核')
            if payload.decision=='reopen' and task['status']=='cancelled':
                raise HTTPException(422,'事项已正式取消；需要正式恢复后才能重新办理')
            now=int(time.time());before=public_review(row)
            conn.execute("UPDATE task_reviews SET version=version+1,state='reviewed',data=?,note=?,updated_at=?,reviewed_at=? WHERE task_id=?",
                         (dumps({**data,'decision':payload.decision}),payload.note,now,now,tid))
            if payload.decision=='reopen':
                from .workflow import WorkflowData
                before_flow=flow or WorkflowData().model_dump()
                revised={**before_flow,'stage':'supplement' if before_flow['receipt'] or before_flow['receipt_url'] else 'preparing',
                         'outcome':'本人核对变更后重新办理：'+payload.note}
                conn.execute('INSERT INTO task_workflows VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at',
                             (tid,dumps(revised),(workflow['version'] if workflow else 0)+1,now))
                audit(conn,current['id'],task['notice_id'],'workflow_update',before=before_flow,after=revised,task_id=tid)
                if task['status']!='pending':
                    conn.execute("UPDATE tasks SET status='pending',version=version+1,updated_at=? WHERE id=?",(now,tid))
                    record_change(conn,current['id'],tid,value,value,task['status'],'pending')
            audit(conn,current['id'],task['notice_id'],'change_reviewed',before=before,
                  after={'decision':payload.decision,'note':payload.note,'task_status_before':task['status'],
                         'task_status_after':'pending' if payload.decision=='reopen' else task['status']},task_id=tid)
            return get_task(conn,tid,current['id'])
