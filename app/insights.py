"""提醒中心与数据看板。

提醒：按北京时间汇总“现在需要留意的事”，包括已过期、即将到期（含尚未确认的期限，
单独标注）、本人设置的提醒、到期跟进、待核实的通知变化、今明两天的个人安排和未整理的通知。
页面打开时由前端按 next_at 触发浏览器通知；本服务不向手机推送。

看板：个人只统计本人数据；管理员看板只返回全站计数，不含任何人的通知内容或身份信息。
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import time
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field

CST = timezone(timedelta(hours=8))
LEVELS = {'urgent': 0, 'attention': 1, 'info': 2}

REMINDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminder_states(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 reminder_id TEXT NOT NULL, read_at INTEGER, archived_at INTEGER,
 PRIMARY KEY(user_id, reminder_id));
"""


class ReminderStateUpdate(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=1000)
    state: Literal['read', 'unread', 'archived']


def reminder_id(item):
    # Relative wording (today/tomorrow) must not reset read state. A changed
    # deadline, urgency, occurrence or source revision is a new reminder.
    identity = {key: item.get(key) for key in (
        'kind', 'level', 'task_id', 'arrangement_id', 'notice_id', 'at',
        'title', 'confirmed', 'revision',
    )}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def apply_reminder_states(conn, uid, result):
    saved = {r['reminder_id']: r for r in conn.execute(
        'SELECT reminder_id,read_at,archived_at FROM reminder_states WHERE user_id=?', (uid,))}
    for item in result['items']:
        row = saved.get(item['id'])
        item['is_read'] = bool(row and row['read_at'])
        item['is_archived'] = bool(row and row['archived_at'])
    unread = [item for item in result['items'] if not item['is_read'] and not item['is_archived']]
    result['unread_counts'] = {level: sum(item['level'] == level for item in unread) for level in LEVELS}
    result['unread_counts']['total'] = len(unread)
    return result


def deadline_of(data):
    """返回 (截止时刻, 是否全天)。全天期限按当天 23:59 计算剩余时间，不改写原值。"""
    if not data.get('due_date'):
        return None, False
    try:
        day = date.fromisoformat(data['due_date'])
        if data.get('due_time'):
            hour, minute = map(int, data['due_time'][:5].split(':'))
            return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CST), False
        return datetime(day.year, day.month, day.day, 23, 59, tzinfo=CST), True
    except ValueError:
        return None, False


def parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=CST)


def relative_day(moment, now):
    days = (moment.astimezone(CST).date() - now.date()).days
    return {0: '今天', 1: '明天', 2: '后天', -1: '昨天'}.get(days, f'{moment.astimezone(CST):%m月%d日}'.lstrip('0'))


def clock_text(moment, all_day=False):
    return '' if all_day else f'{moment.astimezone(CST):%H:%M}'


def arrangement_occurrences(data, start, end):
    """个人安排在 [start, end) 日期区间内的发生日。"""
    first = date.fromisoformat(data['start_date'])
    step = {'weekly': 7, 'biweekly': 14}.get(data.get('repeat'), 0)
    last = date.fromisoformat(data['repeat_until']) if step and data.get('repeat_until') else first
    day = first
    while day <= last and day < end:
        if day >= start:
            yield day
        if not step:
            break
        day += timedelta(days=step)


