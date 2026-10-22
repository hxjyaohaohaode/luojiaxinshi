"""Transactional memory provenance, revisions and materialized search indexes.

SQLite remains authoritative. Editable Markdown is a versioned interchange
format, never an alternative path around ownership or optimistic concurrency.
"""
import hashlib
import json
import re
import time

from .db import dumps, ident
from .memory_policy import normalized, rows_for, save_policy, scope_key

MAX_MEMORIES = 10000
KINDS = ('preference', 'constraint', 'decision', 'fact', 'episode', 'skill', 'intention', 'summary')
REQUIRED_TABLES = {'memory_details', 'memory_revisions', 'memory_evidence', 'memory_links',
                   'memory_tombstones', 'memory_blocked_sources', 'memory_settings',
                   'memory_jobs', 'memory_action_receipts', 'memory_working', 'memory_fts',
                   'memory_import_provenance', 'memory_maintenance'}
V1_TABLES = {'memory_details','memory_revisions','memory_jobs','memory_links',
             'memory_evidence','memory_settings','memory_working'}
V2_TABLES = set(REQUIRED_TABLES)


def tokens(text):
    chunks = re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+', normalized(text))
    return ' '.join(word for part in chunks for word in (
        [part] if part.isascii() else [part[i:i+n] for n in (1, 2, 3) for i in range(len(part)-n+1)]))


