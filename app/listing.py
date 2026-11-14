"""Bounded owner-scoped lists, indexed text search and leased keyset cursors.

The legacy array endpoints remain available to exports/internal workflows.
Interactive pages use these bounded projections; a changed snapshot requires
an explicit refresh, rather than silently losing or duplicating records.
"""
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time

from fastapi import HTTPException

from .db import dumps

TABLES={'notice_search_documents','notice_search_fts'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_search_documents(
 id INTEGER PRIMARY KEY, document_key TEXT UNIQUE NOT NULL,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, label TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS notice_search_owner ON notice_search_documents(user_id,notice_id);
CREATE INDEX IF NOT EXISTS notice_search_notice_kind ON notice_search_documents(notice_id,kind,id);
CREATE INDEX IF NOT EXISTS notices_page_owner ON notices(user_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS tasks_page_owner ON tasks(user_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS ingest_updates_notice_state ON notice_ingest_updates(notice_id,state);
CREATE INDEX IF NOT EXISTS receipts_owner_notice ON notice_ingest_receipts(user_id,notice_id);
CREATE VIRTUAL TABLE IF NOT EXISTS notice_search_fts USING fts5(text,content='notice_search_documents',content_rowid='id',tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS notice_search_fts_insert AFTER INSERT ON notice_search_documents BEGIN
 INSERT INTO notice_search_fts(rowid,text) VALUES(NEW.id,NEW.text); END;
CREATE TRIGGER IF NOT EXISTS notice_search_fts_delete AFTER DELETE ON notice_search_documents BEGIN
 INSERT INTO notice_search_fts(notice_search_fts,rowid,text) VALUES('delete',OLD.id,OLD.text); END;
CREATE TRIGGER IF NOT EXISTS notice_search_fts_update AFTER UPDATE ON notice_search_documents BEGIN
 INSERT INTO notice_search_fts(notice_search_fts,rowid,text) VALUES('delete',OLD.id,OLD.text);
 INSERT INTO notice_search_fts(rowid,text) VALUES(NEW.id,NEW.text); END;
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='bounded_lists_version'").fetchone()
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('列表索引版本不兼容或必要索引表缺失，未改写')
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta VALUES('listing_cursor_key',?)", (secrets.token_hex(32),))
    definitions = {
        'notices': ("'h:'||n.id", 'n.user_id', 'n.id', "'header'", "'标题与来源'",
                    "n.title||char(10)||n.source_label", 'notices n', 'n.id', ''),
        'sources': ("'s:'||s.id", 'n.user_id', 's.notice_id', "'source'", 's.name',
                    "s.name||char(10)||COALESCE((SELECT group_concat(COALESCE(json_extract(CASE WHEN j.type='object' THEN j.value ELSE '{}' END,'$.text'),''),char(10)) FROM json_each(CASE WHEN json_valid(s.sections) THEN s.sections ELSE '[]' END) j),'')",
                    'sources s JOIN notices n ON n.id=s.notice_id', 's.id', ' AND s.active=1'),
        'tasks': ("'t:'||t.id", 't.user_id', 't.notice_id', "'task'", "'办理事项'",
                  "COALESCE(json_extract(t.data,'$.title'),'')||char(10)||COALESCE(json_extract(t.data,'$.details'),'')||char(10)||COALESCE(json_extract(t.data,'$.materials'),'')||char(10)||COALESCE(json_extract(t.data,'$.submission'),'')",
                  'tasks t', 't.id', ' AND json_valid(t.data)'),
        'notice_ingest_receipts': ("'r:'||r.id", 'r.user_id', 'r.notice_id', "'origin'", "'来源'", 'r.source_label',
                                  'notice_ingest_receipts r JOIN notices n ON n.id=r.notice_id AND n.user_id=r.user_id', 'r.id', ''),
    }
    statements = []
    for table, values in definitions.items():
        key, owner, nid, kind, label, content, source, identity, condition = values
        projection = ','.join((key, owner, nid, kind, label, content))
        insert = "INSERT INTO notice_search_documents(document_key,user_id,notice_id,kind,label,text) SELECT " + projection + ' FROM ' + source
        upsert = ' ON CONFLICT(document_key) DO UPDATE SET user_id=excluded.user_id,notice_id=excluded.notice_id,label=excluded.label,text=excluded.text;'
        prefix = {'notices': 'h:', 'sources': 's:', 'tasks': 't:', 'notice_ingest_receipts': 'r:'}[table]
        for action, ref in [('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')]:
            body = f"DELETE FROM notice_search_documents WHERE document_key='{prefix}'||{ref}.id;"
            if action != 'DELETE':
                body += insert + f' WHERE {identity}={ref}.id' + condition + upsert
            # Only fields relevant to the index trigger rebuilds. Status-only
            # workflow writes do not reindex thousands of text characters.
            update = {'notices': 'title,source_label', 'sources': 'name,sections,active', 'tasks': 'data',
                      'notice_ingest_receipts': 'source_label'}[table]
            event = 'UPDATE OF ' + update if action == 'UPDATE' else action
            statements.append(f'CREATE TRIGGER IF NOT EXISTS list_index_{table}_{action.lower()} AFTER {event} ON {table} BEGIN {body} END;')
        if not version:
            conn.execute(insert + ' WHERE 1=1' + condition + upsert)
    conn.commit()
    conn.executescript('BEGIN IMMEDIATE;' + '\n'.join(statements) + "INSERT OR IGNORE INTO meta VALUES('bounded_lists_version','1');COMMIT;")


def _revision(conn, uid):
    return {row['domain']: row['revision'] for row in conn.execute(
        "SELECT domain,revision FROM workspace_revisions WHERE subject=? AND domain IN ('notices','tasks','account')",
        ('user:' + uid,))}


def _secret(conn):
    return bytes.fromhex(conn.execute("SELECT value FROM meta WHERE key='listing_cursor_key'").fetchone()[0])


def _encode(conn, value):
    raw = base64.urlsafe_b64encode(dumps(value).encode()).decode().rstrip('=')
    return raw + '.' + hmac.new(_secret(conn), raw.encode(), hashlib.sha256).hexdigest()


def _decode(conn, cursor, uid, kind, filters, revision):
    try:
        raw, signature = cursor.split('.')
        if not hmac.compare_digest(signature, hmac.new(_secret(conn), raw.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
        if value['owner'] != uid or value['kind'] != kind or value['filters'] != filters:
            raise ValueError()
        if value['expires'] < time.time() or value['revision'] != revision:
            raise HTTPException(409, {'code': 'list_changed', 'message': '列表已有更新，请重新加载；原筛选与当前选择可保留。'})
        return value
    except HTTPException:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(422, '分页游标无效或不属于当前账号与筛选') from None


def _query(query):
    value = query.strip()
    if len(value) > 200:
        raise HTTPException(422, '搜索内容请控制在 200 字以内')
    terms = list(dict.fromkeys(value.casefold().split()))
    if len(terms) > 20:
        raise HTTPException(422, '一次最多搜索 20 个关键词')
    return value, terms


def _search(terms, uid, alias='n'):
    conditions, args = [], []
    for term in terms:
        if len(term) >= 3:
            conditions.append(f"{alias}.id IN (SELECT d.notice_id FROM notice_search_fts f JOIN notice_search_documents d ON d.id=f.rowid WHERE notice_search_fts MATCH ? AND d.user_id=?)")
            args.extend(['"' + term.replace('"', '""') + '"', uid])
        else:
            # Trigram indexes cannot represent one/two-character Chinese terms.
            # A bounded SQL fallback preserves substring semantics and ownership.
            conditions.append(f"{alias}.id IN (SELECT d.notice_id FROM notice_search_documents d WHERE d.user_id=? AND instr(lower(d.text),?)>0)")
            args.extend([uid, term])
    return conditions, args


NOTICE_COLUMNS = """n.id,n.title,n.source_label,n.published_at,n.status,n.version,n.created_at,n.updated_at,n.error,
 COALESCE(d.disposition,'inbox') AS disposition,
 (SELECT COUNT(*) FROM tasks t WHERE t.notice_id=n.id) AS task_count,
 CASE WHEN json_valid(n.draft) THEN json_extract(n.draft,'$.applicability') END AS applicability,
 (SELECT COUNT(*) FROM notice_ingest_updates u WHERE u.notice_id=n.id AND u.state='pending') AS pending_intake_updates,
 (SELECT COUNT(*) FROM sources s WHERE s.notice_id=n.id AND s.active=1 AND s.status IN ('review','failed')) AS source_review_count,
 (SELECT substr(x.text,length(x.label)+2,180) FROM notice_search_documents x WHERE x.notice_id=n.id AND x.kind='source' ORDER BY x.id LIMIT 1) AS source_excerpt"""


def notice_page(conn, uid, *, limit=50, cursor='', q='', status='', disposition='', source='',
                intent='',relevance='',from_day='',to_day='',sort='collected',ids=''):
    from .list_filters import selected_ids, valid_day, cached_order, ordered_page, filter_notices
    if not conn.in_transaction:
        conn.execute('BEGIN')
    q, terms = _query(q)
    if status == 'all': status = ''
    if status in {'inbox','reference','closed','not_applicable'}:
        disposition,status = status,''
    if status and status not in {'received', 'processing', 'draft', 'confirmed', 'failed'}:
        raise HTTPException(422, '通知状态筛选无效')
    if disposition and disposition not in {'inbox', 'reference', 'closed', 'not_applicable'}:
        raise HTTPException(422, '收件处理筛选无效')
    valid_day(from_day); valid_day(to_day); selected = selected_ids(ids)
    if from_day and to_day and from_day > to_day:
        raise HTTPException(422,'开始日期不能晚于结束日期')
    filters = {'q': q, 'status': status, 'disposition': disposition, 'source': source,
               'intent':intent,'relevance':relevance,'from':from_day,'to':to_day,'sort':sort,'ids':ids}
    revision = _revision(conn, uid)
    advanced = intent not in {'','all'} or relevance not in {'','all'} or sort not in {'collected','newest'}
    if advanced: revision['clock'] = int(time.time()) // 60
    previous = _decode(conn, cursor, uid, 'notices', filters, revision) if cursor else None
    clauses, args = ['n.user_id=?'], [uid]
    if status:
        clauses.append("n.status=? AND COALESCE(d.disposition,'inbox')='inbox'"); args.append(status)
    if disposition:
        clauses.append("COALESCE(d.disposition,'inbox')=?"); args.append(disposition)
    if source:
        clauses.append("(COALESCE(NULLIF(trim(n.source_label),''),'个人提交')=? OR EXISTS(SELECT 1 FROM notice_ingest_receipts r WHERE r.notice_id=n.id AND r.user_id=n.user_id AND COALESCE(NULLIF(trim(r.source_label),''),'个人提交')=?))")
        args.extend([source, source])
    if from_day:
        clauses.append("date(n.created_at,'unixepoch','+8 hours')>=?"); args.append(from_day)
    if to_day:
        clauses.append("date(n.created_at,'unixepoch','+8 hours')<=?"); args.append(to_day)
    if selected is not None:
        clauses.append('n.id IN (SELECT value FROM json_each(?))'); args.append(dumps(selected))
    conditions, search_args = _search(terms, uid)
    clauses.extend(conditions); args.extend(search_args)
    base = ' FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id WHERE ' + ' AND '.join(clauses)
    total = conn.execute('SELECT COUNT(*)' + base, args).fetchone()[0]
    if advanced:
        def compute():
            from .notice_queue import annotate
            # This path is for semantic filters. Indexed raw filters narrow the
            # set first; the revision cache avoids rereading stable projections.
            columns = NOTICE_COLUMNS.split(',\n (SELECT substr')[0]
            summaries = [dict(row) for row in conn.execute('SELECT ' + columns + base,args)]
            annotate(conn,uid,summaries)
            return [row['id'] for row in filter_notices(summaries,intent=intent,relevance=relevance,sort=sort)]
        order = cached_order(conn,uid,'notices',revision,filters,compute)
        chosen,more = ordered_page(order,previous,limit)
        rows = [dict(row) for row in conn.execute('SELECT '+NOTICE_COLUMNS+base+' AND n.id IN (SELECT value FROM json_each(?))',[*args,dumps(chosen)])]
        positions = {value:index for index,value in enumerate(chosen)}
        rows.sort(key=lambda row:positions[row['id']]); total = len(order)
    position = ''
    page_args = list(args)
    if previous:
        position = ' AND (n.created_at<? OR (n.created_at=? AND n.id<?))'
        page_args.extend([previous['at'], previous['at'], previous['id']])
    if not advanced:
        rows = [dict(row) for row in conn.execute('SELECT ' + NOTICE_COLUMNS + base + position + ' ORDER BY n.created_at DESC,n.id DESC LIMIT ?', [*page_args, limit + 1])]
        more, rows = len(rows) > limit, rows[:limit]
    ids = dumps([row['id'] for row in rows])
    labels = {}
    for row in conn.execute('SELECT notice_id,source_label FROM notice_ingest_receipts WHERE user_id=? AND notice_id IN (SELECT value FROM json_each(?)) ORDER BY created_at,rowid', (uid, ids)):
        label = row['source_label'].strip() or '个人提交'
        group = labels.setdefault(row['notice_id'], [])
        if label not in group:
            group.append(label)
    for row in rows:
        row['origin_labels'] = list(dict.fromkeys([row['source_label'].strip() or '个人提交', *labels.get(row['id'], [])]))
        from .campus_policy import notice_publication_context
        row['publication_context']=notice_publication_context(conn,row['id'])
        if terms:
            documents = conn.execute('SELECT kind,label,text FROM notice_search_documents WHERE notice_id=? AND user_id=? ORDER BY id', (row['id'], uid))
            for document in documents:
                text = document['text']; lowered = text.casefold()
                offsets = [lowered.find(term) for term in terms if term in lowered]
                if offsets:
                    start = max(0, min(offsets) - 35)
                    row.update(search_source=document['label'], search_snippet=('…' if start else '') + text[start:start + 180])
                    break
    if rows:
        from .notice_queue import annotate
        from .notice_matters import annotate as annotate_matters
        annotate(conn, uid, rows)
        annotate_matters(conn, uid, rows)
    result = _response(conn, rows, more, total, limit, uid, 'notices', filters, revision)
    result['facets'] = {'sources':[row[0] for row in conn.execute("SELECT DISTINCT COALESCE(NULLIF(trim(source_label),''),'个人提交') AS label FROM notices WHERE user_id=? UNION SELECT DISTINCT COALESCE(NULLIF(trim(source_label),''),'个人提交') FROM notice_ingest_receipts WHERE user_id=? ORDER BY 1",(uid,uid))]}
    result['order'] = sort
    return result


def _response(conn, items, more, total, limit, uid, kind, filters, revision):
    next_cursor = None
    if more and items:
        last = items[-1]
        next_cursor = _encode(conn, {'owner': uid, 'kind': kind, 'filters': filters, 'revision': revision,
                                    'at': last['created_at'], 'id': last['id'], 'expires': int(time.time()) + 3600})
    return {'items': items, 'total': total, 'next_cursor': next_cursor, 'has_more': more, 'limit': limit,
            'snapshot': hashlib.sha256(dumps(revision).encode()).hexdigest(), 'filters': filters,
            'order': 'created_at_desc_id_desc'}


def task_page(conn, uid, serialize_task, *, limit=50, cursor='', q='', status='', notice_id='', lane='', scope='',day='',ids=''):
    from .list_filters import selected_ids, valid_day, cached_order, ordered_page, task_matches
    if not conn.in_transaction:
        conn.execute('BEGIN')
    q, terms = _query(q)
    if status == 'all': status = ''
    if status and status not in {'pending', 'done', 'cancelled','followup','changes','soon','unverified','sync','blocked'}:
        raise HTTPException(422, '待办状态筛选无效')
    if scope and scope not in {'personal', 'other', 'uncertain'}:
        raise HTTPException(422, '待办范围无效')
    if lane and lane not in {'action', 'followup'}:
        raise HTTPException(422, '看板分组无效')
    valid_day(day); selected = selected_ids(ids)
    filters = {'q': q, 'status': status, 'notice_id': notice_id, 'lane': lane, 'scope': scope,'day':day,'ids':ids}
    revision = _revision(conn, uid)
    advanced = status not in {'','done','cancelled'}
    if advanced: revision['clock'] = int(time.time()) // 60
    previous = _decode(conn, cursor, uid, 'tasks', filters, revision) if cursor else None
    clauses, args = ['t.user_id=?'], [uid]
    for field, value in [('status', status if status in {'done','cancelled'} else ''), ('notice_id', notice_id)]:
        if value:
            clauses.append('t.' + field + '=?'); args.append(value)
    if scope:
        clauses.append("json_extract(t.data,'$.scope')=?"); args.append(scope)
    if lane:
        clauses.append("COALESCE(json_extract(w.data,'$.board_lane'),CASE WHEN json_extract(w.data,'$.stage') IN ('submitted','waiting','supplement','blocked') THEN 'followup' ELSE 'action' END)=?")
        args.append(lane)
    if day:
        clauses.append("(json_extract(t.data,'$.due_date')=? OR (json_extract(t.data,'$.scheduled.start_date')<=? AND COALESCE(json_extract(t.data,'$.scheduled.end_date'),json_extract(t.data,'$.scheduled.start_date'))>=?))")
        args.extend([day,day,day])
    if selected is not None:
        clauses.append('t.id IN (SELECT value FROM json_each(?))'); args.append(dumps(selected))
    for term in terms:
        clauses.append("instr(lower(json_extract(t.data,'$.title')||' '||COALESCE(json_extract(t.data,'$.materials'),'')||' '||n.title),?)>0")
        args.append(term)
    base = ' FROM tasks t JOIN notices n ON n.id=t.notice_id LEFT JOIN task_workflows w ON w.task_id=t.id WHERE ' + ' AND '.join(clauses)
    total = conn.execute('SELECT COUNT(*)' + base, args).fetchone()[0]
    from .workflow import enrich_tasks
    if advanced:
        def compute():
            records=[serialize_task(row) for row in conn.execute('SELECT t.*,n.title AS notice_title'+base+' ORDER BY t.created_at DESC,t.id DESC',args)]
            enrich_tasks(conn,records)
            return [row['id'] for row in records if task_matches(row,status)]
        order=cached_order(conn,uid,'tasks',revision,filters,compute)
        chosen,more=ordered_page(order,previous,limit)
        rows=[serialize_task(row) for row in conn.execute('SELECT t.*,n.title AS notice_title'+base+' AND t.id IN (SELECT value FROM json_each(?))', [*args,dumps(chosen)])]
        positions={value:index for index,value in enumerate(chosen)}
        rows.sort(key=lambda row:positions[row['id']]); total=len(order)
    if previous and not advanced:
        base += ' AND (t.created_at<? OR (t.created_at=? AND t.id<?))'
        args.extend([previous['at'], previous['at'], previous['id']])
    if not advanced:
        rows = [serialize_task(row) for row in conn.execute('SELECT t.*,n.title AS notice_title' + base + ' ORDER BY t.created_at DESC,t.id DESC LIMIT ?', [*args, limit + 1])]
        more, rows = len(rows) > limit, rows[:limit]
    enrich_tasks(conn, rows)
    attachments = {}
    notice_ids = dumps(list({row['notice_id'] for row in rows}))
    for row in conn.execute("""SELECT s.id,s.notice_id,s.name,s.kind,s.status,
        COALESCE(length(s.content),length(m.content)) AS size
        FROM sources s JOIN notices n ON n.id=s.notice_id
        LEFT JOIN campus_material_refs r ON r.source_id=s.id
        LEFT JOIN campus_materials m ON m.publication_id=r.publication_id AND m.version=r.version AND m.position=r.position
        WHERE n.user_id=? AND s.active=1 AND (s.content IS NOT NULL OR m.content IS NOT NULL)
          AND n.id IN (SELECT value FROM json_each(?)) ORDER BY s.created_at,s.id""",(uid,notice_ids)):
        attachments.setdefault(row['notice_id'],[]).append(dict(row))
    for row in rows:
        row['attachments']=attachments.get(row['notice_id'],[])
    return _response(conn, rows, more, total, limit, uid, 'tasks', filters, revision)