def build_reminders(tasks, notices, arrangements, now=None):
    now = (now or datetime.now(CST)).astimezone(CST)
    items, upcoming = [], []
    for task in tasks:
        data = task['data']
        if task['status'] != 'pending' or data.get('scope') != 'personal' or task.get('action_excluded'):
            continue
        title = data.get('title') or '未命名事项'
        source = task.get('notice_title') or ''
        deadline, all_day = deadline_of(data)
        confirmed = bool(data.get('deadline_confirmed'))
        if deadline:
            left = deadline - now
            when = relative_day(deadline, now) + (' ' + clock_text(deadline, all_day) if not all_day else '')
            note = '' if confirmed else '期限还没确认，记得对照原文核实'
            if left < timedelta(0) and left > -timedelta(days=14):
                items.append({'kind': 'overdue', 'level': 'urgent', 'title': title, 'text': f'已经过了截止时间（{when}）', 'note': note,
                              'at': deadline.isoformat(), 'task_id': task['id'], 'notice_title': source, 'confirmed': confirmed})
            elif timedelta(0) <= left <= timedelta(hours=24):
                items.append({'kind': 'due', 'level': 'urgent', 'title': title, 'text': f'{when}截止', 'note': note,
                              'at': deadline.isoformat(), 'task_id': task['id'], 'notice_title': source, 'confirmed': confirmed})
            elif timedelta(hours=24) < left <= timedelta(days=3):
                items.append({'kind': 'due', 'level': 'attention', 'title': title, 'text': f'{when}截止', 'note': note,
                              'at': deadline.isoformat(), 'task_id': task['id'], 'notice_title': source, 'confirmed': confirmed})
            elif timedelta(days=3) < left <= timedelta(days=7):
                items.append({'kind': 'due', 'level': 'info', 'title': title, 'text': f'{when}截止', 'note': note,
                              'at': deadline.isoformat(), 'task_id': task['id'], 'notice_title': source, 'confirmed': confirmed})
            if confirmed:
                # 截止前 24 小时与 1 小时各给一次页面内提醒。
                for lead in (timedelta(hours=24), timedelta(hours=1)):
                    moment = deadline - lead
                    if now < moment <= now + timedelta(hours=24):
                        upcoming.append({'at': moment.isoformat(), 'title': title, 'text': f'{"明天" if lead.days else "1 小时后"}截止', 'task_id': task['id']})
        slot=data.get('scheduled')
        if slot:
            start=parse_time(slot['start_date']+'T'+(slot.get('start_time') or '00:00'))
            end=parse_time((slot.get('end_date') or slot['start_date'])+'T'+(slot.get('end_time') or '23:59'))
            if end>=now and start<=now+timedelta(days=7):
                kind='活动' if slot['kind']=='event' else '办理时段'
                when=relative_day(start,now)+(' '+slot['start_time'] if slot.get('start_time') else '（时刻未明确）')
                items.append({'kind':'notice_event','level':'attention' if start<=now+timedelta(days=1) else 'info',
                              'title':title,'text':kind+' · '+when,'note':'' if slot['confirmed'] else '时段待对照原文核实',
                              'at':start.isoformat(),'task_id':task['id'],'notice_title':source,'confirmed':slot['confirmed'],
                              'revision':[slot.get('end_date'),slot.get('end_time'),slot['kind']]})
                if slot['confirmed'] and slot.get('start_time'):
                    moment=start-timedelta(minutes=15)
                    if now<moment<=now+timedelta(days=1):
                        upcoming.append({'at':moment.isoformat(),'title':title,'text':kind+'将在 15 分钟后开始','task_id':task['id']})
        reminder = parse_time(data.get('reminder_at'))
        if reminder and now - timedelta(hours=12) <= reminder <= now + timedelta(hours=24):
            due = reminder <= now
            items.append({'kind': 'reminder', 'level': 'attention' if due else 'info', 'title': title,
                          'text': ('到了你设定的提醒时间' if due else f'{relative_day(reminder, now)} {clock_text(reminder)} 提醒你'),
                          'at': reminder.isoformat(), 'task_id': task['id'], 'notice_title': source})
            if not due:
                upcoming.append({'at': reminder.isoformat(), 'title': title, 'text': '到了你设定的提醒时间', 'task_id': task['id']})
        if task.get('followup_due'):
            items.append({'kind': 'followup', 'level': 'attention', 'title': title, 'text': '到了跟进时间，看看办理进展',
                          'at': (task.get('workflow') or {}).get('data', {}).get('followup_at'), 'task_id': task['id'], 'notice_title': source})
        if task.get('pending_changes'):
            items.append({'kind': 'change', 'level': 'attention', 'title': title, 'text': f'通知有 {len(task["pending_changes"])} 处变化等你核实',
                          'task_id': task['id'], 'notice_title': source,
                          'revision': sorted(task['pending_changes'], key=lambda change: json.dumps(change, sort_keys=True))})
    today = now.date()
    for record in arrangements:
        data = record['data']
        for day in arrangement_occurrences(data, today, today + timedelta(days=2)):
            start_time = data.get('start_time')
            if start_time:
                hour, minute = map(int, start_time.split(':'))
                moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=CST)
                if moment < now - timedelta(hours=1):
                    continue
                text = f'{relative_day(moment, now)} {start_time}' + (f' · {data["location"]}' if data.get('location') else '')
                if now < moment - timedelta(minutes=15) <= now + timedelta(hours=24):
                    upcoming.append({'at': (moment - timedelta(minutes=15)).isoformat(), 'title': data['title'], 'text': '15 分钟后开始', 'arrangement_id': record['id']})
            else:
                moment = datetime(day.year, day.month, day.day, tzinfo=CST)
                text = relative_day(moment, now) + ' 全天'
            items.append({'kind': 'arrangement', 'level': 'info', 'title': data['title'], 'text': text,
                          'at': moment.isoformat(), 'arrangement_id': record['id'], 'category': data.get('category'),
                          'revision': record.get('version')})
    waiting = [n for n in notices if n['status'] in {'received', 'draft', 'failed'} and n.get('disposition','inbox') == 'inbox']
    if waiting:
        drafts = sum(1 for n in waiting if n['status'] == 'draft')
        items.append({'kind': 'notice', 'level': 'info', 'title': f'{len(waiting)} 则通知待处理',
                      'text': f'其中 {drafts} 则已经整理好，等你确认' if drafts else '整理一下，看看有没有要做的事',
                      'notice_id': waiting[0]['id'] if len(waiting) == 1 else None,
                      'revision': sorted((n['id'], n['status'], n.get('version', 1)) for n in waiting)})
    for item in items:
        item['id'] = reminder_id(item)
        item.pop('revision', None)
    items.sort(key=lambda item: (LEVELS[item['level']], item.get('at') or '9999'))
    upcoming.sort(key=lambda item: item['at'])
    counts = Counter(item['level'] for item in items)
    return {'generated_at': now.isoformat(), 'items': items, 'upcoming': upcoming[:20],
            'counts': {'urgent': counts['urgent'], 'attention': counts['attention'], 'info': counts['info'], 'total': len(items)}}


