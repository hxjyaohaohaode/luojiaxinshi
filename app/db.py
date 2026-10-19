from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid


def ident():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES('schema_version','1');
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
 display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
 profile TEXT NOT NULL DEFAULT '{}', created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS invites(
 token_hash TEXT PRIMARY KEY, role TEXT NOT NULL, expires_at INTEGER NOT NULL,
 used_at INTEGER, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY, count INTEGER NOT NULL, reset_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS edit_caches(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 cache_key TEXT NOT NULL, payload TEXT, revision INTEGER NOT NULL DEFAULT 0,
 notice_id TEXT REFERENCES notices(id) ON DELETE CASCADE, updated_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,cache_key));
CREATE TABLE IF NOT EXISTS notices(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, source_label TEXT NOT NULL, source_url TEXT NOT NULL,
 published_at TEXT, materials_complete INTEGER NOT NULL, fingerprint TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'received',
 draft TEXT, draft_version INTEGER, error TEXT, processing_token TEXT, processing_at INTEGER,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS notices_owner ON notices(user_id, created_at);
CREATE INDEX IF NOT EXISTS notices_fingerprint ON notices(user_id,fingerprint);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 name TEXT NOT NULL, kind TEXT NOT NULL, content BLOB, sha256 TEXT NOT NULL,
 status TEXT NOT NULL, sections TEXT NOT NULL, warning TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS sources_notice ON sources(notice_id);
CREATE TABLE IF NOT EXISTS confirmations(
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 draft_version INTEGER NOT NULL, result TEXT NOT NULL,
 PRIMARY KEY(notice_id,draft_version));
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','cancelled')),
 version INTEGER NOT NULL DEFAULT 1, exported_version INTEGER,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(user_id,updated_at);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 task_id TEXT, action TEXT NOT NULL, before_json TEXT, after_json TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ai_calls(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
 created_at INTEGER NOT NULL);
"""

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS account_recovery(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, code_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 processing_token TEXT, processing_at INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations(user_id,updated_at);
CREATE TABLE IF NOT EXISTS conversation_sources(
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 name TEXT NOT NULL, kind TEXT NOT NULL, content BLOB, sha256 TEXT NOT NULL,
 status TEXT NOT NULL, sections TEXT NOT NULL, warning TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS conversation_sources_parent ON conversation_sources(conversation_id);
CREATE TABLE IF NOT EXISTS conversation_messages(
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
 error TEXT NOT NULL DEFAULT '', request_id TEXT, parent_id TEXT,
 citations TEXT NOT NULL DEFAULT '[]', model TEXT, input_tokens INTEGER, output_tokens INTEGER,
 created_at INTEGER NOT NULL, UNIQUE(conversation_id,request_id));
CREATE INDEX IF NOT EXISTS conversation_messages_parent ON conversation_messages(conversation_id,created_at);
CREATE TABLE IF NOT EXISTS conversation_promotions(
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 PRIMARY KEY(conversation_id,fingerprint));
CREATE TABLE IF NOT EXISTS source_catalog(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS source_catalog_owner ON source_catalog(user_id);
CREATE TABLE IF NOT EXISTS external_bindings(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, app_id TEXT NOT NULL,
 open_id TEXT NOT NULL, created_at INTEGER NOT NULL, last_received_at INTEGER,
 PRIMARY KEY(user_id,app_id), UNIQUE(app_id,open_id));
CREATE TABLE IF NOT EXISTS binding_codes(
 code_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 app_id TEXT NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS integration_receipts(
 receipt_key TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS arrangements(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, UNIQUE(user_id,request_id));
CREATE INDEX IF NOT EXISTS arrangements_owner ON arrangements(user_id);
-- Retain only creation identity after deletion, never deleted arrangement text.
CREATE TABLE IF NOT EXISTS arrangement_receipts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, arrangement_id TEXT NOT NULL, created_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,request_id));
INSERT OR IGNORE INTO arrangement_receipts(user_id,request_id,arrangement_id,created_at)
 SELECT user_id,request_id,id,created_at FROM arrangements;
CREATE TRIGGER IF NOT EXISTS arrangements_remember_creation AFTER INSERT ON arrangements
 BEGIN
 INSERT INTO arrangement_receipts(user_id,request_id,arrangement_id,created_at)
 VALUES(NEW.user_id,NEW.request_id,NEW.id,NEW.created_at);
 END;
INSERT OR IGNORE INTO meta VALUES('arrangement_receipt_schema_version','1');
CREATE TABLE IF NOT EXISTS conversation_ai_consents(
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
 granted_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS material_library(
 source_id TEXT PRIMARY KEY REFERENCES conversation_sources(id) ON DELETE CASCADE,
 path TEXT NOT NULL, full_sections TEXT NOT NULL DEFAULT '[]', full_chars INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reply_selection(
 parent_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS reply_grounding(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 sources TEXT NOT NULL DEFAULT '[]', report TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS reply_reactions(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 value INTEGER NOT NULL CHECK(value IN (-1,0,1)));
CREATE TABLE IF NOT EXISTS reply_shares(
 token_hash TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 title TEXT NOT NULL, body TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL);
"""

GENUI_SCHEMA = """
CREATE TABLE IF NOT EXISTS genui_preferences(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL DEFAULT 1, theme TEXT NOT NULL DEFAULT 'light',
 version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS genui_messages(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 protocol_version INTEGER NOT NULL DEFAULT 1, raw TEXT NOT NULL DEFAULT '',
 parts TEXT NOT NULL DEFAULT '[]', trusted_data TEXT NOT NULL DEFAULT '{}',
 tier INTEGER NOT NULL DEFAULT 3, validated INTEGER NOT NULL DEFAULT 0,
 snapshots TEXT NOT NULL DEFAULT '{}', snapshot_version INTEGER NOT NULL DEFAULT 0,
 ai_label TEXT NOT NULL DEFAULT 'AI 生成内容', updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS genui_interactions(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 origin_message_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
 context TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES('genui_schema_version','1');
"""

# Additive domain extension: old databases and backups acquire it on open.
WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_workflows(
 task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
 data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notice_changes(
 id TEXT PRIMARY KEY, notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 data TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','applied','dismissed')),
 version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS notice_changes_owner ON notice_changes(user_id,state,created_at);
CREATE TABLE IF NOT EXISTS calendar_checks(
 task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
 task_version INTEGER NOT NULL, device TEXT NOT NULL, result TEXT NOT NULL,
 note TEXT NOT NULL, checked_at INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('workflow_schema_version','2');
UPDATE meta SET value='2' WHERE key='workflow_schema_version' AND value='1';
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                if 'meta' not in tables:
                    raise RuntimeError('目标文件不是本工作台数据库，未修改其结构')
                version=conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if version is None or version[0] not in {'1','2','3','4'}:
                    raise RuntimeError('数据库版本不兼容，禁止直接降级')
                workflow_version = conn.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone()
                if workflow_version and workflow_version[0] not in {'1','2'}:
                    raise RuntimeError('办理工作流版本不兼容，禁止直接降级')
                memory_version=conn.execute("SELECT value FROM meta WHERE key='memory_schema_version'").fetchone()
                if memory_version and memory_version[0] not in {'1','2'}:
                    raise RuntimeError('个人记忆版本不兼容，禁止直接降级')
                if memory_version and memory_version[0]=='2' and 'memory_policies' not in tables:
                    raise RuntimeError('个人记忆策略表缺失，未修改数据库')
                execution_version=conn.execute("SELECT value FROM meta WHERE key='execution_schema_version'").fetchone()
                if execution_version and (execution_version[0] not in {'1','2'} or not {'executions','execution_owners'}.issubset(tables) or execution_version[0]=='2' and 'execution_metrics' not in tables):
                    raise RuntimeError('执行记录版本不兼容或数据表缺失，禁止直接降级')
                review_version=conn.execute("SELECT value FROM meta WHERE key='action_review_schema_version'").fetchone()
                if review_version and (review_version[0]!='1' or 'task_reviews' not in tables):
                    raise RuntimeError('办理复核版本不兼容或数据表缺失，禁止直接降级')
                receipt_version=conn.execute("SELECT value FROM meta WHERE key='arrangement_receipt_schema_version'").fetchone()
                if receipt_version and (receipt_version[0]!='1' or 'arrangement_receipts' not in tables):
                    raise RuntimeError('安排提交记录版本不兼容或数据表缺失，禁止直接降级')
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.executescript('BEGIN IMMEDIATE;'+WORKSPACE_SCHEMA+"UPDATE meta SET value='4' WHERE key='schema_version';COMMIT;")
            conn.executescript('BEGIN IMMEDIATE;'+GENUI_SCHEMA+'COMMIT;')
            conn.executescript('BEGIN IMMEDIATE;'+WORKFLOW_SCHEMA+'COMMIT;')
            from .memory import SCHEMA as MEMORY_SCHEMA
            conn.executescript('BEGIN IMMEDIATE;'+MEMORY_SCHEMA+'COMMIT;')
            from .memory_policy import SCHEMA as MEMORY_POLICY_SCHEMA
            conn.executescript('BEGIN IMMEDIATE;'+MEMORY_POLICY_SCHEMA+'COMMIT;')
            from .execution import SCHEMA as EXECUTION_SCHEMA
            conn.executescript('BEGIN IMMEDIATE;'+EXECUTION_SCHEMA+'COMMIT;')
            from .action_review import SCHEMA as REVIEW_SCHEMA
            conn.executescript('BEGIN IMMEDIATE;'+REVIEW_SCHEMA+'COMMIT;')

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA secure_delete=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def backup(self, destination: Path):
        if destination.exists():
            raise ValueError("备份目标已存在，拒绝覆盖")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            target.execute('PRAGMA secure_delete=ON')
            result = target.execute("PRAGMA integrity_check").fetchone()[0]
            if result != 'ok':
                raise RuntimeError("备份完整性检查失败")
            target.execute("DELETE FROM sessions")
            target.execute("DELETE FROM invites")
            target.execute('DELETE FROM binding_codes')
            target.execute('DELETE FROM external_bindings')
            target.execute('DELETE FROM reply_shares')
            target.execute('DELETE FROM conversation_ai_consents')
            target.commit()


def audit(conn, user_id, notice_id, action, before=None, after=None, task_id=None):
    conn.execute("INSERT INTO audit(user_id,notice_id,task_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                 (user_id, notice_id, task_id, action, dumps(before) if before is not None else None,
                  dumps(after) if after is not None else None, int(time.time())))
