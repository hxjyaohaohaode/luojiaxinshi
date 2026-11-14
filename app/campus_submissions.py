"""Durable, owner-scoped decisions to stop an uncommitted publication.

These records are not editor caches or publishing permission. They live until
account deletion; full backup/restore retains cancellations present in that
snapshot. A delayed POST cannot revive a recorded cancellation. A snapshot
made before cancellation cannot recover that later decision; ordinary restore
restrictions and fresh organizational authorization still apply.
"""
import time

from fastapi import Depends, HTTPException, Path

from .security import rate_limit

TABLES = {'campus_submission_cancellations'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_submission_cancellations(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 16 AND 80),
 cancelled_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,request_id));
INSERT OR IGNORE INTO meta VALUES('campus_submission_schema_version','1');
"""


def initialize(conn):
    marker=conn.execute("SELECT value FROM meta WHERE key='campus_submission_schema_version'").fetchone()
    tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if marker and (marker[0]!='1' or not TABLES.issubset(tables)):
        raise RuntimeError('数据库扩展版本不兼容或必要记录缺失，未改写：campus_submission_schema_version')
    conn.executescript(SCHEMA)


def require_not_cancelled(conn, uid, request_id):
    if conn.execute('SELECT 1 FROM campus_submission_cancellations WHERE user_id=? AND request_id=?',
                    (uid,request_id)).fetchone():
        raise HTTPException(409, {'code':'publication_cancelled',
            'message':'这次发布请求已由本人停止，不会继续发送。需要发布新草稿时，请重新核对并使用新的提交编号。'})


def export_cancellations(conn, uid):
    # Portable export is informational. It must not be imported as another
    # account's request state, organizational authority or publishing consent.
    return [dict(row) for row in conn.execute(
        'SELECT request_id,cancelled_at FROM campus_submission_cancellations WHERE user_id=? ORDER BY cancelled_at,request_id',
        (uid,))]


def install(app, db, user):
    from .campus import publisher

    @app.post('/api/campus/submissions/{request_id}/cancel')
    def cancel(request_id:str=Path(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$'),current=Depends(user)):
        with db.connect() as conn:
            publisher(conn,current['id'])
        rate_limit(db,'campus-submission-cancel:'+current['id'],60,3600)
        # This is the same BEGIN IMMEDIATE boundary used by publication. The
        # winner is either an existing publication or a durable cancellation;
        # no response loss or competing request can produce both outcomes.
        with db.connect(write=True) as conn:
            publisher(conn,current['id'])
            previous=conn.execute('SELECT id FROM campus_publications WHERE publisher_id=? AND request_id=?',
                                  (current['id'],request_id)).fetchone()
            if previous:
                # An owner may have moved to another college since submitting.
                # This minimal operation receipt releases an uncertain editor;
                # it grants no access to the old notice, recipients or files.
                return {'state':'published','publication_id':previous['id']}
            conn.execute('INSERT OR IGNORE INTO campus_submission_cancellations VALUES(?,?,?)',
                         (current['id'],request_id,int(time.time())))
            return {'state':'cancelled'}