def completion_times(conn, uid):
    """每项待办最近一次被标记完成的时间（来自修改记录）。"""
    result = {}
    for row in conn.execute("SELECT task_id,before_json,after_json,created_at FROM audit WHERE user_id=? AND action='update_task' AND task_id IS NOT NULL ORDER BY created_at,id", (uid,)):
        try:
            after = json.loads(row['after_json'] or 'null') or {}
            before = json.loads(row['before_json'] or 'null') or {}
        except ValueError:
            continue
        if after.get('status') == 'done':
            if before.get('status') != 'done':result[row['task_id']] = row['created_at']
        elif after.get('status') in {'pending', 'cancelled'}:
            result.pop(row['task_id'], None)
    return result


def personal_insights(conn, uid, now=None, current_tasks=None):
    now = (now or datetime.now(CST)).astimezone(CST)
    notices = [dict(r) for r in conn.execute("SELECT n.id,n.status,n.source_label,n.draft,n.created_at,COALESCE(d.disposition,'inbox') AS disposition FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id WHERE n.user_id=?", (uid,))]
    tasks = []
    for row in conn.execute('SELECT id,status,data,created_at,updated_at FROM tasks WHERE user_id=?', (uid,)):
        item = dict(row)
        item['data'] = json.loads(item['data'])
        tasks.append(item)
    if current_tasks is not None:tasks=current_tasks
    personal = [t for t in tasks if t['data'].get('scope') == 'personal']
    eligible = [t for t in personal if not t.get('action_excluded')]
    pending = [t for t in eligible if t['status']=='pending']
    done_at = {tid:moment for tid,moment in completion_times(conn, uid).items() if tid in {t['id'] for t in eligible if t['status']=='done'}}
    status = Counter(t['status'] for t in eligible)
    on_time = late = 0
    for task in personal:
        if task['status'] != 'done' or task['id'] not in done_at:
            continue
        deadline, _ = deadline_of(task['data'])
        if deadline is None or not task['data'].get('deadline_confirmed'):
            continue
        if done_at[task['id']] <= deadline.timestamp():
            on_time += 1
        else:
            late += 1
    # 近 8 周每周完成数（周一为一周开始）
    monday = now.date() - timedelta(days=now.weekday())
    weeks = [monday - timedelta(weeks=i) for i in range(7, -1, -1)]
    weekly = Counter()
    weekly_ids = {}
    for tid, moment in done_at.items():
        day = datetime.fromtimestamp(moment, CST).date()
        start = day - timedelta(days=day.weekday())
        weekly[start] += 1
        weekly_ids.setdefault(start,[]).append(tid)
    trend = [{'week': w.isoformat(), 'label': f'{w.month}/{w.day}', 'done': weekly[w],'ids':weekly_ids.get(w,[])} for w in weeks]
    # 未来 4 周的期限分布
    horizon = []
    for i in range(4):
        start = monday + timedelta(weeks=i)
        horizon.append({'week': start.isoformat(), 'label': '本周' if i == 0 else '下周' if i == 1 else f'{start.month}/{start.day} 起',
                        'confirmed': 0, 'unconfirmed': 0,'ids':[]})
    overdue = 0
    for task in pending:
        deadline, _ = deadline_of(task['data'])
        if deadline is None:
            continue
        if deadline < now:
            overdue += bool(task['data'].get('deadline_confirmed'))
            continue
        index = (deadline.date() - monday).days // 7
        if 0 <= index < 4:
            horizon[index]['confirmed' if task['data'].get('deadline_confirmed') else 'unconfirmed'] += 1
            horizon[index]['ids'].append(task['id'])
    sources = Counter((n['source_label'] or '本人提交').strip() or '本人提交' for n in notices)
    relevance = Counter()
    for notice in notices:
        if notice['draft']:
            try:
                relevance[json.loads(notice['draft']).get('applicability') or 'unknown'] += 1
            except ValueError:
                relevance['unknown'] += 1
        else:
            relevance['unprocessed'] += 1
    origins = Counter(t['data'].get('origin', 'manual') for t in personal)
    ai = Counter(r['status'] for r in conn.execute('SELECT status FROM ai_calls WHERE user_id=?', (uid,)))
    def group(key,label,kind,records):
        return {'key':key,'label':label,'kind':kind,'count':len(records),'ids':[r['id'] for r in records]}
    notice_rows=[group('all','全部通知','notices',notices)]
    for key,label in [('received','待整理'),('draft','待确认'),('processing','整理中'),('failed','整理失败'),('confirmed','已转为行动')]:
        notice_rows.append(group(key,label,'notices',[n for n in notices if n['status']==key and n['disposition']=='inbox']))
    for key,label in [('reference','仅存资料'),('not_applicable','与我无关'),('closed','已结束')]:
        notice_rows.append(group(key,label,'notices',[n for n in notices if n['disposition']==key]))
    active_sources=list(conn.execute('SELECT s.notice_id,s.kind,o.data AS origin FROM sources s JOIN notices n ON n.id=s.notice_id LEFT JOIN notice_source_origins o ON o.source_id=s.id WHERE n.user_id=? AND s.active=1',(uid,)))
    intake=[]
    for key,label in [('text','粘贴正文'),('file','上传材料'),('link','链接快照')]:
        ids={r['notice_id'] for r in active_sources if (bool(r['origin']) if key=='link' else not r['origin'] and (r['kind']=='text' if key=='text' else r['kind']!='text'))}
        intake.append(group(key,label,'notices',[n for n in notices if n['id'] in ids]))
    task_rows=[group('all','本人事项','tasks',personal),group('pending','待完成','tasks',pending),group('done','已完成','tasks',[t for t in eligible if t['status']=='done']),group('cancelled','已取消','tasks',[t for t in eligible if t['status']=='cancelled']),group('excluded','已决定不参加','tasks',[t for t in personal if t.get('action_excluded')])]
    def timing_review(t):
        d=t['data'];slot=d.get('scheduled');mode=t.get('workflow',{}).get('data',{}).get('execution_mode')
        return bool(d.get('due_date') and not d.get('deadline_confirmed') or slot and not slot.get('confirmed') or not d.get('due_date') and not slot and mode in {None,'submission'})
    timing=[group('overdue','已过期未完成','tasks',[t for t in pending if t['data'].get('deadline_confirmed') and deadline_of(t['data'])[0] and deadline_of(t['data'])[0]<now]),group('unverified','时间待核对','tasks',[t for t in pending if timing_review(t)]),group('event','活动时间','tasks',[t for t in pending if t['data'].get('scheduled',{} ) and t['data']['scheduled']['kind']=='event']),group('window','办理时段','tasks',[t for t in pending if t['data'].get('scheduled',{}) and t['data']['scheduled']['kind']=='window'])]
    progress=[group('followup','待跟进','tasks',[t for t in pending if t.get('followup_due') or t.get('workflow',{}).get('data',{}).get('board_lane')=='followup' or t.get('workflow',{}).get('data',{}).get('stage') in {'submitted','supplement','blocked','waiting'}]),group('changes','变化待复核','tasks',[t for t in personal if t.get('pending_changes') or (t.get('change_review') or {}).get('state')=='pending']),group('blocked','受阻或前提待确认','tasks',[t for t in pending if t.get('workflow',{}).get('blocked') or t.get('workflow',{}).get('data',{}).get('stage')=='blocked' or t.get('execution_issues')]),group('sync','日历待同步','tasks',[t for t in personal if t.get('needs_calendar_sync') or t.get('calendar_check_required')])]
    return {
        'dimensions':{'notices':notice_rows,'intake':intake,'tasks':task_rows,'timing':timing,'progress':progress},
        'generated_at': now.isoformat(),
        'notices': {'total': len(notices), 'confirmed': sum(n['status'] == 'confirmed' for n in notices),
                    'waiting': sum(n['status'] in {'received', 'draft', 'failed'} and n['disposition']=='inbox' for n in notices)},
        'tasks': {'total': len(personal), 'done': status['done'], 'pending': status['pending'], 'cancelled': status['cancelled'],
                  'overdue': overdue, 'on_time': on_time, 'late': late, 'from_ai': origins['ai'], 'manual': origins['manual']},
        'trend': trend, 'horizon': horizon,
        'sources': [{'label': label, 'count': count} for label, count in sources.most_common(6)],
        'relevance': {'matches_known': relevance['matches_known'], 'needs_review': relevance['needs_review'],
                      'not_matching': relevance['not_matching'], 'unprocessed': relevance['unprocessed'],'unknown':relevance['unknown']},
        'ai': {'calls': sum(ai.values()), 'succeeded': ai['succeeded']},
    }


