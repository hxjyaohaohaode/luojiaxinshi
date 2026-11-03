"""Automatic information age, separate from the user's task completion.

Only current, independently checked, explicitly evidenced dates can retire an
opportunity. Publication age, an inferred year and a preparation plan cannot.
This projection is recomputed at reads and before delivery, including after a
restart; no per-notice opt-in or timer is required.
"""
from datetime import datetime,timedelta,timezone
import time
import re
from .deadline_evidence import analyze,ANCHOR

CST=timezone(timedelta(hours=8))
RETIRED_STATES={'elapsed','event_date_passed','entry_closed'}

def focus_projection(notice,draft,*,current=False,now=None):
    """A shared list/detail key time, never guessed from publication or age."""
    quality=draft.get('quality')
    if not current or not isinstance(quality,dict) or quality.get('status')!='passed':return {'key_time':None,'summary':''}
    now=int(time.time()) if now is None else now
    candidates=[]
    for task in draft.get('tasks') or []:
        if not isinstance(task,dict) or task.get('scope')!='personal':continue
        try:
            boundary=closing(task,notice.get('published_at'))
            if boundary and boundary['kind']=='deadline':
                candidates.append({'label':'原文截止','date':task['due_date'],'time':task.get('due_time') or '',
                    'at':boundary['at'],'date_only':boundary['date_only'],'title':task.get('title','')})
            slot=task.get('scheduled')
            if isinstance(slot,dict) and slot.get('start_date'):
                quotes=[e.get('quote','') for e in slot.get('evidence') or [] if isinstance(e,dict)]
                day,clock=slot['start_date'],slot.get('start_time')
                support=analyze(quotes,notice.get('published_at'))
                if support.supports_date(day,clock) and (not clock or support.supports_time(day,clock)):
                    at=datetime.fromisoformat(day+'T'+(clock or '00:00')).replace(tzinfo=CST).timestamp()
                    candidates.append({'label':'办理开始' if slot.get('kind')=='window' else '活动时间','date':day,'time':clock or '',
                        'at':int(at),'date_only':not bool(clock),'title':task.get('title','')})
        except (ValueError,TypeError,OverflowError):continue
    candidates.sort(key=lambda item:(item['at']<now,item['at'] if item['at']>=now else -item['at']))
    return {'key_time':candidates[0] if candidates else None,'summary':draft.get('summary','')}


def elapsed_entry_windows(notice,draft,now):
    """An optional entry window can close while consultation/results stay readable.

    This only retires recommendation as a NEW participation opportunity. It
    asserts neither the event's end nor the completion of chosen personal work.
    Every identified entry must have a checked, explicit original deadline;
    an unknown/alternative open entry or mandatory personal action blocks it.
    """
    plans=draft.get('plans') or {}
    if not isinstance(plans,dict):return []
    entries=[]
    for index,task in enumerate(draft.get('tasks') or []):
        if not isinstance(task,dict) or task.get('scope')!='personal':continue
        plan=plans.get(str(index),plans.get(index,{}))
        if not isinstance(plan,dict) or plan.get('action_kind')!='optional':return []
        if plan.get('execution_mode')!='submission' or not re.search(r'报名|注册|申报|申请|参赛登记',task.get('title','')):continue
        quotes='\n'.join(e.get('quote','') for e in [*(task.get('evidence') or []),*(task.get('deadline_evidence') or [])] if isinstance(e,dict))
        if not re.search(r'报名|注册|申报|申请|参赛登记',quotes):return []
        try:boundary=closing(task,notice.get('published_at'))
        except (ValueError,TypeError,OverflowError):boundary=None
        if not boundary or boundary['kind']!='deadline' or boundary['at']>now:return []
        entries.append({'index':index,'title':task.get('title','报名或申报'),**boundary})
    return entries


def past_event_facts(notice,draft,now):
    """A dated event preview is no longer a future opportunity.

    This does NOT assert that the event ended. Publication age and application,
    funding or publicity windows cannot establish an event occurrence date.
    """
    if not re.search(r'讲坛|讲座|讲堂|报告会|学术报告|研讨会|学术年会|会议|论坛|培训班|活动预告|演出',notice.get('title','')):return []
    tasks=[t for t in draft.get('tasks',[]) or [] if isinstance(t,dict) and t.get('scope')=='personal']
    if any(t.get('due_date') or not isinstance(t.get('scheduled'),dict) or t['scheduled'].get('kind','event')!='event' for t in tasks):return []
    fact=(draft.get('facts') or {}).get('dates') or {}
    if not isinstance(fact,dict):return []
    evidence=fact.get('evidence') or []
    quotes=[e.get('quote','') for e in evidence if isinstance(e,dict)]
    text=re.sub(r'\s+','','\n'.join(quotes))
    if not re.search(r'(?:^|[。；;])(?:讲座|报告|活动|会议|培训)?时间[：:]',text):return []
    if re.search(r'发布时间|公示时间|报名时间|办理时间|申报时间|截止|长期|常年|滚动|持续|每周|每月|至今|为期',text):return []
    anchors=[anchor for quote in quotes for anchor in ANCHOR.finditer(quote)]
    if not anchors or any(not anchor['full'] for anchor in anchors):return []
    days=analyze(quotes).days
    today=datetime.fromtimestamp(now,CST).date().isoformat()
    if not days or max(days)>=today:return []
    if any(t['scheduled'].get('start_date') not in days or (t['scheduled'].get('end_date') or '')>=today for t in tasks):return []
    return [{'title':'原文活动日期','dates':sorted(days),'evidence':evidence}]


