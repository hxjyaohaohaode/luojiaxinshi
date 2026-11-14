"""Shared, explainable delivery plans for personal arrangements and collaboration.

Plans are derived from current owner-scoped records. They confer no consent and
never claim that a provider acceptance proves device display or reading.
"""
from datetime import date, datetime, time, timedelta
import json
import hashlib

from .schedule import CST
from .proactive_policy import next_digest, outside_quiet_hours


def phase_updates(conn,uid,now):
    from .notice_tracking import summary
    rows=[dict(row) for row in conn.execute('''SELECT p.notice_id,p.version,p.updated_at,n.title
        FROM notice_phase_tracking p JOIN notices n ON n.id=p.notice_id
        WHERE p.user_id=? AND n.user_id=? AND p.notice_version=n.version AND p.updated_at>=?
        AND json_extract(p.data,'$.phase') IN ('publicity','result')''',(uid,uid,now-86400))]
    phases=summary(conn,uid,[row['notice_id'] for row in rows])
    return [{**row,**phases[row['notice_id']]} for row in rows
            if row['notice_id'] in phases and not phases[row['notice_id']].get('review_required')]


def extra_candidates(conn, uid, now):
    from .insights import arrangement_occurrences
    from .collaboration import IN_SCOPE,reminders
    result = {}
    today = datetime.fromtimestamp(now, CST).date()
    for row in conn.execute('SELECT * FROM arrangements WHERE user_id=?', (uid,)):
        data = json.loads(row['data'])
        minutes = data.get('reminder_minutes')
        if minutes is None:
            continue
        # Include enough future occurrences for the largest explicit offset.
        for day in arrangement_occurrences(data, today - timedelta(days=1), today + timedelta(days=9)):
            at = datetime.combine(day, time.fromisoformat(data['start_time']) if data.get('start_time') else time(9), CST)
            start = int(at.timestamp())
            due = start - minutes * 60
            expires = start + 60
            # Workers poll and recheck before sending. A start-time reminder
            # remains valid throughout its declared grace window, not just
            # the exact start second; the expiry boundary stays exclusive.
            if now >= expires or due < now - 86400:
                continue
            # Identity depends on the actual reminder time and occurrence, not
            # an unrelated note edit; changing time revokes the previous plan.
            key = f'arrangement:{row["id"]}:{day.isoformat()}:{due}'
            result[key] = {'due_at': due, 'expires_at': expires, 'prospective': True,
                'category': 'arrangement', 'created_at': 0,
                'payload': {'user_id': uid, 'title': data['title'][:90],
                    'body': '你设置的安排即将开始，请查看时间和地点' if data.get('start_time') else '今天有你设置的全天安排；09:00 是提醒时刻',
                    'url': '/#calendar/' + row['id'], 'tag': 'arrangement:' + row['id']}}
    for case in reminders(conn, uid, now):
        if case['updated_at'] < now - 86400:
            continue
        # The owner's history can outlive an assignment. Sending another
        # reminder requires today's shared authority and current event identity.
        current=conn.execute(f"""SELECT c.version,c.state,{IN_SCOPE} AS in_scope,
            CASE WHEN c.state='withdrawn' AND EXISTS(SELECT 1 FROM collaboration_events e
              WHERE e.case_id=c.id AND e.version=c.version AND e.action='decline')
              THEN 'declined' ELSE c.state END AS public_state,
            n.id AS notice_id,n.user_id AS notice_owner,
            f.version AS followup_version,f.due_at AS followup_at
            FROM collaboration_cases c
            LEFT JOIN tasks t ON t.id=c.task_id AND t.user_id=c.sender_id
            LEFT JOIN notices n ON n.id=t.notice_id AND n.user_id=c.sender_id
            LEFT JOIN collaboration_followups f ON f.case_id=c.id AND f.user_id=?
            WHERE c.id=? AND (c.sender_id=? OR c.recipient_id=?)""",(uid,case['id'],uid,uid)).fetchone()
        if current is None or not current['in_scope']:
            continue
        if case['state']=='followup':
            if (current['state'] in {'resolved','withdrawn'} or current['followup_version']!=case['version']
                    or current['followup_at']!=case['updated_at']):
                continue
        elif current['version']!=case['version'] or current['public_state']!=case['state']:
            continue
        key = f'collaboration:{case["id"]}:{case["version"]}:{case["state"]}'
        result[key] = {'due_at': case['updated_at'], 'expires_at': case['updated_at'] + 86400,
            'created_at': case['updated_at'], 'prospective': True, 'category': 'collaboration',
            # Sensitive titles, names, materials and reasons never go to a lock screen.
            'payload': {'user_id': uid, 'title': '站内协作有新进展',
                'body': '请登录珞珈信使核对当前协作与回执',
                'url': '/#collaboration/' + case['id'], 'tag': 'collaboration:' + case['id']}}
        # Apply an institutional reference/expiry restriction internally, but
        # never expose the counterparty's private notice ID in the event. Only
        # the owner can apply their personal notice/source routing override.
        nid=current['notice_id']
        if nid:
            from .campus_policy import suppress_external_notice
            if suppress_external_notice(conn,nid,now):
                result[key]['suppression_reason']='发布方标为历史参考或已超过其显式有效期；站内协作记录保留'
            if current['notice_owner']==uid:result[key]['notice_id']=nid
    from .source_sync import recent_failures
    for failure in recent_failures(conn,uid,now):
        at=failure['checked_at']
        key=f'source-health:{failure["source_id"]}:{failure["problem_version"]}'
        result[key]={'due_at':at,'expires_at':at+86400,'created_at':at,'prospective':True,'category':'source_health',
            'payload':{'user_id':uid,'title':'你订阅的来源需要核对',
                'body':'来源读取尚未完成，当前覆盖不能判定为没有新通知。请在来源页核对失败与恢复状态。',
                'url':'/#sources','tag':'source-health:'+failure['source_id']}}
    for phase in phase_updates(conn,uid,now):
        at=phase['updated_at'];nid=phase['notice_id']
        key=f'phase:{nid}:{phase["version"]}:{phase["phase"]}'
        result[key]={'due_at':at,'expires_at':at+86400,'created_at':at,'prospective':True,'category':'task','notice_id':nid,
            'payload':{'user_id':uid,'title':'已核对的公示或结果记录更新',
                'body':'请查看当前阶段、原文依据与本人后续行动；公示结束不等于正式结果。',
                'url':'/#notice/'+nid,'tag':'notice:'+nid}}
    return result