def admin_insights(conn, now=None):
    """全站匿名计数：不返回任何账号、通知标题、来源名称或正文。"""
    now = (now or datetime.now(CST)).astimezone(CST)
    week = int((now - timedelta(days=7)).timestamp())
    month = int((now - timedelta(days=30)).timestamp())
    one = lambda sql, *args: conn.execute(sql, args).fetchone()[0]
    ai = Counter(r['status'] for r in conn.execute('SELECT status FROM ai_calls WHERE created_at>=?', (month,)))
    tasks = Counter(r['status'] for r in conn.execute('SELECT status FROM tasks'))
    return {
        'generated_at': now.isoformat(),
        'users': {'total': one('SELECT COUNT(*) FROM users'),
                  'active_7d': one('SELECT COUNT(DISTINCT user_id) FROM audit WHERE created_at>=?', week)},
        'notices': {'total': one('SELECT COUNT(*) FROM notices'), 'last_30d': one('SELECT COUNT(*) FROM notices WHERE created_at>=?', month),
                    'confirmed': one("SELECT COUNT(*) FROM notices WHERE status='confirmed'")},
        'tasks': {'total': sum(tasks.values()), 'done': tasks['done'], 'pending': tasks['pending'], 'cancelled': tasks['cancelled']},
        'ai_30d': {'calls': sum(ai.values()), 'failed': ai['failed']},
    }


