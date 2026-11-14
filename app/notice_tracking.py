"""Explicit source phases and follow-up links; personal execution stays in tasks.

An announcement, a publicity list, the user's identity check and the user's
submission receipt are separate facts. No text matcher chooses a result.
"""
from datetime import datetime,timedelta
import hashlib
import json
import time
from typing import Literal

from fastapi import Depends,HTTPException
from pydantic import Field,field_validator,model_validator

from .ai import normalized
from .db import audit,dumps
from .models import Evidence,Strict,TaskData
from .schedule import CreateArrangement,create_arrangement
from .notice_lifecycle import CST

TABLES={'notice_phase_tracking'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS notice_phase_tracking(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 version INTEGER NOT NULL DEFAULT 1, notice_version INTEGER NOT NULL,
 data TEXT NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS notice_phase_tracking_owner ON notice_phase_tracking(user_id);
INSERT OR IGNORE INTO meta VALUES('notice_tracking_schema_version','1');
"""
PHASE_LABELS={'unannounced':'等待正式公告','preview':'官方预告','announcement':'正式公告',
    'supplement':'补充说明','publicity':'公示中／核对公示','result':'结果与后续办理'}
ACTION_LABELS={'check_publication':'查看是否正式公告','objection':'提出异议／申诉','confirm_place':'确认名额',
    'collect':'领取','sign':'签约','report':'报到','waitlist':'候补／补录跟进','other':'后续行动'}


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='notice_tracking_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('通知阶段跟踪版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


class ObjectionWindow(Strict):
    start_date:str|None=None
    end_date:str|None=None
    end_time:str|None=None
    evidence:list[Evidence]=Field(default_factory=list,max_length=10)

    @field_validator('start_date','end_date')
    @classmethod
    def date_value(cls,value):return TaskData.valid_date(value)

    @field_validator('end_time')
    @classmethod
    def time_value(cls,value):return TaskData.valid_time(value)

    @model_validator(mode='after')
    def coherent(self):
        if self.end_time and not self.end_date:raise ValueError('异议结束时刻需要明确日期')
        if self.start_date and self.end_date and self.start_date>self.end_date:raise ValueError('异议结束日期不能早于开始日期')
        if (self.start_date or self.end_date) and not self.evidence:raise ValueError('异议窗口必须保留明确原文依据')
        return self


class ActionLink(Strict):
    kind:Literal['objection','confirm_place','collect','sign','report','waitlist','other']
    task_id:str=Field(min_length=1,max_length=100)


class TrackingData(Strict):
    phase:Literal['unannounced','preview','announcement','supplement','publicity','result']='unannounced'
    basis:Literal['personal_lead','past_pattern','official_preview','official_notice']='personal_lead'
    evidence:list[Evidence]=Field(default_factory=list,max_length=20)
    related_notice_versions:dict[str,int]=Field(default_factory=dict,max_length=20)
    outcome:Literal['unknown','shortlisted','selected','not_selected','waitlisted','supplementary']='unknown'
    identity_confirmed:bool=Field(default=False,strict=True)
    identity_note:str=Field(default='',max_length=1000)
    objection_intent:Literal['undecided','considering','preparing','declined']='undecided'
    objection_window:ObjectionWindow|None=None
    actions:list[ActionLink]=Field(default_factory=list,max_length=20)
    followup_arrangement_ids:list[str]=Field(default_factory=list,max_length=20)
    note:str=Field(default='',max_length=2000)

    @model_validator(mode='after')
    def separates_facts(self):
        if self.phase=='unannounced' and self.basis not in {'personal_lead','past_pattern','official_preview'}:
            raise ValueError('尚未公告的线索不能标记为正式通知')
        if self.phase=='preview' and self.basis!='official_preview':raise ValueError('官方预告须单独核对预告依据')
        if self.phase not in {'unannounced','preview'} and self.basis!='official_notice':raise ValueError('正式阶段需要明确正式通知依据')
        if self.basis in {'official_preview','official_notice'} and not self.evidence:raise ValueError('请选择当前通知或相关通知中的原文依据')
        if self.phase!='result' and self.outcome!='unknown':raise ValueError('预告、公示及公示结束均不能当作正式结果')
        if self.outcome!='unknown' and (not self.identity_confirmed or len(self.identity_note.strip())<2):
            raise ValueError('请本人核实身份及名单依据；不能凭同名或模糊匹配认定结果')
        if self.phase=='unannounced' and (self.objection_window or self.actions):raise ValueError('未公告线索仅可设置个人查进展安排，不能生成正式办理窗口或行动')
        if self.objection_window and self.phase not in {'publicity','result'}:raise ValueError('异议窗口须关联公示或结果阶段')
        if len({a.task_id for a in self.actions})!=len(self.actions):raise ValueError('同一后续行动不能重复关联')
        if len(set(self.followup_arrangement_ids))!=len(self.followup_arrangement_ids):raise ValueError('个人跟进安排不能重复关联')
        return self


class TrackingUpdate(Strict):
    version:int=Field(ge=0)
    notice_version:int=Field(ge=1)
    data:TrackingData


class FollowupCreate(Strict):
    version:int=Field(ge=0)
    notice_version:int=Field(ge=1)
    kind:Literal['check_publication','objection','confirm_place','collect','sign','report','waitlist','other']='check_publication'
    arrangement:CreateArrangement


def own(conn,uid,nid):
    row=conn.execute('SELECT * FROM notices WHERE id=? AND user_id=?',(nid,uid)).fetchone()
    if not row:raise HTTPException(404,'通知不存在或无权访问')
    return row


def validate_data(conn,uid,nid,notice,data):
    related={nid:notice['version'],**data.related_notice_versions}
    if nid in data.related_notice_versions and data.related_notice_versions[nid]!=notice['version']:
        raise HTTPException(409,'主通知版本已变化，请重新核对')
    for target,version in data.related_notice_versions.items():
        if type(version) is not int or version<1:raise HTTPException(422,'相关通知版本无效')
        if own(conn,uid,target)['version']!=version:raise HTTPException(409,'相关通知已更正，请重新核对阶段及名单依据')
    sources=[]
    for target in related:
        for row in conn.execute('SELECT id,kind,sections,status FROM sources WHERE notice_id=? AND active=1',(target,)):
            sources.append({**dict(row),'sections':json.loads(row['sections'])})
    try:
        text_index={(s['id'],part['locator']):normalized(part['text']) for s in sources for part in s['sections']}
        def check_evidence(items):
            for item in items:
                if not normalized(item.quote) or normalized(item.quote) not in text_index.get((item.source_id,item.locator),''):
                    raise ValueError('原文依据校验失败：引用位置或原句不匹配，请补充可核对的正文')
        check_evidence(data.evidence)
        if data.objection_window:
            check_evidence(data.objection_window.evidence)
            from .deadline_evidence import analyze
            support=analyze([e.quote for e in data.objection_window.evidence],notice['published_at'])
            window=data.objection_window
            if window.start_date and not support.supports_date(window.start_date,None):raise ValueError('异议开始日期缺少原文支持')
            if window.end_date and (not support.supports_date(window.end_date,window.end_time) or window.end_time and not support.supports_time(window.end_date,window.end_time)):
                raise ValueError('异议结束时间缺少原文支持')
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    for action in data.actions:
        task=conn.execute('SELECT notice_id FROM tasks WHERE id=? AND user_id=?',(action.task_id,uid)).fetchone()
        if not task or task['notice_id'] not in related:raise HTTPException(404,'后续行动不属于已关联的本人通知')
    for eid in data.followup_arrangement_ids:
        if not conn.execute('SELECT 1 FROM arrangements WHERE id=? AND user_id=?',(eid,uid)).fetchone():
            raise HTTPException(404,'个人跟进安排不存在或无权访问')


def read_tracking(conn,uid,nid):
    notice=own(conn,uid,nid)
    row=conn.execute('SELECT * FROM notice_phase_tracking WHERE notice_id=? AND user_id=?',(nid,uid)).fetchone()
    if not row:return {'notice_id':nid,'version':0,'notice_version':notice['version'],'data':TrackingData().model_dump(),
        'recorded':False,'phase_label':'尚未记录阶段','review_required':False,'actions':[],'followups':[]}
    data=json.loads(row['data']);warnings=[]
    if row['notice_version']==0:warnings.append('这是导入历史，请重新引用当前原文核实阶段、身份和后续动作')
    elif row['notice_version']!=notice['version']:warnings.append('主通知已更正，请复核阶段和后续动作')
    for target,version in data.get('related_notice_versions',{}).items():
        source=conn.execute('SELECT version FROM notices WHERE id=? AND user_id=?',(target,uid)).fetchone()
        if not source or source[0]!=version:warnings.append('相关通知已更正或移除，请复核原文依据')
    actions=[]
    for action in data.get('actions',[]):
        row_task=conn.execute('SELECT t.id,t.version,t.status,t.data,w.data AS workflow FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.id=? AND t.user_id=?',(action['task_id'],uid)).fetchone()
        if row_task:
            actions.append({**action,'label':ACTION_LABELS[action['kind']],'task_version':row_task['version'],
                'status':row_task['status'],'task':json.loads(row_task['data']),'workflow':json.loads(row_task['workflow'] or '{}')})
        else:actions.append({**action,'label':ACTION_LABELS[action['kind']],'status':'missing'})
    followups=[]
    for eid in data.get('followup_arrangement_ids',[]):
        item=conn.execute('SELECT * FROM arrangements WHERE id=? AND user_id=?',(eid,uid)).fetchone()
        if item:
            from .schedule import serialize
            followups.append(serialize(item))
        else:followups.append({'id':eid,'missing':True})
    window=data.get('objection_window');closed=False
    if window and window.get('end_date'):
        boundary=datetime.fromisoformat(window['end_date']+'T'+(window.get('end_time') or '00:00')).replace(tzinfo=CST)
        if not window.get('end_time'):boundary+=timedelta(days=1)
        closed=boundary.timestamp()<=time.time()
    return {**dict(row),'data':data,'recorded':True,'phase_label':PHASE_LABELS[data['phase']],
        'review_required':bool(warnings),'warnings':warnings,'actions':actions,'followups':followups,
        'objection_window_closed':closed,'publicity_is_final_result':False,
        'imported_history':imported_history(conn,uid,nid)}


def save_tracking(conn,uid,nid,payload):
    notice=own(conn,uid,nid)
    prior=conn.execute('SELECT * FROM notice_phase_tracking WHERE notice_id=? AND user_id=?',(nid,uid)).fetchone()
    if payload.notice_version!=notice['version'] or payload.version!=(prior['version'] if prior else 0):
        raise HTTPException(409,'通知或阶段跟踪已变化，请重新读取后保存')
    validate_data(conn,uid,nid,notice,payload.data)
    conn.execute('INSERT INTO notice_phase_tracking VALUES(?,?,1,?,?,?) ON CONFLICT(notice_id) DO UPDATE SET version=version+1,notice_version=excluded.notice_version,data=excluded.data,updated_at=excluded.updated_at',
        (nid,uid,notice['version'],payload.data.model_dump_json(),int(time.time())))
    audit(conn,uid,nid,'notice_phase_recorded',before=json.loads(prior['data']) if prior else None,after=payload.data.model_dump())
    return read_tracking(conn,uid,nid)


def summary(conn,uid,notice_ids=None):
    query='SELECT p.* FROM notice_phase_tracking p JOIN notices n ON n.id=p.notice_id WHERE p.user_id=? AND n.user_id=?'
    params=[uid,uid]
    if notice_ids is not None:
        if not notice_ids:return {}
        query+=' AND p.notice_id IN (SELECT value FROM json_each(?))';params.append(dumps(notice_ids))
    rows=[];needed=set()
    for row in conn.execute(query,params):
        data=json.loads(row['data']);rows.append((row,data));needed.add(row['notice_id'])
        needed.update(data.get('related_notice_versions',{}))
    if not rows:return {}
    versions={row['id']:row['version'] for row in conn.execute('SELECT id,version FROM notices WHERE user_id=? AND id IN (SELECT value FROM json_each(?))',(uid,dumps(list(needed))))}
    result={}
    for row,data in rows:
        review=row['notice_version']!=versions.get(row['notice_id']) or any(versions.get(nid)!=version for nid,version in data.get('related_notice_versions',{}).items())
        result[row['notice_id']]={'phase':data['phase'],'label':PHASE_LABELS[data['phase']],
            'outcome':data['outcome'],'version':row['version'],'review_required':review}
    return result


def imported_history(conn,uid,nid):
    row=conn.execute("SELECT after_json FROM audit WHERE notice_id=? AND user_id=? AND action='notice_phase_imported' ORDER BY id DESC LIMIT 1",(nid,uid)).fetchone()
    return json.loads(row[0]).get('history',[]) if row and row[0] else []


def export_tracking(conn,uid):
    return [{'notice_id':row['notice_id'],'notice_version':row['notice_version'],'data':json.loads(row['data']),
        'version':row['version'],'updated_at':row['updated_at'],'imported_history':imported_history(conn,uid,row['notice_id'])} for row in conn.execute(
        'SELECT p.* FROM notice_phase_tracking p JOIN notices n ON n.id=p.notice_id WHERE p.user_id=? AND n.user_id=? ORDER BY p.notice_id',(uid,uid))]


class TrackingArchive(Strict):
    notice_id:str=Field(min_length=1,max_length=100)
    notice_version:int=Field(ge=0,strict=True)
    data:TrackingData
    version:int=Field(ge=0,strict=True)
    updated_at:int=Field(ge=0,strict=True)


class TrackingExport(TrackingArchive):
    imported_history:list[TrackingArchive]=Field(default_factory=list,max_length=20)


def validate_import_tracking(items,limit):
    if not isinstance(items,list) or len(items)>limit:raise ValueError('公告阶段历史格式或数量不符合要求')
    parsed=[TrackingExport.model_validate(item).model_dump() for item in items]
    if len({item['notice_id'] for item in parsed})!=len(parsed):raise ValueError('公告阶段历史含重复通知标识')
    return parsed


def import_tracking(conn,uid,items):
    """Preserve portable history without reviving stale official claims.

    Source ids and personal calendar ids have no durable cross-export mapping.
    The original record stays readable as history; only an explicit new save
    against current evidence can re-establish a live phase or result.
    """
    for entry in items:
        key='notice-phase:'+hashlib.sha256(dumps(entry).encode()).hexdigest()
        if conn.execute('SELECT 1 FROM import_receipts WHERE user_id=? AND item_key=?',(uid,key)).fetchone():continue
        linked=conn.execute('SELECT l.notice_id FROM import_notice_links l JOIN notices n ON n.id=l.notice_id WHERE l.user_id=? AND l.source_id=? AND n.user_id=?',(uid,entry['notice_id'],uid)).fetchone()
        if not linked:raise HTTPException(422,'阶段历史引用的通知尚未导入，请一并导入该通知；本次导入未保存')
        nid=linked['notice_id']
        if conn.execute('SELECT 1 FROM notice_phase_tracking WHERE notice_id=?',(nid,)).fetchone():
            raise HTTPException(409,'该通知已有阶段跟踪；导入不会改写本地记录，请核对后移除文件中的对应阶段历史')
        history=list(entry.get('imported_history',[]))
        if entry['notice_version']>0 or not history:
            history.append({k:v for k,v in entry.items() if k!='imported_history'})
        if len(history)>20:raise HTTPException(422,'阶段历史超过20个归档版本，请使用完整数据库备份保存全部历史')
        current=TrackingData(note='已保留导入的公告阶段历史；请重新核实当前原文和本人结果。')
        now=int(time.time())
        conn.execute('INSERT INTO notice_phase_tracking VALUES(?,?,1,0,?,?)',(nid,uid,current.model_dump_json(),now))
        audit(conn,uid,nid,'notice_phase_imported',after={'history':history,'requires_review':True})
        conn.execute('INSERT INTO import_receipts VALUES(?,?,?)',(uid,key,now))


def install(app,db,user):
    @app.get('/api/notices/{nid}/lifecycle-tracking')
    def read(nid:str,current=Depends(user)):
        with db.connect() as conn:return read_tracking(conn,current['id'],nid)

    @app.put('/api/notices/{nid}/lifecycle-tracking')
    def save(nid:str,payload:TrackingUpdate,current=Depends(user)):
        with db.connect(write=True) as conn:return save_tracking(conn,current['id'],nid,payload)

    @app.post('/api/notices/{nid}/lifecycle-tracking/followup')
    def followup(nid:str,payload:FollowupCreate,current=Depends(user)):
        with db.connect(write=True) as conn:
            uid=current['id'];state=read_tracking(conn,uid,nid);data=TrackingData.model_validate(state['data'])
            if data.phase=='unannounced' and payload.kind!='check_publication':
                raise HTTPException(422,'未公告线索只能设置查看公告进展的个人安排')
            # Ordinary arrangement validation/idempotency/reminder consent are
            # reused; the personal date never becomes an official deadline.
            item=create_arrangement(conn,uid,payload.arrangement)
            if item['id'] in data.followup_arrangement_ids:
                # A retried identical request is already linked. A response
                # lost after commit must not create another follow-up/version.
                state['created_followup']=item
                return state
            if item['id'] not in data.followup_arrangement_ids:data.followup_arrangement_ids.append(item['id'])
            if len(data.followup_arrangement_ids)>20:raise HTTPException(422,'单则通知最多关联20项跟进安排')
            update=TrackingUpdate(version=payload.version,notice_version=payload.notice_version,data=data)
            result=save_tracking(conn,uid,nid,update)
            result['created_followup']=item
            return result