def digest(value):
    return hashlib.sha256(normalized(value).encode('utf-8')).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_details(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 origin TEXT NOT NULL DEFAULT 'manual',review_status TEXT NOT NULL DEFAULT 'accepted',
 locked INTEGER NOT NULL DEFAULT 1,labels TEXT NOT NULL DEFAULT '[]',
 agent_id TEXT NOT NULL DEFAULT 'messenger',content_hash TEXT NOT NULL,
 last_used_at INTEGER,use_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS memory_revisions(
 memory_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 version INTEGER NOT NULL,snapshot TEXT NOT NULL,actor TEXT NOT NULL,created_at INTEGER NOT NULL,
 PRIMARY KEY(memory_id,version));
CREATE TABLE IF NOT EXISTS memory_evidence(
 memory_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,source_version INTEGER NOT NULL DEFAULT 1,
 quote TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,
 PRIMARY KEY(memory_id,source_kind,source_id));
CREATE INDEX IF NOT EXISTS memory_evidence_source ON memory_evidence(source_kind,source_id);
CREATE TABLE IF NOT EXISTS memory_links(
 child_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 parent_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 relation TEXT NOT NULL CHECK(relation IN ('derived_from','related_to','supersedes')),
 parent_version INTEGER NOT NULL,PRIMARY KEY(child_id,parent_id,relation),
 CHECK(child_id<>parent_id));
CREATE INDEX IF NOT EXISTS memory_links_parent ON memory_links(parent_id,relation);
CREATE TABLE IF NOT EXISTS memory_tombstones(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 content_hash TEXT NOT NULL,scope_key TEXT NOT NULL,created_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,content_hash,scope_key));
CREATE TABLE IF NOT EXISTS memory_blocked_sources(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,created_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,source_kind,source_id));
CREATE TABLE IF NOT EXISTS memory_settings(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 mode TEXT NOT NULL DEFAULT 'auto' CHECK(mode IN ('auto','review','manual','off')),
 auto_organize INTEGER NOT NULL DEFAULT 1,learn_tasks INTEGER NOT NULL DEFAULT 1,
 version INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memory_jobs(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 source_kind TEXT NOT NULL,source_id TEXT NOT NULL,source_version INTEGER NOT NULL DEFAULT 1,
 state TEXT NOT NULL DEFAULT 'queued',error_code TEXT NOT NULL DEFAULT '',
 created_at INTEGER NOT NULL,finished_at INTEGER);
CREATE INDEX IF NOT EXISTS memory_jobs_queue ON memory_jobs(state,created_at);
CREATE TABLE IF NOT EXISTS memory_action_receipts(
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 action_hash TEXT NOT NULL,result TEXT NOT NULL,created_at INTEGER NOT NULL,
 PRIMARY KEY(message_id,action_hash));
CREATE TABLE IF NOT EXISTS memory_working(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 content TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,
 locked INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memory_import_provenance(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_maintenance(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 dirty INTEGER NOT NULL DEFAULT 1,updated_at INTEGER NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
 memory_id UNINDEXED,user_id UNINDEXED,words,tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS memory_index_insert AFTER INSERT ON personal_memories BEGIN
 INSERT INTO memory_fts(memory_id,user_id,words) VALUES(NEW.id,NEW.user_id,memory_tokens(NEW.content));
 INSERT INTO memory_details(memory_id,content_hash) VALUES(NEW.id,memory_digest(NEW.content));
END;
CREATE TRIGGER IF NOT EXISTS memory_index_update AFTER UPDATE OF content ON personal_memories BEGIN
 DELETE FROM memory_fts WHERE memory_id=OLD.id;
 INSERT INTO memory_fts(memory_id,user_id,words) VALUES(NEW.id,NEW.user_id,memory_tokens(NEW.content));
 UPDATE memory_details SET content_hash=memory_digest(NEW.content) WHERE memory_id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_index_delete AFTER DELETE ON personal_memories BEGIN
 DELETE FROM memory_fts WHERE memory_id=OLD.id;
END;
DROP TRIGGER IF EXISTS memory_forget;
CREATE TRIGGER memory_forget BEFORE DELETE ON personal_memories BEGIN
 INSERT OR IGNORE INTO memory_tombstones(user_id,content_hash,scope_key,created_at)
 SELECT OLD.user_id,memory_digest(OLD.content),
        json_array(OLD.scope,coalesce(OLD.project_id,''),OLD.topic),unixepoch()
 WHERE EXISTS(SELECT 1 FROM users WHERE id=OLD.user_id)
 AND NOT EXISTS(SELECT 1 FROM memory_links WHERE child_id=OLD.id AND relation='derived_from');
 INSERT OR IGNORE INTO memory_blocked_sources
 SELECT OLD.user_id,source_kind,source_id,unixepoch() FROM memory_evidence
 WHERE memory_id=OLD.id AND source_kind<>'message' AND EXISTS(SELECT 1 FROM users WHERE id=OLD.user_id);
 DELETE FROM personal_memories WHERE id IN (
  WITH RECURSIVE descendants(id) AS (
   SELECT child_id FROM memory_links WHERE parent_id=OLD.id AND relation='derived_from'
   UNION SELECT l.child_id FROM memory_links l JOIN descendants d ON l.parent_id=d.id
   WHERE l.relation='derived_from'
  ) SELECT id FROM descendants);
END;
CREATE TRIGGER IF NOT EXISTS memory_maintenance_insert AFTER INSERT ON personal_memories BEGIN
 INSERT INTO memory_maintenance VALUES(NEW.user_id,1,unixepoch()) ON CONFLICT(user_id) DO UPDATE SET dirty=1;
END;
CREATE TRIGGER IF NOT EXISTS memory_maintenance_update AFTER UPDATE OF version ON personal_memories BEGIN
 INSERT INTO memory_maintenance VALUES(NEW.user_id,1,unixepoch()) ON CONFLICT(user_id) DO UPDATE SET dirty=1;
END;
CREATE TRIGGER IF NOT EXISTS memory_maintenance_delete AFTER DELETE ON personal_memories BEGIN
 UPDATE memory_maintenance SET dirty=1 WHERE user_id=OLD.user_id;
END;
CREATE TRIGGER IF NOT EXISTS memory_invalidate BEFORE UPDATE OF content,active,scope,project_id,topic ON personal_memories
 WHEN OLD.content<>NEW.content OR OLD.active<>NEW.active OR OLD.scope<>NEW.scope
 OR OLD.project_id IS NOT NEW.project_id OR OLD.topic<>NEW.topic BEGIN
 DELETE FROM personal_memories WHERE id IN (
  WITH RECURSIVE descendants(id) AS (
   SELECT child_id FROM memory_links WHERE parent_id=OLD.id AND relation='derived_from'
   UNION SELECT l.child_id FROM memory_links l JOIN descendants d ON l.parent_id=d.id
   WHERE l.relation='derived_from'
  ) SELECT id FROM descendants);
END;
CREATE TRIGGER IF NOT EXISTS memory_source_message_delete BEFORE DELETE ON conversation_messages BEGIN
 DELETE FROM personal_memories WHERE id IN
 (SELECT memory_id FROM memory_evidence WHERE source_kind='message' AND source_id=OLD.id);
 DELETE FROM memory_jobs WHERE source_kind='message' AND source_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_source_task_delete BEFORE DELETE ON tasks BEGIN
 DELETE FROM personal_memories WHERE id IN
 (SELECT memory_id FROM memory_evidence WHERE source_kind='task' AND source_id=OLD.id);
 DELETE FROM memory_jobs WHERE source_kind='task' AND source_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_message_queue AFTER INSERT ON conversation_messages
 WHEN NEW.role='user' AND NEW.status='complete' BEGIN
 INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
 SELECT 'message:'||NEW.id,user_id,'message',NEW.id,NEW.created_at
 FROM conversations WHERE id=NEW.conversation_id;
END;
CREATE TRIGGER IF NOT EXISTS memory_task_queue AFTER INSERT ON tasks BEGIN
 INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,source_version,created_at)
 VALUES('task:'||NEW.id||':'||NEW.version,NEW.user_id,'task',NEW.id,NEW.version,NEW.updated_at);
END;
CREATE TRIGGER IF NOT EXISTS memory_task_update_queue AFTER UPDATE ON tasks
 WHEN NEW.version<>OLD.version BEGIN
 INSERT OR IGNORE INTO memory_jobs(id,user_id,source_kind,source_id,source_version,created_at)
 VALUES('task:'||NEW.id||':'||NEW.version,NEW.user_id,'task',NEW.id,NEW.version,NEW.updated_at);
END;
INSERT OR IGNORE INTO memory_details(memory_id,content_hash)
 SELECT id,memory_digest(content) FROM personal_memories;
INSERT INTO memory_fts(memory_id,user_id,words)
 SELECT m.id,m.user_id,memory_tokens(m.content) FROM personal_memories m
 WHERE NOT EXISTS(SELECT 1 FROM memory_fts f WHERE f.memory_id=m.id);
INSERT OR IGNORE INTO memory_maintenance SELECT DISTINCT user_id,1,unixepoch() FROM personal_memories;
INSERT OR IGNORE INTO meta VALUES('memory_engine_schema_version','2');
UPDATE meta SET value='2' WHERE key='memory_engine_schema_version';
"""


def settings_for(conn, uid):
    row = conn.execute('SELECT mode,auto_organize,learn_tasks,version FROM memory_settings WHERE user_id=?', (uid,)).fetchone()
    return dict(row) if row else {'mode': 'auto', 'auto_organize': 1, 'learn_tasks': 1, 'version': 0}


def export_archive(conn, uid):
    """Portable records plus provenance. A private SQLite backup preserves runtime state."""
    items = decorate(conn, rows_for(conn, uid))
    by_id = {item['id']: item for item in items}
    for item in items:
        item.update(evidence=[], revisions=[], links=[])
    for table, key in (('memory_evidence', 'evidence'), ('memory_revisions', 'revisions'), ('memory_links', 'links')):
        field = 'child_id' if key == 'links' else 'memory_id'
        for row in conn.execute(f'''SELECT x.* FROM {table} x JOIN personal_memories m
                ON m.id=x.{field} WHERE m.user_id=?''', (uid,)):
            data = dict(row)
            if key == 'revisions':
                data['snapshot'] = json.loads(data['snapshot'])
            by_id[row[field]][key].append(data)
    for row in conn.execute('''SELECT p.* FROM memory_import_provenance p
            JOIN personal_memories m ON m.id=p.memory_id WHERE m.user_id=?''', (uid,)):
        by_id[row['memory_id']]['imported_provenance'] = json.loads(row['payload'])
    return {'format': 'campus-memory-v1', 'memories': items,
            'projects': [dict(row) for row in conn.execute('SELECT * FROM memory_projects WHERE user_id=?', (uid,))],
            'settings': settings_for(conn, uid), 'exported_at': int(time.time()),
            'note': 'JSON 为可迁移记忆档案。导入的历史来源仅供核对，不恢复其他账号的权限或实时关联；完整运行状态请使用数据库备份。'}


def decorate(conn, items):
    if not items:
        return []
    ids = [item['id'] for item in items]
    marks = ','.join('?' for _ in ids)
    metadata = {r['memory_id']: dict(r) for r in conn.execute(
        f'SELECT * FROM memory_details WHERE memory_id IN ({marks})', ids)}
    result = []
    for item in items:
        extra = metadata.get(item['id'], {})
        extra.pop('content_hash', None)
        extra.pop('memory_id', None)
        entry = {**item, **extra, 'labels': json.loads(extra.get('labels', '[]'))}
        if entry.get('review_status') == 'pending':
            entry['state'] = 'pending'
        result.append(entry)
    from .memory_lifecycle import semantics
    result = semantics(conn, result)
    for entry in result:
        if entry.get('state') == 'active' and entry.get('status') in ('cooling','needs_review','archived'):
            entry['state'] = entry['status']
    return result


def record_revision(conn, mid, actor='user'):
    row = conn.execute('''SELECT m.*,COALESCE(p.semantic_key,'') semantic_key,
        p.valid_from,p.expires_at FROM personal_memories m
        LEFT JOIN memory_policies p ON p.memory_id=m.id WHERE m.id=?''', (mid,)).fetchone()
    if row is None:
        return
    extra = conn.execute('SELECT origin,locked,review_status,labels FROM memory_details WHERE memory_id=?', (mid,)).fetchone()
    value = {**dict(row), **(dict(extra) if extra else {})}
    value['labels'] = json.loads(value.get('labels', '[]'))
    value['evidence'] = [dict(r) for r in conn.execute('SELECT * FROM memory_evidence WHERE memory_id=?',(mid,))]
    value['links'] = [dict(r) for r in conn.execute('SELECT * FROM memory_links WHERE child_id=?',(mid,))]
    life = conn.execute('SELECT * FROM memory_semantics WHERE memory_id=?',(mid,)).fetchone()
    value['lifecycle'] = dict(life) if life else None
    conn.execute('''INSERT INTO memory_revisions VALUES(?,?,?,?,?) ON CONFLICT(memory_id,version)
        DO UPDATE SET snapshot=excluded.snapshot,actor=excluded.actor''',
        (mid, row['version'], dumps(value), actor, int(time.time())))


def all_revisions_initialized(conn):
    for row in conn.execute('SELECT id FROM personal_memories WHERE id NOT IN (SELECT memory_id FROM memory_revisions)'):
        record_revision(conn, row['id'], 'migration')


def tombstoned(conn, uid, value):
    return bool(conn.execute('SELECT 1 FROM memory_tombstones WHERE user_id=? AND content_hash=? AND scope_key=?',
        (uid, digest(value['content']), dumps(scope_key(value)))).fetchone())


def forget_memory(conn, uid, item):
    """Explicit user forgetting also blocks regeneration of derived overviews."""
    from .memory_lifecycle import before_forget
    before_forget(conn, uid, item)
    conn.execute('INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?,?)',
        (uid, digest(item['content']), dumps(scope_key(item)), int(time.time())))
    conn.execute('DELETE FROM personal_memories WHERE id=? AND user_id=?', (item['id'],uid))


def insert_memory(conn, uid, value, *, origin='manual', review='accepted', locked=True,
                  evidence=None, parents=None, labels=None):
    """Called only with a server-derived owner and previously validated scope."""
    if origin != 'manual' and tombstoned(conn, uid, value):
        return None
    if origin != 'manual':
        from .memory_lifecycle import blocked_fragment
        if any(item['source_kind']=='message' and blocked_fragment(conn,uid,item['source_id'],item.get('quote','')) for item in evidence or []):
            return None
    if origin != 'manual' and any(conn.execute('''SELECT 1 FROM memory_blocked_sources
            WHERE user_id=? AND source_kind=? AND source_id=?''',
            (uid, item['source_kind'], item['source_id'])).fetchone() for item in evidence or []):
        return None
    if conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?', (uid,)).fetchone()[0] >= MAX_MEMORIES:
        raise ValueError('记忆数量达到上限，请导出或整理后再保存')
    key, now = ident(), int(time.time())
    conn.execute('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)',
        (key, uid, value['scope'], value.get('project_id'), value.get('topic', ''),
         value['kind'], value['content'], value.get('source_conversation_id'),
         int(value.get('active', True) and review == 'accepted'), int(value.get('pinned', False)), now, now))
    conn.execute('UPDATE memory_details SET origin=?,review_status=?,locked=?,labels=? WHERE memory_id=?',
        (origin, review, int(locked), dumps(labels or []), key))
    save_policy(conn, key, value)
    for item in evidence or []:
        conn.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?)',
            (key, item['source_kind'], item['source_id'], item.get('source_version', 1), item.get('quote', ''), now))
    for parent in parents or []:
        conn.execute("INSERT INTO memory_links VALUES(?,?,'derived_from',?)", (key, parent['id'], parent['version']))
    from .memory_lifecycle import set_semantics,event
    set_semantics(conn, key, admission='manual' if origin=='manual' else 'task' if origin=='task' else 'derived' if parents else 'explicit')
    if origin=='resource':conn.execute('UPDATE memory_semantics SET review_after=NULL WHERE memory_id=?',(key,))
    event(conn,uid,key,'created','来源：'+origin+'；'+('待本人核对' if review=='pending' else '已保存'))
    record_revision(conn, key, origin)
    return key


def invalidate_dependents(conn, mid):
    conn.execute('''DELETE FROM personal_memories WHERE id IN (
        WITH RECURSIVE descendants(id) AS (
          SELECT child_id FROM memory_links WHERE parent_id=? AND relation='derived_from'
          UNION SELECT l.child_id FROM memory_links l JOIN descendants d ON l.parent_id=d.id
          WHERE l.relation='derived_from') SELECT id FROM descendants)''', (mid,))


def usable_derived(conn, items, now=None):
    """A summary never outlives a source's expiry, conflict or manual revocation."""
    from .memory_policy import temporal_state
    by_id = {item['id']: item for item in items}
    ids=dumps(list(by_id))
    invalid = {row['memory_id'] for row in conn.execute('''SELECT e.memory_id
        FROM json_each(?) selected CROSS JOIN memory_evidence e ON e.memory_id=selected.value CROSS JOIN personal_memories m ON m.id=e.memory_id
        LEFT JOIN tasks t ON t.id=e.source_id AND t.user_id=m.user_id
        WHERE m.user_id=? AND e.source_kind='task'
        AND (t.id IS NULL OR t.version<>e.source_version)''',
        (ids,items[0]['user_id']))} if items else set()
    links = list(conn.execute('''SELECT l.* FROM json_each(?) selected CROSS JOIN memory_links l ON l.child_id=selected.value CROSS JOIN personal_memories m
        ON m.id=l.child_id WHERE m.user_id=? AND l.relation='derived_from' ''',
        (ids,items[0]['user_id']))) if items else []
    if items:
        at=int(time.time()) if now is None else now
        invalid.update(row['memory_id'] for row in conn.execute('''SELECT s.memory_id FROM json_each(?) selected CROSS JOIN memory_semantics s ON s.memory_id=selected.value
            CROSS JOIN personal_memories m ON m.id=s.memory_id CROSS JOIN memory_details d ON d.memory_id=m.id
            WHERE m.user_id=? AND (s.status<>'active' OR (s.review_after<=? AND d.locked=0))''',(ids,items[0]['user_id'],at)))
    from .memory_reliability import source_current
    if items:
        from .memory_resources import invalid_resources
        invalid.update(invalid_resources(conn,items[0]['user_id'],by_id))
    source_cache={}
    for _ in range(len(links)+1):
        changed = False
        for link in links:
            parent = by_id.get(link['parent_id'])
            if (not parent or parent['id'] in invalid or not source_current(conn,parent,link['parent_version'],source_cache)
                    or temporal_state(parent, now) != 'active'):
                if link['child_id'] not in invalid:
                    invalid.add(link['child_id'])
                    changed = True
        if not changed:
            break
    return [item for item in items if item['id'] not in invalid], invalid


from .memory_lifecycle import SCHEMA as LIFECYCLE_SCHEMA, TABLES as LIFECYCLE_TABLES
REQUIRED_TABLES |= LIFECYCLE_TABLES
SCHEMA += LIFECYCLE_SCHEMA
from .memory_reflection_schema import SCHEMA as REFLECTION_SCHEMA, TABLES as REFLECTION_TABLES
REQUIRED_TABLES |= REFLECTION_TABLES
SCHEMA += REFLECTION_SCHEMA
V3_TABLES = set(REQUIRED_TABLES)
from .memory_reliability_schema import SCHEMA as RELIABILITY_SCHEMA, TABLES as RELIABILITY_TABLES
REQUIRED_TABLES |= RELIABILITY_TABLES
SCHEMA += RELIABILITY_SCHEMA
V4_TABLES=set(REQUIRED_TABLES)
from .memory_autonomy_schema import SCHEMA as AUTONOMY_SCHEMA,TABLES as AUTONOMY_TABLES
REQUIRED_TABLES |= AUTONOMY_TABLES
SCHEMA += AUTONOMY_SCHEMA