def category(key):
    if key.startswith('received:'):
        return 'receipt'
    if key.startswith('arrangement:'):
        return 'arrangement'
    if key.startswith('collaboration:'):
        return 'collaboration'
    return 'task'


def apply_policy(items, pref, now, *, include_suppressed=False):
    result = {}
    for key, event in items.items():
        group = event.get('category') or category(key)
        event['category'] = group
        mode = event.get('route_mode') or getattr(pref, group + '_delivery', 'immediate')
        reason = event.get('suppression_reason','')
        original = event['due_at']
        due = original
        if mode in {'in_app', 'off'}:
            reason = '本人选择仅站内提醒' if mode == 'in_app' else '本人关闭了此类提醒'
        else:
            # Receipt candidates already carry a slot resolved from current
            # relevance, owner routes and quiet hours. Scheduling them again
            # would move a digest to the following day and past its expiry.
            if group != 'receipt' and mode == 'digest':
                due = next_digest(original, pref.digest_hour)
            urgent = group != 'receipt' and key.startswith(('change:', 'review:', 'intake-change:'))
            if not (urgent and pref.allow_urgent_during_quiet):
                due = outside_quiet_hours(due, pref)
                # A delayed worker cannot use an old, pre-quiet due time as
                # permission to send during the current quiet window. Keep
                # the stable original slot unless a real quiet delay applies.
                if due <= now:
                    current_end = outside_quiet_hours(now, pref)
                    if current_end > now:
                        due = max(due, current_end)
            if event.get('expires_at') is not None and now >= event['expires_at']:
                reason = '本次提醒已超过有效窗口；保留站内记录，请核对当前事项'
            elif event.get('expires_at') is not None and due >= event['expires_at']:
                reason = '免打扰或摘要时刻已晚于本次有效窗口；保留站内记录，请核对偏好'
        event['due_at'] = due
        event['policy'] = {'mode': mode, 'original_due_at': original, 'due_at': due,
                           'delayed': due != original, 'suppressed': bool(reason),
                           'reason': reason or ('按免打扰或摘要偏好延后' if due != original else '按本人偏好安排')}
        if not reason or include_suppressed:
            result[key] = event
    return result


