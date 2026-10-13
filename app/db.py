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
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.executescript('BEGIN IMMEDIATE;'+WORKSPACE_SCHEMA+"UPDATE meta SET value='4' WHERE key='schema_version';COMMIT;")

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
            target.commit()


def audit(conn, user_id, notice_id, action, before=None, after=None, task_id=None):
    conn.execute("INSERT INTO audit(user_id,notice_id,task_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                 (user_id, notice_id, task_id, action, dumps(before) if before is not None else None,
                  dumps(after) if after is not None else None, int(time.time())))
