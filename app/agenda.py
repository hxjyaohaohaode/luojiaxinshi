"""Read personal calendar occurrences and identify confirmed timetable conflicts."""
from datetime import date, datetime, time, timedelta
import json

from .insights import CST, arrangement_occurrences, parse_time


def dated(day, clock=None):
    return datetime.combine(day, time.fromisoformat(clock) if clock else time.min, CST)


def interval(record, kind, start, end=None, *, confirmed=True, timed=True):
    return {
        'id': record['id'], 'version': record.get('version', 1), 'kind': kind,
        'title': record['data'].get('title') or '未命名事项',
        'start': start, 'end': end, 'confirmed': confirmed, 'timed': timed,
    }


def occurrences(arrangements, tasks, first, last):
    """Intervals intersect [first, last). Deadlines, plans and unknown ends stay points."""
    window_start, window_end = dated(first), dated(last)
    result = []

    def include(event):
        end = event['end']
        if event['start'] < window_end and (end > window_start if end else event['start'] >= window_start):
            result.append(event)

    for record in arrangements:
        data = record['data']
        start_day = date.fromisoformat(data['start_date'])
        duration = date.fromisoformat(data.get('end_date') or data['start_date']) - start_day
        for day in arrangement_occurrences(data, first - duration, last):
            timed = bool(data.get('start_time'))
            end = None
            if data.get('end_time'):
                end = dated(day + duration, data['end_time'])
            elif not timed:
                end = dated(day + duration + timedelta(days=1))
            include(interval(record, data.get('category', 'personal'), dated(day, data.get('start_time')), end, timed=timed))

    for task in tasks:
        data = task['data']
        if task['status'] != 'pending' or task.get('action_excluded') or data.get('scope') != 'personal':
            continue
        if data.get('due_date'):
            include(interval(task, 'deadline', dated(date.fromisoformat(data['due_date']), data.get('due_time')),
                             confirmed=bool(data.get('deadline_confirmed')), timed=bool(data.get('due_time'))))
        planned = parse_time(data.get('planned_at'))
        if planned:
            include(interval(task, 'plan', planned.astimezone(CST)))
        slot = data.get('scheduled')
        if slot and slot.get('start_date'):
            day = date.fromisoformat(slot['start_date'])
            last_day = date.fromisoformat(slot.get('end_date') or slot['start_date'])
            timed = bool(slot.get('start_time'))
            end = dated(last_day, slot['end_time']) if slot.get('end_time') else None
            if not timed:
                end = dated(last_day + timedelta(days=1))
            kind = 'notice_window' if slot.get('kind') == 'window' else 'notice_event'
            include(interval(task, kind, dated(day, slot.get('start_time')), end,
                             confirmed=bool(slot.get('confirmed')), timed=timed))
    return sorted(result, key=lambda event: (event['start'], event['id'], event['kind']))


def overlaps(events, limit=24):
    """Sweep confirmed commitments in occurrence order. Touching endpoints are compatible."""
    active, pairs = [], []
    for event in events:
        if not (event['confirmed'] and event['timed'] and event['end']) or event['kind'] in ('notice_window', 'deadline', 'plan'):
            continue
        active = [prior for prior in active if prior['end'] > event['start']]
        for prior in active:
            if prior['id'] == event['id']:
                continue
            if len(pairs) >= limit:
                return pairs, True
            pairs.append((prior, event))
        active.append(event)
    return pairs, False


def stamp(value):
    return value.isoformat(timespec='minutes') if value else None


def conflict_reminders(tasks, arrangements, now):
    horizon = now + timedelta(hours=48)
    events = occurrences(arrangements, tasks, now.date(), horizon.date() + timedelta(days=1))
    upcoming = [event for event in events if event['end'] and event['end'] > now and event['start'] < horizon]
    pairs, _ = overlaps(upcoming)
    items = []
    for first, second in pairs:
        start, end = second['start'], min(first['end'], second['end'])
        items.append({
            'kind': 'schedule_conflict', 'level': 'attention', 'title': '两项安排时间重叠',
            'text': f'{first["title"]}、{second["title"]}',
            'note': f'重叠时段 {start:%m月%d日 %H:%M}–{end:%H:%M}' if start.date() == end.date()
                    else f'重叠时段 {start:%m月%d日 %H:%M}–{end:%m月%d日 %H:%M}',
            'at': stamp(start), 'calendar_date': start.date().isoformat(),
            'revision': sorted((e['id'], stamp(e['start']), stamp(e['end']), e['title']) for e in (first, second)),
        })
    return items


def read_agenda(conn, uid, args):
    from .workflow import enrich_tasks

    first, last = date.fromisoformat(args.start_day), date.fromisoformat(args.end_day)
    arrangements = [dict(row) for row in conn.execute("""
        SELECT id,version,data FROM arrangements WHERE user_id=? AND json_extract(data,'$.start_date')<=?
        AND (coalesce(json_extract(data,'$.end_date'),json_extract(data,'$.start_date'))>=? OR
             julianday(json_extract(data,'$.repeat_until')) + julianday(json_extract(data,'$.end_date'))
               - julianday(json_extract(data,'$.start_date'))>=julianday(?))
        """, (uid, args.end_day, args.start_day, args.start_day))]
    # The extra day on either side covers stored ISO timestamps with UTC offsets.
    tasks = [dict(row) for row in conn.execute("""
        SELECT * FROM tasks WHERE user_id=? AND status='pending' AND (
          json_extract(data,'$.due_date') BETWEEN ? AND ? OR substr(json_extract(data,'$.planned_at'),1,10) BETWEEN ? AND ? OR
          (json_extract(data,'$.scheduled.start_date')<=? AND
           coalesce(json_extract(data,'$.scheduled.end_date'),json_extract(data,'$.scheduled.start_date'))>=?))
        """, (uid, args.start_day, args.end_day, (first - timedelta(days=1)).isoformat(),
              (last + timedelta(days=1)).isoformat(), args.end_day, args.start_day))]
    for row in arrangements + tasks:
        row['data'] = json.loads(row['data'])
    if tasks:
        enrich_tasks(conn, tasks)
    events = occurrences(arrangements, tasks, first, last + timedelta(days=1))
    pairs, more = overlaps(events)
    records = [
        {'id': e['id'], 'version': e['version'], 'kind': e['kind'], 'title': e['title'],
         'starts_at': stamp(e['start']), 'ends_at': stamp(e['end']), 'time_specified': e['timed'], 'confirmed': e['confirmed']}
        for e in events[args.offset:args.offset + args.limit]
    ]
    return {
        'records': records, 'total': len(events), 'offset': args.offset, 'has_more': args.offset + len(records) < len(events),
        'query_scope': {'kind': 'agenda', 'start_day': args.start_day, 'end_day': args.end_day, 'timezone': 'Asia/Shanghai'},
        'conflicts': [{'first': a['title'], 'first_id': a['id'], 'second': b['title'], 'second_id': b['id'],
                       'from': stamp(b['start']), 'until': stamp(min(a['end'], b['end'])),
                       'minutes': int((min(a['end'], b['end']) - b['start']).total_seconds() // 60)} for a, b in pairs],
        'more_conflicts': more, 'scope_note': '仅含本人已保存的安排与待办。全天或未给具体时刻不推断占用；截止和办理窗口不是持续占用。',
    }
