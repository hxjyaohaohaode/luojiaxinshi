"""Deterministic checks for human review decisions, not semantic certification."""
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from .models import TaskData,Strict,IssueResolution,DraftIndex,ReviewObservation

VERSION=1
CONTENT_FIELDS=('title','details','scope','due_date','due_time','deadline_text','materials','submission','location','contact','uncertainties')


class ReceiptEvidence(Strict):
    source_id:str=Field(default='',max_length=40)
    locator:str=Field(min_length=1,max_length=80)
    quote:str=Field(min_length=1,max_length=1600)


class ReceiptFinding(Strict):
    task_index:DraftIndex|None
    code:Literal['procedure','actor','obligation','condition','dependency','omission','deadline','applicability']
    message:str=Field(min_length=8,max_length=500)
    evidence:list[ReceiptEvidence]=Field(max_length=8)


class ReceiptIssue(IssueResolution):
    task_titles:list[str]=Field(default_factory=list,max_length=30)
    finding:ReceiptFinding


class PortableReceipt(Strict):
    version:Literal[1]
    review_status:Literal['needs_review','unavailable','passed','not_run']
    created_at:int=Field(strict=True,ge=0,le=4102444800)
    manual_reviewed:bool=Field(default=False,strict=True)
    note:str=Field(default='',max_length=2000)
    issues:list[ReceiptIssue]=Field(default_factory=list,max_length=24)
    observation:ReviewObservation|None=None


def portable_receipt(value):
    if value is None:return None
    if not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=VERSION:raise ValueError('核对记录格式或版本无效')
    parsed=PortableReceipt.model_validate({k:value[k] for k in PortableReceipt.model_fields if k in value}).model_dump()
    indices=[item['issue_index'] for item in parsed['issues']]
    if len(indices)!=len(set(indices)) or any(len(title)>160 for item in parsed['issues'] for title in item['task_titles']):
        raise ValueError('核对记录的序号或标题无效')
    return parsed


def import_receipt(conn,user_id,notice_id,value,sources):
    if value is None:return
    from .db import audit
    for item in value['issues']:
        for evidence in item['finding']['evidence']:
            evidence['source_id']=sources.get(evidence['source_id'],'')
    audit(conn,user_id,notice_id,'import_quality_review',after=value)


def fail(message):
    raise HTTPException(422,message)


def content(task):
    normalized=TaskData.model_validate(task).model_dump()
    return {key:normalized[key] for key in CONTENT_FIELDS}


def require_confirmation(draft,payload):
    quality=draft.get('quality') or {};status=quality.get('status','not_run')
    result={'version':VERSION,'review_status':status,'issues':[]}
    if payload.review_observation is not None:
        result['observation']=payload.review_observation.model_dump()
    if status=='unavailable':
        if not payload.manual_quality_reviewed or len(payload.quality_resolution.strip())<8:
            fail('独立复核未完成；请明确勾选已逐份人工核对，并填写至少 8 个字的核实与修改说明。')
        result.update(manual_reviewed=True,note=payload.quality_resolution)
        return result
    if status!='needs_review':
        if payload.issue_resolutions:fail('当前草稿没有需要逐条处理的复核意见，请重新打开当前版本。')
        return result

    original=draft['tasks'];issues=quality.get('issues',[]);sources=payload.source_indices
    if not issues:fail('复核意见记录不完整，请重新核对材料后整理。')
    if len(sources)!=len(payload.tasks) or any(i is not None and i>=len(original) for i in sources):
        fail('所选步骤与原草稿的对应关系不完整，请重新打开草稿。')
    nonempty=[i for i in sources if i is not None]
    if len(set(nonempty))!=len(nonempty):fail('一个原草稿步骤不能重复对应多个所选步骤。')
    decisions={item.issue_index:item for item in payload.issue_resolutions}
    if len(decisions)!=len(payload.issue_resolutions) or set(decisions)!=set(range(len(issues))):
        fail('请逐条处理本次全部复核意见，不能用一段总说明替代。')

    originals=[content(task) for task in original]
    selected=[content(task.model_dump()) for task in payload.tasks]
    def changed(index):
        source=sources[index]
        if source is None:
            # Relabelling an unchanged original as a new step is not a correction.
            return selected[index] not in originals
        if selected[index]!=originals[source]:return True
        current=payload.plans.get(index)
        if current is None:return False  # Existing workflow intentionally retained.
        prior=draft.get('plans',{}).get(str(source),draft.get('plans',{}).get(source,{}))
        previous={'action_kind':prior.get('action_kind','unclassified'),'conditions':prior.get('conditions',[]),
                  'depends_on':prior.get('depends_on',[])}
        mapped=[sources[i] if sources[i] is not None else ('new',i) for i in current.depends_on if i<len(sources)]
        return (current.action_kind!=previous['action_kind'] or current.conditions!=previous['conditions']
                or set(map(str,mapped))!=set(map(str,previous['depends_on'])))

    for index,issue in enumerate(issues):
        decision=decisions[index];related=issue.get('task_index');targets=decision.task_indices
        if len(set(targets))!=len(targets) or any(i>=len(selected) for i in targets):fail(f'意见 {index+1} 关联了不存在或重复的所选步骤。')
        if decision.action=='excluded':
            if related is None or related in sources or originals[related] in selected or targets:
                fail(f'意见 {index+1} 的相关步骤仍在保存范围中，不能标记为不保存。')
        elif decision.action=='changed':
            if not targets or not any(changed(i) for i in targets):fail(f'意见 {index+1} 标为已修改，但关联内容尚无实际改动。')
            if related is not None and (related not in sources or sources.index(related) not in targets):
                fail(f'意见 {index+1} 请关联其实际修改步骤；若不保存，请取消选中该步骤。')
        else:
            if len(decision.note.strip())<8:fail(f'意见 {index+1} 请填写至少 8 个字的本人核实依据。')
            if targets:fail(f'意见 {index+1} 的处理方式不应携带修改步骤。')
            if decision.action=='acknowledged' and not (related is None and issue.get('code') in {'condition','obligation','applicability'}):
                fail(f'意见 {index+1} 涉及具体步骤或遗漏，不能只标为一般注意事项。')
        result['issues'].append({**decision.model_dump(),'task_titles':[payload.tasks[i].title for i in targets]})
    return result


def receipt(conn,notice_id):
    row=conn.execute("SELECT before_json,after_json,created_at,action FROM audit WHERE notice_id=? AND action IN ('confirm_draft','import_quality_review') ORDER BY id DESC LIMIT 1",(notice_id,)).fetchone()
    if not row:return None
    if row['action']=='import_quality_review':return {**json.loads(row['after_json']),'imported':True}
    after=json.loads(row['after_json'] or '{}');saved=after.get('quality_result')
    if not isinstance(saved,dict) or saved.get('version')!=VERSION:return None
    original=json.loads(row['before_json'] or '{}').get('quality') or {}
    return {**saved,'created_at':row['created_at'],'original_quality':original,
            'issues':[{**item,'finding':original.get('issues',[])[item['issue_index']]} for item in saved.get('issues',[]) if item['issue_index']<len(original.get('issues',[]))]}