def closing(task,published_at=None):
    evidence=task.get('deadline_evidence') or []
    quotes=[e.get('quote','') for e in evidence if isinstance(e,dict)]
    day,clock=task.get('due_date'),task.get('due_time')
    if day:
        support=analyze(quotes,published_at)
        if not support.supports_date(day,clock) or clock and not support.supports_time(day,clock):return None
        moment=datetime.fromisoformat(day+'T'+(clock or '00:00')).replace(tzinfo=CST)
        # A date-only deadline remains open for the entire stated date.
        if not clock:moment+=timedelta(days=1)
        return {'at':int(moment.timestamp()),'date_only':not bool(clock),'kind':'deadline','evidence':evidence}
    slot=task.get('scheduled')
    if not isinstance(slot,dict) or not slot.get('start_date'):return None
    # A start is not an end. Do not invent a one-day duration for a multi-day
    # event whose closing boundary was never published.
    if not slot.get('end_date'):return None
    evidence=slot.get('evidence') or []
    quotes=[e.get('quote','') for e in evidence if isinstance(e,dict)]
    day=slot['end_date'];clock=slot.get('end_time')
    support=analyze(quotes,published_at)
    if not support.supports_date(day,clock) or clock and not support.supports_time(day,clock):return None
    moment=datetime.fromisoformat(day+'T'+(clock or '00:00')).replace(tzinfo=CST)
    if not clock:moment+=timedelta(days=1)
    return {'at':int(moment.timestamp()),'date_only':not bool(clock),'kind':'event_end','evidence':evidence}


def lifecycle(notice,draft,*,current=False,now=None):
    now=int(time.time()) if now is None else now
    base={'automatic':True,'state':'unknown','label':'持续跟踪','evaluated_at':int(now),
          'expired_actions':[],'open_actions':[],'unknown_actions':[],'past_events':[],'entry_deadlines':[],
          'reason':'尚无当前版本、通过核对的明确期限；不按收录月份判断已经结束'}
    quality=draft.get('quality')
    if not current or not isinstance(quality,dict) or quality.get('status')!='passed':return base
    tasks=draft.get('tasks') or []
    for index,task in enumerate(tasks):
        if not isinstance(task,dict) or task.get('scope')!='personal':continue
        try:boundary=closing(task,notice.get('published_at'))
        except (ValueError,TypeError,OverflowError):boundary=None
        item={'index':index,'title':task.get('title','本人行动')}
        if boundary is None:base['unknown_actions'].append(item)
        else:base['expired_actions' if boundary['at']<=now else 'open_actions'].append({**item,**boundary})
    if base['expired_actions'] and not base['open_actions'] and not base['unknown_actions']:
        base.update(state='elapsed',label='已过原文期限',reason='所有本人行动的有据期限均已过去；不再推荐为新机会，系统仍检查原文修订，未把个人待办改成已完成')
    elif base['open_actions']:
        base.update(state='mixed' if base['expired_actions'] else 'active',label='仍有可办理内容',
                    reason='仅推荐尚在有据期限内的行动；已过期步骤保留原文与历史')
    elif base['unknown_actions']:
        base['reason']='存在未明确期限的本人行动；不能确认整体已经结束，继续跟踪原文'
    if not base['open_actions']:
        base['past_events']=past_event_facts(notice,draft,now)
        if base['past_events']:
            base.update(state='event_date_passed',label='已过原文活动日期',
                reason='原文明确列出的活动日期已过，不再作为未来新机会推荐；结束时间未明确，不据此宣称活动已结束，仍保留跟踪与恢复入口')
    if base['state']!='elapsed':
        base['entry_deadlines']=elapsed_entry_windows(notice,draft,now)
        if base['entry_deadlines']:
            base.update(state='entry_closed',label='报名或申报期限已过',
                reason='所有已识别的可选报名或申报入口均已过原文期限，不再作为新参与机会推荐；咨询、结果查询和已有办理记录保留，不据此宣称整件事已结束，可手动恢复')
    return base
