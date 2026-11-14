"""Pure current-time flags shared by full and lightweight task views."""
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def deadline_flags(task, now=None):
    moment = (now or datetime.now(CST)).astimezone(CST)
    data = task['data'];overdue = due_soon = False
    if task['status']=='pending' and not task.get('action_excluded') and data.get('due_date') and data.get('deadline_confirmed'):
        if data.get('due_time'):
            deadline = datetime.fromisoformat(data['due_date']+'T'+data['due_time']).replace(tzinfo=CST)
            overdue, due_soon = deadline<moment, moment<=deadline<=moment+timedelta(days=7)
        else:
            day = datetime.fromisoformat(data['due_date']).date()
            overdue, due_soon = day<moment.date(), moment.date()<=day<=moment.date()+timedelta(days=7)
    return {'overdue':overdue,'due_soon':due_soon}


def followup_due(task, now=None):
    value = (task.get('workflow') or {}).get('data') or {}
    return bool(task['status']=='pending' and not task.get('action_excluded') and value.get('followup_at') and
                datetime.fromisoformat(value['followup_at']) <= (now or datetime.now(timezone.utc)))