def channel_events(events, seen, baseline):
    """Aggregate eligible category digests without replaying accepted components.

    The ledger stores the underlying event identities. Preference changes or
    a cancellation within a digest cannot resend the remaining accepted items.
    Each channel performs this calculation against its own consent and ledger.
    """
    result={};buckets={}
    for key,event in events.items():
        if key.startswith('received:'):
            result[key]=event
            continue
        if key in seen:
            continue
        if event.get('prospective') and (event.get('created_at',0) and event['created_at']<baseline or event.get('policy',{}).get('original_due_at',event['due_at'])<baseline):
            continue
        value={**event,'payload':{**event['payload'],'event_refs':[key]}}
        if event.get('policy',{}).get('mode')!='digest':
            result[key]=value
            continue
        buckets.setdefault((event['category'],event['due_at']),[]).append((key,value))
    labels={'receipt':'收件与关注内容','task':'待办','arrangement':'个人安排','collaboration':'站内协作','source_health':'来源状态'}
    routes={'receipt':'notices','task':'tasks','arrangement':'calendar','collaboration':'collaboration','source_health':'sources'}
    for (group,due),members in buckets.items():
        refs=sorted(key for key,_ in members)
        signature=hashlib.sha256(json.dumps(refs,separators=(',',':')).encode()).hexdigest()[:24]
        key=f'digest:{group}:{due}:{signature}'
        first=members[0][1]
        result[key]={**first,'created_at':max(event.get('created_at',0) for _,event in members),
            'payload':{'user_id':first['payload']['user_id'],'title':f'{labels[group]}提醒摘要（{len(members)}项）',
                       'body':'已合并同一摘要窗口内仍然有效的事项，请登录核对当前内容与变化。',
                       'url':'/#'+routes[group],'tag':'digest:'+group,'event_refs':refs}}
    return result


MATRIX = [
    {'kind': 'receipt', 'label': '新收件与关注内容更新', 'in_app': True, 'push': True, 'email': True,
     'condition': '按相关性、来源与摘要偏好；历史基线不重放'},
    {'kind': 'task', 'label': '本人期限、活动、跟进与正式更正', 'in_app': True, 'push': True, 'email': True,
     'condition': '本人已选择事项，正式时间已核对；变更后重算并取消旧计划'},
    {'kind': 'arrangement', 'label': '个人安排与课程', 'in_app': True, 'push': True, 'email': True,
     'condition': '每项安排显式设置提前提醒；导入课程默认不外发'},
    {'kind': 'collaboration', 'label': '协作收件、补件、补交与办结', 'in_app': True, 'push': True, 'email': True,
     'condition': '默认仅站内，须主动开启协作外发；发送时重核双方权限'},
    {'kind': 'source_health', 'label': '来源失败与采集覆盖', 'in_app': True, 'push': True, 'email': True,
     'condition': '默认仅站内；本人显式开启后才外发，重复同类故障不重复发送，恢复或停用即撤销'},
]

EVENT_MATRIX=[
    {'event':'announcement','category':'receipt','label':'新公告','basis':'新收件、当前适用性与来源授权'},
    {'event':'opening','category':'task','label':'开放办理／活动开始','basis':'本人事项中已核对的 scheduled 时段'},
    {'event':'deadline','category':'task','label':'正式期限','basis':'本人已核对的正式日期；日期级提醒不冒充时刻'},
    {'event':'correction','category':'task','label':'提前／延期／更正','basis':'待核实变更或办理复核；未核实不改正式值'},
    {'event':'cancellation','category':'task','label':'取消／恢复','basis':'明确变更版本；旧有效计划重新核对'},
    {'event':'supplement','category':'collaboration','label':'补件／补交','basis':'当前双方权限与协作版本'},
    {'event':'result','category':'task','label':'公示／结果','basis':'新公告按自身证据处理；本人已核对的当前公示/结果版本独立提醒，不用旧报名期限判断新结果'},
    {'event':'followup','category':'task','label':'本人跟进','basis':'本人设置的跟进时刻'},
    {'event':'source_failure','category':'source_health','label':'来源读取失败','basis':'实际采集失败与规则版本，不把失败说成无更新'},
]


