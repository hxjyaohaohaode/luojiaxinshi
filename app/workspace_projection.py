"""Complete, lightweight owner projections with separate clock refreshes.

The stable snapshot never leaves this process in full: drafts are private policy
inputs, and task evidence/material text is discarded after summary creation.
Every request authenticates first and binds a bounded, expiring cache to the
database, owner and committed revisions. Clock-only reads never reload source
text, notice drafts or full task JSON. A changed revision returns a fresh complete
light snapshot so clients cannot accidentally miss new/deleted entities.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import RLock
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .campus_policy import policy_projection
from .db import dumps
from .handling_state import current_step
from .notice_queue import annotation_inputs, annotate_inputs
from .task_timing import deadline_flags, followup_due

CST = timezone(timedelta(hours=8))
DOMAINS = ('notices', 'tasks', 'account', 'sources')
NOTICE_DYNAMIC = ('intent', 'recommended', 'assessment', 'tracking', 'publication_context')
TASK_DYNAMIC = ('overdue', 'due_soon', 'followup_due', 'handling_state')


def _json(value):
    if isinstance(value, set):return sorted(value)
    if hasattr(value, 'model_dump'):return value.model_dump()
    return dict(value)


class ProjectionCache:
    """Per-application cache; byte and owner limits also bound private residency."""
    def __init__(self, *, max_bytes=48*1024*1024, max_entries=24, ttl=300):
        self.max_bytes, self.max_entries, self.ttl = max_bytes, max_entries, ttl
        self.entries, self.bytes, self.lock = OrderedDict(), 0, RLock()

    def _drop(self, key):
        value = self.entries.pop(key, None)
        if value:self.bytes -= value['bytes']

    def _expire(self, now):
        for key, entry in list(self.entries.items()):
            if entry['expires'] <= now:self._drop(key)

    def get(self, key, revision, now):
        with self.lock:
            self._expire(now)
            entry = self.entries.get(key)
            if entry and entry['revision'] != revision:
                self._drop(key);return None
            if entry:self.entries.move_to_end(key)
            return entry['value'] if entry else None

    def put(self, key, revision, value, now):
        # Conservative multiplier covers Python's object overhead as well as
        # the encoded strings. Oversized accounts still work without retention.
        size = 3*len(json.dumps(value, ensure_ascii=False, default=_json).encode())
        with self.lock:
            self._expire(now);self._drop(key)
            if size > self.max_bytes:return
            while self.entries and (self.bytes+size > self.max_bytes or len(self.entries) >= self.max_entries):
                self._drop(next(iter(self.entries)))
            self.entries[key] = {'revision':revision, 'value':value, 'expires':now+self.ttl, 'bytes':size}
            self.bytes += size

    def forget(self, uid):
        with self.lock:
            for key in list(self.entries):
                if key[1]==uid:self._drop(key)


def stable_revision(conn, uid):
    instance = conn.execute("SELECT value FROM meta WHERE key='deployment_instance_id'").fetchone()[0]
    domains = {r['domain']:r['revision'] for r in conn.execute(
        'SELECT domain,revision FROM workspace_revisions WHERE subject=? AND domain IN (?,?,?,?)',
        ('user:'+uid, *DOMAINS))}
    # Policy-only official corrections can retain byte-identical sources. The
    # exact received version is therefore part of this owner's stable revision.
    policies = [dict(r) for r in conn.execute('''
        SELECT d.notice_id,d.publication_id,d.delivered_version AS version,
               p.valid_until,COALESCE(p.reference_only,0) AS reference_only
        FROM campus_deliveries d JOIN notices n ON n.id=d.notice_id AND n.user_id=d.user_id
        LEFT JOIN campus_publication_policy p ON p.publication_id=d.publication_id AND p.version=d.delivered_version
        WHERE d.user_id=? AND d.delivered_version>0 ORDER BY d.notice_id''', (uid,))]
    revision = hashlib.sha256(dumps(['workspace-light-v1', instance, uid, domains, policies]).encode()).hexdigest()
    return revision, {row['notice_id']:row for row in policies}


def notice_rows(conn, uid):
    # No source.sections, source.content, notice.draft or body excerpts enter the
    # entity projection. Only policy_inputs below may read a draft once/revision.
    records = [dict(r) for r in conn.execute('''
        SELECT n.id,n.title,n.source_label,n.published_at,n.status,n.version,n.created_at,n.updated_at,
          COALESCE(d.disposition,'inbox') AS disposition,
          (SELECT COUNT(*) FROM tasks t WHERE t.notice_id=n.id AND t.user_id=n.user_id) AS task_count,
          CASE WHEN n.draft IS NOT NULL AND json_valid(n.draft) THEN json_extract(n.draft,'$.applicability') END AS applicability,
          (SELECT COUNT(*) FROM notice_ingest_updates u WHERE u.notice_id=n.id AND u.state='pending') AS pending_intake_updates,
          (SELECT COUNT(*) FROM sources s WHERE s.notice_id=n.id AND s.active=1 AND s.status IN ('review','failed')) AS source_review_count
        FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id
        WHERE n.user_id=? ORDER BY n.updated_at DESC,n.rowid DESC''', (uid,))]
    labels = {}
    for row in conn.execute('''SELECT r.notice_id,r.source_label FROM notice_ingest_receipts r
        JOIN notices n ON n.id=r.notice_id AND n.user_id=r.user_id
        WHERE r.user_id=? ORDER BY r.created_at,r.rowid''', (uid,)):
        label = (row['source_label'] or '').strip() or '个人提交'
        if label not in labels.setdefault(row['notice_id'], []):labels[row['notice_id']].append(label)
    for row in records:
        primary = (row['source_label'] or '').strip() or '个人提交'
        row['origin_labels'] = labels.get(row['id'], [])
        if primary not in row['origin_labels']:row['origin_labels'].insert(0, primary)
    from .notice_matters import annotate as annotate_matters
    return annotate_matters(conn, uid, records)


def _pick(value, keys):
    return {key:value[key] for key in keys if key in value}


def _tracking(value):
    result = _pick(value, ('automatic','state','label','evaluated_at','reason'))
    for field in ('expired_actions','open_actions','unknown_actions','past_events','entry_deadlines'):
        result[field] = [_pick(item, ('index','title','at','date_only','kind','dates')) for item in value.get(field, [])]
    return result


def _notice(record, policies, now):
    result = {**record, 'projection':'light'}
    result['tracking'] = _tracking(record['tracking'])
    decision = record['assessment']
    result['assessment'] = _pick(decision, ('version','priority','label','relevance','quality','personal_actions',
        'interest_match','delivery','reasons','requires_review','urgency','recommended'))
    result['assessment']['tracking'] = result['tracking']
    result['assessment']['focus'] = {'key_time':(decision.get('focus') or {}).get('key_time'), 'summary':''}
    result['feedback'] = _pick(record.get('feedback') or {}, ('mode','version','notice_version'))
    policy = policies.get(record['id'])
    result['publication_context'] = {'publication_id':policy['publication_id'],'version':policy['version'],
        **policy_projection({'valid_until':policy['valid_until'],'reference_only':bool(policy['reference_only'])}, now)} if policy else None
    return result


def _step(value):
    # The kind/label are exact; long free text belongs in the full handling view.
    detail = value.get('detail', '')
    return {**value, 'detail':detail[:240], 'detail_truncated':len(detail)>240}


def task_summary(task):
    data = task['data'];workflow = task.get('workflow') or {};progress = workflow.get('data') or {}
    result = _pick(task, ('id','notice_id','notice_title','version','status','created_at','updated_at','exported_version',
        'needs_calendar_sync','action_excluded','execution_issues','pending_changes','schedule_issues','calendar_check_required'))
    result.update(projection='light', material_count=len(data.get('materials') or []),
                  prepared_material_count=len(progress.get('prepared_materials') or []),
                  attachment_count=len(task.get('attachments') or []))
    result['data'] = _pick(data, ('title','scope','due_date','due_time','deadline_confirmed','planned_at','reminder_at','location','origin'))
    result['data'].update(details='', materials=[], scheduled=_pick(data['scheduled'],
        ('kind','start_date','start_time','end_date','end_time','confirmed')) if data.get('scheduled') else None)
    result['workflow'] = {'version':workflow.get('version',0), 'blocked':bool(workflow.get('blocked')),
        'data':_pick(progress, ('stage','execution_mode','action_kind','participation','followup_at','next_step','board_lane','board_order','phase_label'))}
    result['workflow']['data']['next_step'] = progress.get('next_step','')[:240]
    review = task.get('change_review')
    result['change_review'] = _pick(review, ('version','state','updated_at','reviewed_at')) if review else None
    result['review_required'] = bool(review and review.get('state')=='pending')
    check = task.get('calendar_check')
    result['calendar_check'] = _pick(check, ('task_version','result','current','updated_at')) if check else None
    handling = [_step(current_step({**task, 'followup_due':due})) for due in (False, True)]
    return result, handling


def task_clock(task, handling, now):
    moment = datetime.fromtimestamp(now, CST)
    due = followup_due(task, moment)
    return {'id':task['id'],**deadline_flags(task, moment),'followup_due':due,
            'handling_state':handling[int(due)]}


def build_snapshot(conn, uid, include, list_tasks):
    notices = notice_rows(conn, uid) if 'notices' in include else []
    inputs = annotation_inputs(conn, uid, notices)
    tasks, handling = [], {}
    if 'tasks' in include:
        for task in list_tasks(conn, uid):
            item, states = task_summary(task);tasks.append(item);handling[task['id']] = states
    counts = {kind:conn.execute('SELECT COUNT(*) FROM '+kind+' WHERE user_id=?',(uid,)).fetchone()[0]
              for kind in ('notices','tasks')}
    return {'notices':notices,'inputs':inputs,'tasks':tasks,'handling':handling,'counts':counts}


def install(app, db, user, list_tasks):
    cache = ProjectionCache()
    app.state.workspace_projection_cache = cache
    database = str(db.path.resolve())

    @app.get('/api/workspace/projection')
    def workspace_projection(request:Request, include:str='notices,tasks', clock_only:bool=False,
                             revision:str='', current=Depends(user)):
        selected = tuple(sorted(set(include.split(','))))
        if not selected or any(kind not in {'notices','tasks'} for kind in selected) or len(include)>40 or len(revision)>64:
            raise HTTPException(422, '轻量投影只支持 notices、tasks；版本标识格式无效')
        uid = current['id'];now = int(time.time());clock = now//60
        with db.connect() as conn:
            conn.execute('BEGIN')
            # Authentication happened on another connection. Recheck existence
            # in this snapshot before looking up private cached policy inputs.
            if conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone() is None:
                raise HTTPException(401, '请先登录，或登录已过期')
            stable, policies = stable_revision(conn, uid)
            key = (database, uid, selected)
            value = cache.get(key, stable, now)
            sparse = bool(clock_only and revision==stable and value is not None)
            tag = '"'+hashlib.sha256(dumps([stable, selected, clock, sparse]).encode()).hexdigest()+'"'
            headers = {'ETag':tag, 'Cache-Control':'private, no-cache', 'Vary':'Cookie, X-Workspace-Owner'}
            if value is not None and request.headers.get('if-none-match')==tag:
                return Response(status_code=304, headers=headers)
            if value is None:
                value = build_snapshot(conn, uid, selected, list_tasks)
                cache.put(key, stable, value, now)
        notices = [_notice(record, policies, now) for record in annotate_inputs(deepcopy(value['notices']), value['inputs'], now=now)]
        tasks = [task_clock(task, value['handling'][task['id']], now) for task in value['tasks']]
        if sparse:
            notices = [_pick(record, ('id', *NOTICE_DYNAMIC)) for record in notices]
        else:
            tasks = [{**task, **dynamic} for task,dynamic in zip(value['tasks'], tasks)]
        return JSONResponse({'projection':'light','revision':stable,'clock':clock,'clock_only':sparse,
            'included':list(selected),'counts':value['counts'],'notices':notices,'tasks':tasks}, headers=headers)

    @app.get('/api/workspace/calendar-search')
    def calendar_search(q:str='', current=Depends(user)):
        if len(q)>500:raise HTTPException(422, '日历关键词请控制在500字以内')
        query = q.strip();needle = query.lower();uid = current['id']
        with db.connect() as conn:
            conn.execute('BEGIN')
            revision, _ = stable_revision(conn, uid)
            matches = [row['id'] for row in conn.execute('''
                SELECT id,json_extract(data,'$.title') AS title,json_extract(data,'$.location') AS location,
                       json_extract(data,'$.details') AS details
                FROM tasks WHERE user_id=? ORDER BY updated_at DESC,id''',(uid,))
                if needle in ' '.join(row[key] or '' for key in ('title','location','details')).lower()]
        return JSONResponse({'query':query,'revision':revision,'task_ids':matches},
                            headers={'Cache-Control':'private, no-cache','Vary':'Cookie, X-Workspace-Owner'})
