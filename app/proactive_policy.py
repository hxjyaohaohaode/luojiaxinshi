"""Local, explainable notification policy. Never infers facts or calls a model.

Applicability comes from a versioned, profile-checked extraction. Keywords only
influence interest/delivery, and can never establish eligibility or urgency.
"""
from datetime import datetime,timedelta,timezone
import json
from .models import NotificationPreferences
from .notice_lifecycle import RETIRED_STATES

VERSION='proactive-policy-v1'
CST=timezone(timedelta(hours=8))
PRIORITIES={'P0':'已有事项需要核对','P1':'优先办理','P2':'关注机会','P3':'知悉资料','R':'待核实'}

def preferences(profile):
    profile=json.loads(profile) if isinstance(profile,str) else profile or {}
    try:return NotificationPreferences.model_validate(profile.get('notification_preferences') or {})
    except (ValueError,TypeError):
        # Corrupt/unsupported saved preferences cannot silently enable a burst.
        return NotificationPreferences(mode='digest')

def assess(notice,*,current_draft=False,pref=None,now=None):
    pref=pref or NotificationPreferences()
    draft=notice.get('draft') or {}
    if isinstance(draft,str):
        try:draft=json.loads(draft)
        except (ValueError,TypeError):draft={}
    if not isinstance(draft,dict):draft={}
    relevance=draft.get('applicability','needs_review') if current_draft else 'needs_review'
    if relevance not in {'matches_known','needs_review','not_matching'}:relevance='needs_review'
    quality=draft.get('quality') or {}
    quality_status=quality.get('status','unverified') if current_draft and isinstance(quality,dict) else 'unverified'
    rejected_match=relevance=='not_matching' and quality_status!='passed'
    if rejected_match:relevance='needs_review'
    raw_tasks=draft.get('tasks') if isinstance(draft.get('tasks'),list) else []
    tasks=[task for task in raw_tasks if isinstance(task,dict) and task.get('scope')=='personal'] if current_draft else []
    plans=draft.get('plans') or {}
    optional=bool(tasks) and all(isinstance(plans.get(str(i),plans.get(i)),dict) and plans.get(str(i),plans.get(i)).get('action_kind')=='optional'
        for i,t in enumerate(raw_tasks) if isinstance(t,dict) and t.get('scope')=='personal') if isinstance(plans,dict) else False
    text=(str(notice.get('title',''))+' '+str(draft.get('summary',''))).casefold()
    interested=any(term.casefold() in text for term in pref.interest_terms)
    muted=any(term.casefold() in text for term in pref.muted_terms)
    priority='R';reasons=[]
    if rejected_match:reasons.append('不匹配结论尚未通过核对，保留为待核实，避免漏掉本人相关信息')
    if relevance=='not_matching':
        reasons.append('当前通知及个人条件的适用判断为不匹配；保留资料，停止新收件提醒')
    elif not current_draft:
        reasons.append('尚无同时匹配当前通知版本与个人条件的整理结果')
    elif quality_status!='passed':
        reasons.append('内容尚未通过独立核对，不按已确认的本人事项提醒')
    elif relevance!='matches_known':
        reasons.append('原文或个人条件不足，需要核实是否适用')
    elif tasks:
        priority='P2' if optional else 'P1'
        reasons.append('符合当前已知个人条件，且有本人行动'+('；已识别为可选事项' if optional else ''))
    else:
        priority='P3';reasons.append('符合已知个人条件，以知悉为主，未生成本人行动')
    if interested:reasons.append('命中你主动设置的关注关键词；不据此推断资格')
    # Muting cannot hide an already identified personal action; task deadlines
    # and corrections use their existing, separate reminder pipeline as well.
    suppressed=relevance=='not_matching' or (muted and priority!='P1')
    if muted and priority!='P1':reasons.append('命中你设置的静默关键词，仍可在收件箱查看')
    if pref.mode=='digest':delivery='daily_digest'
    elif pref.mode=='all':delivery='near_term'
    elif priority=='P3':delivery='daily_digest'
    elif priority=='P2' and not interested:delivery='opportunity_digest'
    else:delivery='near_term'
    from .notice_lifecycle import lifecycle,focus_projection
    tracking=lifecycle(notice,draft,current=current_draft,now=now)
    closing_at=min((item['at'] for item in tracking['open_actions']),default=None)
    urgent=closing_at is not None and 0<closing_at-tracking['evaluated_at']<=86400
    if urgent:
        delivery='near_term'
        reasons.append('有原文依据的本人行动期限在24小时内，优先提示，避免等待普通机会汇总而错过')
    if tracking['state'] in RETIRED_STATES:
        suppressed=True;reasons.append(tracking['reason'])
    return {'version':VERSION,'priority':priority,'label':'历史信息' if tracking['state'] in RETIRED_STATES else PRIORITIES[priority],
            'focus':focus_projection(notice,draft,current=current_draft,now=tracking['evaluated_at']),
            'relevance':relevance,'quality':quality_status,'personal_actions':len(tasks),
            'interest_match':interested,'delivery':'silent' if suppressed else delivery,
            'reasons':reasons,'requires_review':priority=='R','tracking':tracking,
            'urgency':{'state':'elapsed' if tracking['state'] in RETIRED_STATES else 'due_soon' if urgent else 'normal',
                'closing_at':closing_at},
            'recommended':not suppressed}