def install(app, db, user, admin, list_tasks):
    from .schedule import serialize as serialize_arrangement

    def current_reminders(conn, uid):
        tasks = list_tasks(conn, uid)
        notices = [dict(r) for r in conn.execute("SELECT n.id,n.status,n.version,COALESCE(d.disposition,'inbox') AS disposition FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id WHERE n.user_id=?", (uid,))]
        arrangements = [serialize_arrangement(r) for r in conn.execute('SELECT * FROM arrangements WHERE user_id=?', (uid,))]
        return build_reminders(tasks, notices, arrangements)

    @app.get('/api/reminders')
    def reminders(current=Depends(user)):
        with db.connect() as conn:
            return apply_reminder_states(conn, current['id'], current_reminders(conn, current['id']))

    @app.post('/api/reminders/state')
    def update_reminders(payload: ReminderStateUpdate, current=Depends(user)):
        uid, now = current['id'], int(time.time())
        with db.connect(write=True) as conn:
            result = current_reminders(conn, uid)
            active = {item['id'] for item in result['items']}
            # Only the submitted snapshot can be marked. Newly arrived items
            # and another account's reminders are never included implicitly.
            selected = active.intersection(payload.ids)
            for rid in selected:
                conn.execute('''INSERT INTO reminder_states(user_id,reminder_id,read_at,archived_at)
                    VALUES(?,?,?,?) ON CONFLICT(user_id,reminder_id) DO UPDATE SET
                    read_at=excluded.read_at,archived_at=excluded.archived_at''',
                    (uid, rid, None if payload.state == 'unread' else now,
                     now if payload.state == 'archived' else None))
            result = apply_reminder_states(conn, uid, result)
            result['updated'] = len(selected)
            return result

    @app.get('/api/insights')
    def insights(current=Depends(user)):
        with db.connect() as conn:
            return personal_insights(conn, current['id'], current_tasks=list_tasks(conn,current['id']))

    @app.get('/api/admin/insights')
    def site_insights(current=Depends(admin)):
        with db.connect() as conn:
            return admin_insights(conn)