def install(app, db, settings, user):
    from fastapi import Depends, Query
    from .cloud_messages import CloudMessages
    from .proactive_policy import preferences
    from .mail_delivery import preference
    from .push_delivery import candidates
    import time as clock

    @app.get('/api/notifications/matrix')
    def matrix(current=Depends(user)):
        with db.connect() as conn:
            profile = conn.execute('SELECT profile FROM users WHERE id=?', (current['id'],)).fetchone()[0]
            devices = conn.execute('SELECT COUNT(*) FROM push_devices WHERE user_id=? AND enabled=1', (current['id'],)).fetchone()[0]
            mail = bool(preference(conn, current['id']))
        return {'categories': MATRIX,'events':EVENT_MATRIX, 'preferences': preferences(profile).model_dump(),
                'channels': {'push': {'configured': True, 'enabled_devices': devices},
                             'email': {'configured': CloudMessages(settings).available('email'), 'enabled': mail}},
                'receipt_meanings': {'pending': '等待执行', 'leased': '执行中', 'sending': '正在提交邮件',
                    'accepted': '供应商接受；设备展示与本人阅读未知', 'uncertain': '提交结果不确定，不自动重发',
                    'failed': '失败，查看原因与恢复入口', 'cancelled': '已撤销的旧计划'},
                'device_validation': '真实设备前台、后台、锁屏、关闭和断网恢复须分别核验'}

    @app.get('/api/notifications/routes')
    def routes(notice_id:str='',current=Depends(user)):
        from fastapi import HTTPException
        from .notification_routing import notice_modes,source_routes
        with db.connect() as conn:
            profile=conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()[0]
            pref=preferences(profile)
            sources=[{'id':row['id'],'title':row['title'],
                      'mode':pref.source_delivery.get(row['id'],'inherit')}
                     for row in source_routes(conn,current['id'])]
            notice=None
            if notice_id:
                row=conn.execute('SELECT id,title FROM notices WHERE id=? AND user_id=?',(notice_id,current['id'])).fetchone()
                if not row:raise HTTPException(404,'通知不存在或无权访问')
                notice={**dict(row),'mode':pref.notice_delivery.get(notice_id,'inherit'),
                        'effective_mode':notice_modes(conn,current['id'],pref).get(notice_id,'inherit')}
        return {'preferences':pref.model_dump(),'sources':sources,'notice':notice,
                'precedence':'事项设置优先；同一通知含多个来源时采用其中更保守的显式设置；未设置时继承类别偏好。规则不改变资格、证据或授权。'}

    @app.get('/api/notifications/plan')
    def plan(limit: int = Query(default=50, ge=1, le=100), current=Depends(user)):
        now = int(clock.time())
        with db.connect() as conn:
            events = candidates(conn, current['id'], now, include_suppressed=True)
            rows = [{'event_key': key, **{k: value[k] for k in ('due_at', 'category', 'policy')},
                     'title': value['payload']['title'], 'url': value['payload']['url']}
                    for key, value in events.items()]
            rows.sort(key=lambda row: (row['due_at'], row['event_key']))
            recent = []
            for table, channel in [('push_outbox', 'push'), ('mail_outbox', 'email')]:
                recent.extend({'channel': channel, **dict(row)} for row in conn.execute(
                    'SELECT event_key,state,due_at,created_at,finished_at,error FROM ' + table +
                    ' WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?', (current['id'], limit)))
        recent.sort(key=lambda row: row['created_at'], reverse=True)
        return {'evaluated_at': now, 'items': rows[:limit], 'total': len(rows),
                'has_more': len(rows) > limit, 'recent': recent[:limit],
                'note': '当前计划随事项、权限与偏好重算。已读只代表站内显式操作，供应商接受不代表本人看到。'}
