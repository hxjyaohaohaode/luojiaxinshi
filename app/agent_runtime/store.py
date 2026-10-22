"""Transactional admission, owner fencing, append-only events and exact approvals."""
import hashlib
import json
import time

from fastapi import HTTPException

from ..db import dumps, ident
from .types import AgentError

TABLES = {'agent_threads', 'agent_turns', 'agent_events', 'agent_messages', 'agent_approvals'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_threads(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
 title TEXT NOT NULL,options TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS agent_turns(
 id TEXT PRIMARY KEY,thread_id TEXT NOT NULL REFERENCES agent_threads(id) ON DELETE CASCADE,
 owner_id TEXT NOT NULL REFERENCES execution_owners(id),request_id TEXT NOT NULL,prompt TEXT NOT NULL,
 status TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
 usage TEXT NOT NULL DEFAULT '{}',created_at INTEGER NOT NULL,finished_at INTEGER,
 UNIQUE(thread_id,request_id));
CREATE UNIQUE INDEX IF NOT EXISTS agent_one_active ON agent_turns(thread_id)
 WHERE status IN ('running','waiting_approval');
CREATE TABLE IF NOT EXISTS agent_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,thread_id TEXT NOT NULL REFERENCES agent_threads(id) ON DELETE CASCADE,
 turn_id TEXT NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,type TEXT NOT NULL,
 data TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS agent_event_cursor ON agent_events(thread_id,seq);
CREATE TABLE IF NOT EXISTS agent_messages(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,turn_id TEXT NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,
 agent_id TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_approvals(
 id TEXT PRIMARY KEY,turn_id TEXT NOT NULL REFERENCES agent_turns(id) ON DELETE CASCADE,
 call_id TEXT NOT NULL,tool TEXT NOT NULL,arguments TEXT NOT NULL,digest TEXT NOT NULL,
 status TEXT NOT NULL,expires_at INTEGER NOT NULL,UNIQUE(turn_id,call_id));
INSERT OR IGNORE INTO meta VALUES('agent_schema_version','1');
"""
ACTIVE = ('running', 'waiting_approval')


def event(conn, tid, run, kind, data):
    cursor = conn.execute('INSERT INTO agent_events(thread_id,turn_id,type,data,created_at) VALUES(?,?,?,?,?)',
                          (tid, run, kind, dumps(data), int(time.time())))
    return {'seq': cursor.lastrowid, 'thread_id': tid, 'turn_id': run, 'type': kind, 'data': data}


def recover(conn, now):
    rows = conn.execute("""SELECT r.* FROM agent_turns r JOIN execution_owners o ON o.id=r.owner_id
        WHERE r.status IN ('running','waiting_approval') AND o.expires_at<=?""", (now,)).fetchall()
    for row in rows:
        finish(conn, row, 'interrupted', error='执行进程中断；操作可能已完成，请核对后手动重试。')
    return len(rows)


def finish(conn, row, status, answer='', error='', usage=None):
    changed = conn.execute("""UPDATE agent_turns SET status=?,answer=?,error=?,usage=?,finished_at=?
        WHERE id=? AND status IN ('running','waiting_approval')""",
        (status, answer, error, dumps(usage or {}), int(time.time()), row['id'])).rowcount
    if changed:
        conn.execute("UPDATE agent_approvals SET status='expired' WHERE turn_id=? AND status IN ('pending','approve')", (row['id'],))
        event(conn, row['thread_id'], row['id'], 'turn.' + status, {'status': status, 'answer': answer, 'error': error, 'usage': usage or {}})
    return bool(changed)


class Store:
    def __init__(self, db, owner):
        self.db, self.owner = db, owner

    def own(self, conn, tid, uid):
        row = conn.execute('SELECT * FROM agent_threads WHERE id=? AND user_id=?', (tid, uid)).fetchone()
        if row is None:
            raise HTTPException(404, '任务会话不存在或无权访问')
        return {**dict(row), 'options': json.loads(row['options'])}

    def chat_thread(self, uid, cid):
        """Bind execution to the existing conversation; never create another UI/chat."""
        from .types import NewThread
        with self.db.connect(write=True) as conn:
            chat = conn.execute('SELECT title FROM conversations WHERE id=? AND user_id=?', (cid, uid)).fetchone()
            if not chat:
                raise HTTPException(404, '对话不存在或无权访问')
            for row in conn.execute('SELECT id,options FROM agent_threads WHERE conversation_id=? AND user_id=?', (cid, uid)):
                if json.loads(row['options']).get('channel') == 'conversation':
                    return self.own(conn, row['id'], uid)
            tid = ident()
            options = NewThread(title=chat['title'], conversation_id=cid, scopes=['library', 'schedule', 'memory']).model_dump()
            options['channel'] = 'conversation'
            conn.execute('INSERT INTO agent_threads VALUES(?,?,?,?,?,?)',
                         (tid, uid, cid, chat['title'], dumps(options), int(time.time())))
            return self.own(conn, tid, uid)

    def create(self, uid, options):
        tid, now = ident(), int(time.time())
        with self.db.connect(write=True) as conn:
            if options.conversation_id and not conn.execute('SELECT 1 FROM conversations WHERE id=? AND user_id=?', (options.conversation_id, uid)).fetchone():
                raise HTTPException(404, '原对话不存在或无权访问')
            if conn.execute('SELECT count(*) FROM agent_threads WHERE user_id=?', (uid,)).fetchone()[0] >= 100:
                raise HTTPException(413, '任务会话已达 100 个，请先删除旧会话')
            if not options.conversation_id:
                if conn.execute('SELECT count(*) FROM conversations WHERE user_id=?', (uid,)).fetchone()[0] >= 100:
                    raise HTTPException(413, '原对话已达 100 个，请先整理旧对话')
                options = options.model_copy(update={'conversation_id': ident()})
                conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',
                             (options.conversation_id, uid, options.title, now, now))
            conn.execute('INSERT INTO agent_threads VALUES(?,?,?,?,?,?)', (tid, uid, options.conversation_id, options.title, dumps(options.model_dump()), now))
            return self.own(conn, tid, uid)

    def start(self, uid, tid, payload, daily_limit):
        with self.db.connect(write=True) as conn:
            thread = self.own(conn, tid, uid)
            existing = conn.execute('SELECT * FROM agent_turns WHERE thread_id=? AND request_id=?', (tid, payload.request_id)).fetchone()
            if existing:
                if existing['prompt'] != payload.prompt:
                    raise HTTPException(409, '同一请求标识不能用于不同任务')
                return thread, dict(existing), False
            now = int(time.time())
            recover(conn, now)
            if conn.execute("SELECT 1 FROM agent_turns WHERE thread_id=? AND status IN ('running','waiting_approval')", (tid,)).fetchone():
                raise HTTPException(409, '当前任务仍在执行，请先等待或停止')
            if thread['options'].get('channel') != 'conversation' and conn.execute('SELECT count(*) FROM agent_turns WHERE thread_id=?', (tid,)).fetchone()[0] >= 100:
                raise HTTPException(413, '会话已达 100 轮，请新建任务会话')
            if conn.execute("SELECT count(*) FROM agent_turns r JOIN agent_threads t ON t.id=r.thread_id WHERE r.status IN ('running','waiting_approval')").fetchone()[0] >= 4:
                raise HTTPException(429, '当前执行任务较多，请稍后重试')
            # Admission and per-provider-call limits are separate bounds.
            count = conn.execute('SELECT count(*) FROM agent_turns r JOIN agent_threads t ON t.id=r.thread_id WHERE t.user_id=? AND r.created_at>?', (uid, now-86400)).fetchone()[0]
            if count >= daily_limit:
                raise HTTPException(429, '今日智能任务次数已达上限')
            conn.execute('INSERT INTO execution_owners VALUES(?,?) ON CONFLICT(id) DO UPDATE SET expires_at=excluded.expires_at', (self.owner, now+45))
            run = ident()
            conn.execute("INSERT INTO agent_turns(id,thread_id,owner_id,request_id,prompt,status,created_at) VALUES(?,?,?,?,?,'running',?)", (run, tid, self.owner, payload.request_id, payload.prompt, now))
            event(conn, tid, run, 'turn.started', {'provider': thread['options']['provider']})
            return thread, dict(conn.execute('SELECT * FROM agent_turns WHERE id=?', (run,)).fetchone()), True

    def active(self, run):
        with self.db.connect() as conn:
            row = conn.execute('SELECT r.status,o.expires_at FROM agent_turns r JOIN execution_owners o ON o.id=r.owner_id WHERE r.id=? AND r.owner_id=?', (run, self.owner)).fetchone()
        if not row or row['status'] not in ACTIVE or row['expires_at'] <= time.time():
            raise AgentError('执行已停止或所有权已失效')

    def emit(self, tid, run, kind, data):
        self.active(run)
        with self.db.connect(write=True) as conn:
            return event(conn, tid, run, kind, data)

    def message(self, run, aid, body):
        self.active(run)
        with self.db.connect(write=True) as conn:
            conn.execute('INSERT INTO agent_messages(turn_id,agent_id,body) VALUES(?,?,?)', (run, aid, dumps(body)))

    def approval(self, tid, run, call_id, name, arguments):
        key = ident()
        digest = hashlib.sha256(dumps([run, call_id, name, arguments]).encode()).hexdigest()
        with self.db.connect(write=True) as conn:
            conn.execute('INSERT INTO agent_approvals VALUES(?,?,?,?,?,?,?,?)', (key, run, call_id, name, dumps(arguments), digest, 'pending', int(time.time())+300))
            conn.execute("UPDATE agent_turns SET status='waiting_approval' WHERE id=? AND status='running'", (run,))
            event(conn, tid, run, 'approval.requested', {'id': key, 'tool': name, 'arguments': arguments, 'digest': digest})
        return key

    def decide(self, uid, tid, key, decision):
        with self.db.connect(write=True) as conn:
            self.own(conn, tid, uid)
            row = conn.execute('SELECT a.*,r.status AS run_status FROM agent_approvals a JOIN agent_turns r ON r.id=a.turn_id WHERE a.id=? AND r.thread_id=?', (key, tid)).fetchone()
            if row is None:
                raise HTTPException(404, '审批不存在')
            if row['digest'] != decision.digest or row['status'] != 'pending' or row['expires_at'] <= time.time() or row['run_status'] not in ACTIVE:
                raise HTTPException(409, '审批已处理、过期或操作不匹配')
            conn.execute('UPDATE agent_approvals SET status=? WHERE id=?', (decision.decision, key))
            event(conn, tid, row['turn_id'], 'approval.resolved', {'id': key, 'decision': decision.decision})
        return {'status': decision.decision}
