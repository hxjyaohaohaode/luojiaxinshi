"""Server equivalents of the existing inbox/task filters.

Only ordered record identifiers are cached, never another user's page content.
Cache keys include the database, owner, committed revisions, filters and clock.
"""
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import threading
import time

from fastapi import HTTPException

CST = timezone(timedelta(hours=8))
_orders = OrderedDict()
_lock = threading.Lock()


def selected_ids(value):
    if not value:
        return None
    entries = list(dict.fromkeys(value.split(',')))
    if len(entries) > 1000 or any(not 1 <= len(x) <= 100 or not x.replace('_', '').replace('-', '').isalnum() for x in entries):
        raise HTTPException(422, '选定记录标识无效；单次最多 1000 条')
    return entries


def valid_day(value):
    if value:
        try:
            if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, '日期筛选须为有效的 YYYY-MM-DD') from None
    return value


def published(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if len(value) == 10:
            parsed = parsed.replace(tzinfo=CST)
        if parsed.tzinfo is None:
            return None
        return parsed.timestamp()
    except (TypeError, ValueError):
        return None


def notice_rank(item):
    assessment = item.get('assessment') or {}
    if item.get('recommended') is False: return 20
    if item.get('task_count') and item.get('intent') == 'verify': return 0
    if assessment.get('quality') == 'passed' and assessment.get('urgency', {}).get('state') == 'due_soon': return 1
    if (item.get('feedback') or {}).get('mode') == 'include': return 2
    if assessment.get('quality') == 'passed':
        priority = assessment.get('priority')
        if priority == 'P1': return 3
        if priority == 'P2': return 4 if assessment.get('interest_match') else 5
        if priority == 'P3': return 7
    return 6


def filter_notices(items, *, intent='', relevance='', sort='collected'):
    if intent not in {'', 'all', 'current', 'tracking', 'act', 'decide', 'verify', 'followup', 'read', 'discussion', 'irrelevant', 'closed'}:
        raise HTTPException(422, '通知意图筛选无效')
    if relevance not in {'', 'all', 'unknown', 'matches_known', 'needs_review', 'not_matching'}:
        raise HTTPException(422, '适用性筛选无效')
    if sort not in {'priority', 'published', 'collected', 'updated', 'newest', 'deadline'}:
        raise HTTPException(422, '通知排序无效')
    result = []
    for item in items:
        if intent == 'current' and (item.get('recommended') is False or item.get('intent') in {'closed', 'irrelevant'}): continue
        if intent not in {'', 'all', 'current'} and item.get('intent') != intent: continue
        if relevance == 'unknown' and item.get('applicability'): continue
        if relevance not in {'', 'all', 'unknown'} and item.get('applicability') != relevance: continue
        result.append(item)
    def key(item):
        stamp = published(item.get('published_at'))
        base = (-item.get('created_at', 0) if sort in {'collected', 'newest'} else -item.get('updated_at', 0), item['id'])
        if sort in {'published', 'priority'}:
            base = (stamp is None, -(stamp or 0), *base)
        if sort in {'priority', 'deadline'}:
            rank = notice_rank(item)
            closing = (item.get('assessment') or {}).get('urgency', {}).get('closing_at')
            base = ((rank if sort == 'priority' else 0), closing or float('inf') if rank == 1 or sort == 'deadline' else 0, *base)
        return base
    return sorted(result, key=key)


def task_matches(item, status):
    if status in {'', 'all'}: return True
    flow = item.get('workflow') or {}
    data = flow.get('data') or {}
    pending = item['status'] == 'pending' and not item.get('action_excluded')
    if status == 'pending': return pending
    if status == 'followup': return pending and (data.get('board_lane') == 'followup' or item.get('followup_due') or data.get('stage') in {'submitted','supplement','blocked','waiting'})
    if status == 'changes': return bool(item.get('pending_changes') or (item.get('change_review') or {}).get('state') == 'pending')
    if status == 'sync': return bool(item.get('needs_calendar_sync') or item.get('calendar_check_required'))
    if status == 'blocked': return pending and bool(flow.get('blocked') or data.get('stage') == 'blocked' or item.get('execution_issues'))
    if status == 'soon': return pending and bool(item.get('due_soon') or item.get('overdue'))
    if status == 'unverified':
        task = item['data']; slot = task.get('scheduled')
        return pending and task.get('scope') == 'personal' and bool(
            task.get('due_date') and not task.get('deadline_confirmed') or
            slot and not slot.get('confirmed') or
            not task.get('due_date') and not slot and data.get('execution_mode', 'submission') == 'submission')
    return item['status'] == status


def cached_order(conn, uid, kind, revision, filters, compute):
    database = next((row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main'), '')
    key = hashlib.sha256(json.dumps([database, uid, kind, revision, filters], sort_keys=True).encode()).hexdigest()
    with _lock:
        if key in _orders:
            value = _orders.pop(key); _orders[key] = value
            return list(value)
    order = compute()
    # Keep this an acceleration only: no persisted truth and bounded memory.
    if len(order) <= 20000:
        with _lock:
            _orders[key] = tuple(order)
            while len(_orders) > 4:
                _orders.popitem(last=False)
    return order


def ordered_page(order, previous, limit):
    start = 0
    if previous:
        try: start = order.index(previous['id']) + 1
        except ValueError:
            raise HTTPException(409, {'code': 'list_changed', 'message': '列表已变化，请保留筛选后重新加载。'}) from None
    return order[start:start + limit], start + limit < len(order)
