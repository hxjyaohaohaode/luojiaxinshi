"""Owner-scoped, model-free intake shared by manual and connected sources.

Exact content is reused across entry points. Only a stable external identity
can update an existing item; similar titles alone never merge different rounds.
"""
import hashlib
import json
import re
import time
import unicodedata

from .usage_limits import check_count, check_storage, limits_for
from fastapi import HTTPException

from .db import audit, dumps, ident
from .documents import MAX_CHARS, total_chars
from .models import safe_url

TABLES = {'notice_ingest_receipts', 'notice_ingest_updates'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_ingest_receipts(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 external_key TEXT NOT NULL, fingerprint TEXT NOT NULL, source_label TEXT NOT NULL,
 source_url TEXT NOT NULL, source_ids TEXT NOT NULL, created_at INTEGER NOT NULL,
 observed_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS notice_ingest_receipt_notice ON notice_ingest_receipts(notice_id,created_at);
CREATE INDEX IF NOT EXISTS notice_ingest_receipt_identity ON notice_ingest_receipts(user_id,external_key);
CREATE TABLE IF NOT EXISTS notice_ingest_updates(
 id TEXT PRIMARY KEY, notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 receipt_id TEXT NOT NULL REFERENCES notice_ingest_receipts(id) ON DELETE CASCADE,
 previous_source_ids TEXT NOT NULL, new_source_ids TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, reviewed_at INTEGER);
INSERT OR IGNORE INTO meta VALUES('notice_ingest_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='notice_ingest_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('通知收件记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


def sections(source):
    value = source.get('sections') or []
    return json.loads(value) if isinstance(value, str) else value


def normalized_text(source):
    value = '\n'.join(str(part.get('text', '')) for part in sections(source))
    value = unicodedata.normalize('NFKC', value).strip()
    # Strip only an unambiguous forwarding wrapper. Dates, batch, issuer and
    # added requirements remain part of the identity.
    value = re.sub(r'^(?:转发(?:学校|学院|班级|原)?通知|转发|转自)[：:]\s*', '', value, count=1)
    return re.sub(r'\s+', '', value)


def fingerprint(sources):
    parts = []
    for source in sources:
        if source['kind'] == 'text' and normalized_text(source):
            parts.append('text:' + hashlib.sha256(normalized_text(source).encode()).hexdigest())
        else:
            parts.append('file:' + source['sha256'])
    return 'v2:' + hashlib.sha256(dumps(sorted(set(parts))).encode()).hexdigest()


def infer_title(sources):
    for source in sources:
        for part in sections(source):
            line = re.sub(r'\s+', ' ', str(part.get('text', ''))).strip()
            line = re.sub(r'^(?:转发(?:学校|学院|班级|原)?通知|转发)[：:]\s*', '', line)
            if line:
                return line[:76] + ('…' if len(line) > 76 else '')
    return (sources[0].get('name') or '新收到的通知')[:160]


def personal_storage_bytes(conn, uid):
    value = conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?', (uid,)).fetchone()[0]
    value += conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?', (uid,)).fetchone()[0]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_material_versions'").fetchone():
        from .task_materials import personal_material_bytes
        value += personal_material_bytes(conn, uid)
    return value


def _distinct_round(record, title, published_at):
    for pattern in (r'(?:19|20)\d{2}', r'第[一二三四五六七八九十百\d]+(?:批|轮|期)', r'(?:春季|秋季|上学期|下学期|第一学期|第二学期)'):
        old, new = set(re.findall(pattern, record['title'])), set(re.findall(pattern, title))
        if old and new and old != new:
            return True
    return bool(record['published_at'] and published_at and record['published_at'][:4] != published_at[:4])


def _find_duplicate(conn, uid, sources, digest, title, published_at):
    for row in conn.execute('SELECT * FROM notices WHERE user_id=? AND fingerprint=? ORDER BY created_at,rowid', (uid, digest)).fetchall():
        if not _distinct_round(row, title, published_at):
            return dict(row)
    # Legacy/manual/imported records used different hash serialization. Compare
    # their actual active sources without rewriting or merging old records.
    for record in conn.execute("SELECT * FROM notices WHERE user_id=? AND fingerprint NOT LIKE 'v2:%' ORDER BY created_at,rowid", (uid,)).fetchall():
        if _distinct_round(record, title, published_at):continue
        active = [dict(s) for s in conn.execute('SELECT kind,sha256,sections FROM sources WHERE notice_id=? AND active=1', (record['id'],))]
        if active and fingerprint(active) == digest:
            return dict(record)
    return None


def ingest_notice(conn, uid, *, sources, title='', source_label='', source_url='', external_key='',
                  published_at=None, materials_complete=False, allow_duplicate=False, observed_at=None):
    """Call within a write transaction. No network, model, or outgoing message."""
    if not sources:
        raise HTTPException(422, '请提供通知正文、链接原文或附件')
    if total_chars([{**s, 'sections': sections(s)} for s in sources]) > MAX_CHARS:
        raise HTTPException(422, '通知正文与附件合计超过 10000 字，请按事项拆分；未截断')
    if sum(s['kind'] != 'text' for s in sources) > 5:
        raise HTTPException(422, '单则通知最多保留 5 份当前附件，请按事项拆分')
    title = title.strip() or infer_title(sources)
    source_url = safe_url(source_url)
    if len(title) > 160 or len(source_label) > 100 or len(external_key) > 2400:
        raise HTTPException(422, '标题、来源名称或收件标识过长')
    digest, now = fingerprint(sources), int(time.time())
    observation = float(observed_at) if observed_at is not None else time.time()
    if not 0 < observation < 100_000_000_000:
        raise HTTPException(422, '来源版本时间无效')
    key = external_key or 'manual:' + ident()
    previous = conn.execute('SELECT * FROM notice_ingest_receipts WHERE user_id=? AND external_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (uid, key)).fetchone()
    if previous and previous['fingerprint'] == digest:
        conn.execute('UPDATE notice_ingest_receipts SET observed_at=MAX(observed_at,?) WHERE id=?', (observation,previous['id']))
        return {'notice_id': previous['notice_id'], 'created': False, 'updated': False, 'duplicate': True}
    # An event may be redelivered out of order after a newer version. A receipt
    # of that old fingerprint must never roll current facts back.
    if previous and observation <= previous['observed_at']:
        return {'notice_id': previous['notice_id'], 'created': False, 'updated': False, 'duplicate': True, 'stale': True}
    changed = bool(previous)
    duplicate = None if changed or allow_duplicate else _find_duplicate(conn, uid, sources, digest, title, published_at)
    if changed:
        nid = previous['notice_id']
    elif duplicate:
        nid = duplicate['id']
    else:
        check_count(conn,uid,'notices','notices','通知')
        nid = ident()
    existing = {s['sha256']: s['id'] for s in conn.execute('SELECT id,sha256 FROM sources WHERE notice_id=?', (nid,))}
    new_sources = [s for s in sources if s['sha256'] not in existing]
    check_storage(conn,uid,sum(len(s.get('content') or b'') for s in new_sources))
    created = not changed and duplicate is None
    if created:
        conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,published_at,materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (nid, uid, title, source_label, source_url, published_at, bool(materials_complete), digest, now, now))
    source_ids = []
    for source in sources:
        sid = existing.get(source['sha256'])
        if not sid:
            sid = ident()
            conn.execute('INSERT INTO sources(id,notice_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (sid, nid, source['name'], source['kind'], source.get('content'), source['sha256'], source['status'], dumps(sections(source)), source.get('warning', ''), now))
            from .notice_intake import save_origin
            save_origin(conn, sid, source)
            existing[source['sha256']] = sid
        source_ids.append(sid)
    rid = ident()
    conn.execute('INSERT INTO notice_ingest_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (rid, uid, nid, key, digest, source_label, source_url, dumps(source_ids), now, observation))
    if changed:
        old_ids = json.loads(previous['source_ids'])
        for sid in set(old_ids) - set(source_ids):
            conn.execute('UPDATE sources SET active=0 WHERE notice_id=? AND id=?', (nid, sid))
        for sid in source_ids:
            conn.execute('UPDATE sources SET active=1 WHERE notice_id=? AND id=?', (nid, sid))
        conn.execute('INSERT INTO notice_ingest_updates(id,notice_id,receipt_id,previous_source_ids,new_source_ids,created_at) VALUES(?,?,?,?,?,?)',
                     (ident(), nid, rid, dumps(old_ids), dumps(source_ids), now))
        # Keep the previous draft and all personal task/material progress for
        # comparison. Its draft_version no longer matches, so it cannot confirm.
        conn.execute("UPDATE notices SET version=version+1,status='received',materials_complete=0,fingerprint=?,processing_token=NULL,processing_at=NULL,error=NULL,updated_at=? WHERE id=?", (digest, now, nid))
        from .notice_intake import reopen
        reopen(conn, nid)
    elif duplicate:
        # Extra provenance does not invalidate a user's reviewed action plan.
        conn.execute('UPDATE notices SET updated_at=? WHERE id=?', (now, nid))
    audit(conn, uid, nid, 'source_update' if changed else 'create_notice' if created else 'notice_source_received',
          after={'title': title, 'source_label': source_label, 'receipt_id': rid})
    return {'notice_id': nid, 'created': created, 'updated': changed, 'duplicate': bool(duplicate)}


def intake_state(conn, nid):
    receipts = []
    for row in conn.execute('SELECT id,source_label,source_url,source_ids,created_at FROM notice_ingest_receipts WHERE notice_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100', (nid,)):
        receipts.append({**dict(row), 'source_ids': json.loads(row['source_ids'])})
    updates = []
    for row in conn.execute("SELECT * FROM notice_ingest_updates WHERE notice_id=? ORDER BY created_at DESC,rowid DESC LIMIT 50", (nid,)):
        updates.append({**dict(row), 'previous_source_ids': json.loads(row['previous_source_ids']), 'new_source_ids': json.loads(row['new_source_ids'])})
    return {'receipts': receipts, 'intake_updates': updates}


def search_notices(conn, uid, query=''):
    query = query.strip()
    if len(query) > 200:
        raise HTTPException(422, '搜索内容请控制在 200 字以内')
    records = [dict(r) for r in conn.execute("""SELECT n.id,n.title,n.source_label,n.status,n.version,n.created_at,n.updated_at,n.error,
        COALESCE(d.disposition,'inbox') AS disposition,
        (SELECT COUNT(*) FROM tasks t WHERE t.notice_id=n.id) AS task_count,
        CASE WHEN n.draft IS NOT NULL AND json_valid(n.draft) THEN json_extract(n.draft,'$.applicability') END AS applicability,
        (SELECT COUNT(*) FROM notice_ingest_updates u WHERE u.notice_id=n.id AND u.state='pending') AS pending_intake_updates
        FROM notices n LEFT JOIN notice_dispositions d ON d.notice_id=n.id WHERE n.user_id=? ORDER BY n.updated_at DESC,n.rowid DESC""", (uid,))]
    from .notice_queue import annotate
    annotate(conn, uid, records)
    from .notice_matters import annotate as annotate_matters
    annotate_matters(conn, uid, records)
    if not query:
        return records
    terms = query.casefold().split()
    result = []
    chunks_by_notice = {}
    for source in conn.execute('SELECT s.notice_id,s.name,s.sections FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=? AND s.active=1', (uid,)):
        chunks_by_notice.setdefault(source['notice_id'], []).append((source['name'], '\n'.join(str(p.get('text', '')) for p in json.loads(source['sections']))))
    for task in conn.execute('SELECT notice_id,data FROM tasks WHERE user_id=?', (uid,)):
        value = json.loads(task['data'])
        chunks_by_notice.setdefault(task['notice_id'], []).append(('办理事项', ' '.join([value.get('title', ''), *value.get('materials', []), value.get('submission', '')])))
    for record in records:
        chunks = [('标题', record['title']), ('来源', record['source_label']), *chunks_by_notice.get(record['id'], [])]
        haystack = '\n'.join(text for _, text in chunks).casefold()
        if not all(term in haystack for term in terms):
            continue
        label, text = next(((label, text) for label, text in chunks if any(term in text.casefold() for term in terms)), chunks[0])
        at = min((text.casefold().find(term) for term in terms if term in text.casefold()), default=0)
        start = max(0, at - 35)
        record.update(search_source=label, search_snippet=('…' if start else '') + text[start:start + 180])
        result.append(record)
    return result
