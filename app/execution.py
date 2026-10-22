"""Durable run ownership and interruption recovery for model workflows.

Leases fence publication, not provider billing. Lost work is never replayed
automatically: the user retries against current inputs and a new attempt ID.
Multiple application processes share the same SQLite ownership registry.
"""
import json
import time

from fastapi import Depends

from .db import dumps,ident

LEASE_SECONDS=45
HEARTBEAT_SECONDS=10
INTERRUPTED='处理进程已中断，已保留问题和材料。请核对当前内容后重试；模型服务可能已计费。'
SCHEMA="""
CREATE TABLE IF NOT EXISTS execution_owners(id TEXT PRIMARY KEY,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS executions(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 owner_id TEXT NOT NULL REFERENCES execution_owners(id),
 kind TEXT NOT NULL CHECK(kind IN ('conversation','notice')),
 conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
 notice_id TEXT REFERENCES notices(id) ON DELETE CASCADE,
 processing_token TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'running',stage TEXT NOT NULL DEFAULT 'accepted',
 stop_reason TEXT NOT NULL DEFAULT '',started_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,finished_at INTEGER,
 CHECK((kind='conversation' AND conversation_id IS NOT NULL AND notice_id IS NULL)
    OR (kind='notice' AND notice_id IS NOT NULL AND conversation_id IS NULL)));
CREATE INDEX IF NOT EXISTS executions_owner ON executions(user_id,started_at DESC);
CREATE INDEX IF NOT EXISTS executions_active ON executions(status,owner_id);
CREATE TABLE IF NOT EXISTS execution_metrics(
 execution_id TEXT PRIMARY KEY REFERENCES executions(id) ON DELETE CASCADE,metrics TEXT NOT NULL);
INSERT INTO meta VALUES('execution_schema_version','2') ON CONFLICT(key) DO UPDATE SET value='2';
"""


class Runtime:
    def __init__(self,db):
        self.db=db
        self.owner=ident()

    def register(self,conn,now):
        conn.execute('INSERT INTO execution_owners VALUES(?,?) ON CONFLICT(id) DO UPDATE SET expires_at=excluded.expires_at',
                     (self.owner,now+LEASE_SECONDS))

    def start(self,conn,key,uid,kind,target,token):
        now=int(time.time());self.register(conn,now)
        conn.execute('''INSERT INTO executions(id,user_id,owner_id,kind,conversation_id,notice_id,processing_token,started_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)''',(key,uid,self.owner,kind,target if kind=='conversation' else None,
            target if kind=='notice' else None,token,now,now))

    def finish(self,conn,key,status,reason=''):
        if status not in {'succeeded','failed','cancelled','discarded','interrupted'}:raise ValueError('invalid execution status')
        now=int(time.time())
        conn.execute("UPDATE executions SET status=?,stop_reason=?,updated_at=?,finished_at=? WHERE id=? AND status='running'",
                     (status,reason,now,now,key))

    def tick(self):
        with self.db.connect(write=True) as conn:
            now=int(time.time());self.register(conn,now)
            from .agent_runtime.store import recover as recover_agents
            return recover(conn,now)+recover_agents(conn,now)

    def close(self):
        with self.db.connect(write=True) as conn:
            now=int(time.time())
            conn.execute('UPDATE execution_owners SET expires_at=? WHERE id=?',(now,self.owner))
            recover(conn,now)
            from .agent_runtime.store import recover as recover_agents
            recover_agents(conn,now)


def stage(conn,key,name):
    if name not in {'accepted','planning','retrieving','searching','coverage','writing','verifying','extracting','receiving','reviewing'}:return
    conn.execute("UPDATE executions SET stage=?,updated_at=? WHERE id=? AND status='running'",(name,int(time.time()),key))


def notice_processing(conn,record,legacy_timeout,now=None):
    """A live lease outranks the historical HTTP read-timeout heuristic."""
    if not record.get('processing_token'):return False
    now=time.time() if now is None else now
    row=conn.execute('''SELECT e.status,o.expires_at FROM executions e JOIN execution_owners o ON o.id=e.owner_id
        WHERE e.notice_id=? AND e.processing_token=? ORDER BY e.started_at DESC,e.rowid DESC LIMIT 1''',
        (record['id'],record['processing_token'])).fetchone()
    if row:return row['status']=='running' and row['expires_at']>now
    # Records created before durable executions have no owner to inspect.
    return (record.get('processing_at') or 0)>now-legacy_timeout-30


def recover(conn,now):
    lost=conn.execute("SELECT e.* FROM executions e JOIN execution_owners o ON o.id=e.owner_id WHERE e.status='running' AND o.expires_at<=?",(now,)).fetchall()
    for run in lost:
        if run['kind']=='conversation':
            conn.execute('''UPDATE conversations SET processing_token=NULL,processing_at=NULL,version=version+1,updated_at=?
                WHERE id=? AND processing_token=?''',(now,run['conversation_id'],run['processing_token'])).rowcount
            # Each message belongs to this attempt, even if a newer attempt now
            # owns the conversation. Finalize the old message without touching
            # the newer conversation token or its answer.
            changed=conn.execute("UPDATE conversation_messages SET status='failed',error=? WHERE id=? AND status='processing'",(INTERRUPTED,run['id'])).rowcount
            if changed:
                conn.execute('UPDATE genui_messages SET validated=0 WHERE message_id=?',(run['id'],))
                row=conn.execute('SELECT report FROM reply_grounding WHERE message_id=?',(run['id'],)).fetchone()
                if row:
                    report=json.loads(row['report']);report.update(status='not_published',invalidation='process_lost',finished_at=now)
                    if report.get('harness'):report['harness']['stop_reason']='process_lost'
                    conn.execute('UPDATE reply_grounding SET report=? WHERE message_id=?',(dumps(report),run['id']))
        else:
            conn.execute("""UPDATE notices SET status='failed',error=?,processing_token=NULL,processing_at=NULL,
                version=version+1,updated_at=? WHERE id=? AND processing_token=?""",(INTERRUPTED,now,run['notice_id'],run['processing_token'])).rowcount
            conn.execute("UPDATE ai_calls SET status='interrupted' WHERE id=? AND status='processing'",(run['id'],))
        conn.execute("UPDATE executions SET status='interrupted',stop_reason='process_lost',updated_at=?,finished_at=? WHERE id=?",(now,now,run['id']))
    return len(lost)


def install(app,db,user):
    @app.get('/api/executions')
    def recent(current=Depends(user)):
        with db.connect() as conn:
            rows=conn.execute('''SELECT e.id,e.kind,e.status,e.stage,e.stop_reason,e.started_at,e.updated_at,e.finished_at,
                e.conversation_id,e.notice_id,COALESCE(c.title,n.title,'已删除内容') AS title,m.metrics
                FROM executions e LEFT JOIN conversations c ON c.id=e.conversation_id LEFT JOIN notices n ON n.id=e.notice_id
                LEFT JOIN execution_metrics m ON m.execution_id=e.id
                WHERE e.user_id=? ORDER BY e.started_at DESC,e.rowid DESC LIMIT 50''',(current['id'],)).fetchall()
            from .notice_progress import decode
            items=[]
            for row in rows:
                item=dict(row);item['metrics']=decode(item['metrics']);items.append(item)
            return {'items':items,'limit':50,'recovery':'中断后需要本人重试，不会自动重复向模型发送。'}
