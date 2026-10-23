from datetime import date, datetime, time, timedelta, timezone

from icalendar import Alarm, Calendar, Event

CST=timezone(timedelta(hours=8))


def eligible(data):
    if data['scope']!='personal':
        raise ValueError('请先核对任务确实由本人办理')
    if not data['due_date'] and not data['planned_at'] and not data.get('scheduled'):
        raise ValueError('请先设置经核实的期限、活动时段或个人计划时间')
    if data['due_date'] and not data['deadline_confirmed']:
        raise ValueError('正式期限尚未由本人确认')
    if data.get('scheduled') and not data['scheduled']['confirmed']:
        raise ValueError('活动或办理时段尚未由本人确认')
    if data['uncertainties'] and not data['resolution_note']:
        raise ValueError('请先填写待核实问题的核实结果')


def build_calendar(tasks):
    calendar=Calendar()
    calendar.add('prodid','-//Campus Notice Assistant//CN')
    calendar.add('version','2.0')
    calendar.add('calscale','GREGORIAN')
    calendar.add('x-wr-calname','校园事项')
    now=datetime.now(timezone.utc)
    for task in tasks:
        data=task['data']
        eligible(data)
        event=Event()
        event.add('uid',task['id']+'@campus-notice.local')
        event.add('sequence',task['version'])
        event.add('dtstamp',now)
        event.add('last-modified',datetime.fromtimestamp(task['updated_at'],timezone.utc))
        event.add('summary',data['title'])
        event.add('status','CANCELLED' if task['status']=='cancelled' else 'CONFIRMED')
        event.add('transp','TRANSPARENT')
        if data['due_date']:
            day=date.fromisoformat(data['due_date'])
            if data['due_time']:
                start=datetime.combine(day,time.fromisoformat(data['due_time']),CST).astimezone(timezone.utc)
                event.add('dtstart',start)
                event.add('dtend',start+timedelta(minutes=15))
            else:
                event.add('dtstart',day)
                event.add('dtend',day+timedelta(days=1))
        elif data['planned_at']:
            start=datetime.fromisoformat(data['planned_at']).astimezone(timezone.utc)
            event.add('dtstart',start)
            event.add('dtend',start+timedelta(minutes=15))
        description=[data['details'],'正式期限：'+(data['deadline_text'] or data['due_date'] or '原文未明确'),
                     '时刻：'+(data['due_time'] or '未明确，不推定 23:59'),
                     '个人计划：'+(data['planned_at'] or '未设置'),
                     '提交方式：'+data['submission'],'材料：'+'、'.join(data['materials']),
                     '备注：'+data['notes'], '导出是快照。改期或取消后请手动更新/删除旧事件。']
        description += [f"依据 {e['locator']}：{e['quote']}" for e in data['evidence']]
        event.add('description','\n'.join(description))
        if data['location']:
            event.add('location',data['location'])
        if data['reminder_at'] and task['status']=='pending':
            alarm=Alarm()
            alarm.add('action','DISPLAY')
            alarm.add('description',data['title'])
            alarm.add('trigger',datetime.fromisoformat(data['reminder_at']).astimezone(timezone.utc))
            event.add_component(alarm)
        if data['due_date'] or data['planned_at']:
            calendar.add_component(event)
        if data.get('scheduled'):
            from copy import deepcopy
            slot=data['scheduled'];scheduled=deepcopy(event)
            scheduled['uid']=task['id']+'-scheduled@campus-notice.local'
            scheduled.pop('dtstart',None);scheduled.pop('dtend',None)
            # One explicit reminder produces one alarm, even when a task has
            # both an application deadline and a separate attendance interval.
            if data['due_date'] or data['planned_at']:scheduled.subcomponents=[]
            start=date.fromisoformat(slot['start_date'])
            if slot.get('start_time'):
                start=datetime.combine(start,time.fromisoformat(slot['start_time']),CST).astimezone(timezone.utc)
            scheduled.add('dtstart',start)
            if slot.get('end_date') and bool(slot.get('start_time'))==bool(slot.get('end_time')):
                end=date.fromisoformat(slot['end_date'])
                end=datetime.combine(end,time.fromisoformat(slot['end_time']),CST).astimezone(timezone.utc) if slot.get('end_time') else end+timedelta(days=1)
                scheduled.add('dtend',end)
            label='活动时间' if slot['kind']=='event' else '办理时段'
            scheduled['summary']=data['title']+' · '+label
            scheduled['description']=str(event['description'])+'\n'+label+'：'+slot['start_date']+' '+(slot.get('start_time') or '时刻未明确')+' 至 '+(slot.get('end_date') or '结束未明确')+' '+(slot.get('end_time') or '')
            calendar.add_component(scheduled)
    return calendar.to_ical()