def next_digest(stamp,hour):
    """Fixed Beijing calendar window, independent of polling/restart time."""
    moment=datetime.fromtimestamp(stamp,CST)
    target=moment.replace(hour=hour,minute=0,second=0,microsecond=0)
    if target.timestamp()<=stamp:target+=timedelta(days=1)
    return int(target.timestamp())

def outside_quiet_hours(stamp,pref):
    if not pref.quiet_start:return int(stamp)
    moment=datetime.fromtimestamp(stamp,CST)
    start,end=pref.quiet_start,pref.quiet_end
    clock=moment.strftime('%H:%M')
    within=(start<=clock<end) if start<end else (clock>=start or clock<end)
    if not within:return int(stamp)
    hour,minute=map(int,end.split(':'))
    target=moment.replace(hour=hour,minute=minute,second=0,microsecond=0)
    if target.timestamp()<=stamp:target+=timedelta(days=1)
    return int(target.timestamp())

def delivery_slot(created_at,decision,pref):
    """Stable event keys keep accepted sends from being replayed after restarts."""
    kind=decision['delivery']
    if kind=='silent':return None
    if kind=='daily_digest':
        due=next_digest(created_at,pref.digest_hour);key='daily:'+str(due)
    elif kind=='opportunity_digest':
        # Six-hour digest slots in Beijing time; not every poll/user request.
        local=datetime.fromtimestamp(created_at,CST)
        target=local.replace(hour=(local.hour//6)*6,minute=0,second=0,microsecond=0)+timedelta(hours=6)
        due=int(target.timestamp());key='opportunity:'+str(due)
    else:
        bucket=int(created_at)//120;due=(bucket+1)*120;key=str(bucket)
        closing=(decision.get('urgency') or {}).get('closing_at')
        if closing:due=min(due,max(int(created_at),int(closing)-60))
    return key,outside_quiet_hours(due,pref)

def delivered_refs(conn,table,uid,device_id=None):
    """Prospective idempotency across digest/preference changes.

    Uncertain email submissions may have reached the provider: never blindly
    replay those receipts. Legacy payloads without references stay unknown.
    """
    if table not in {'push_outbox','mail_outbox'}:raise ValueError('Unsupported delivery ledger')
    params=[uid]
    scope=''
    if table=='push_outbox':scope=' AND device_id=?';params.append(device_id)
    states="('accepted','uncertain')" if table=='mail_outbox' else "('accepted')"
    found=set()
    for row in conn.execute('SELECT payload FROM '+table+' WHERE user_id=? AND state IN '+states+scope,params):
        try:value=json.loads(row['payload'])
        except (ValueError,TypeError):continue
        if isinstance(value,dict):
            found.update(x for name in ('receipt_refs','event_refs') for x in value.get(name,[]) if isinstance(x,str))
    return found

def receipt_payload(payload,notices):
    from .push_delivery import receipt_summary
    return {**payload,'body':receipt_summary(notices),
            'receipt_refs':[n['ref'] for n in notices if n.get('ref')],
            'priority':min((n.get('priority','R') for n in notices),default='R')}
