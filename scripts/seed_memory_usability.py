"""Seed >100 short-term entries only in the isolated memory UI fixture."""
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.db import Database,ident

root=Path(__file__).resolve().parent.parent
path=(root/'artifacts/memory-v7-preview/data/app.sqlite3').resolve()
# The fixture database name is discovered only inside this exact private dir.
files=list(path.parent.glob('*.db'))+list(path.parent.glob('*.sqlite3'))
assert len(files)==1, 'Start the isolated v7 preview first'
path=files[0].resolve()
assert path.is_relative_to((root/'artifacts/memory-v7-preview/data').resolve())
db=Database(path)
with db.connect(write=True) as conn:
    user=conn.execute("SELECT id FROM users WHERE username='workflow.demo'").fetchone()
    assert user and conn.execute('SELECT count(*) FROM users').fetchone()[0]==1
    conn.execute('DELETE FROM limits')
    title='合成会话分页验收';chat=conn.execute('SELECT id FROM conversations WHERE user_id=? AND title=?',(user['id'],title)).fetchone()
    if chat:
        conn.execute("UPDATE memory_jobs SET state='done',finished_at=? WHERE source_kind='message' AND source_id IN (SELECT id FROM conversation_messages WHERE conversation_id=?)",(int(time.time()),chat['id']))
        conn.execute('DELETE FROM conversations WHERE id=?',(chat['id'],))
    cid=ident();now=int(time.time())
    conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,user['id'],title,now,now))
    for i in range(125):
        mid=ident();content=f'合成会话条件 {i:03d}，只在本会话讨论。'
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",(mid,cid,content,now))
        conn.execute("INSERT INTO memory_session_items(id,user_id,conversation_id,source_message_id,kind,content,context_key,lifetime,created_at,expires_at) VALUES(?,?,?,?,'constraint',?,'[\"\",[]]','session',?,?)",(ident(),user['id'],cid,mid,content,now+i,now+7*86400))
    conn.execute("UPDATE memory_jobs SET state='done',finished_at=? WHERE source_kind='message' AND source_id IN (SELECT id FROM conversation_messages WHERE conversation_id=?)",(now,cid))
from app.memory_learning import drain_jobs
for _ in range(10):
    drain_jobs(db,uid=user['id'])
    with db.connect() as conn:queued=conn.execute("SELECT count(*) FROM memory_jobs WHERE state='queued'").fetchone()[0]
    if not queued:break
assert not queued,'Fixture local index did not settle'
print('Isolated synthetic session entries ready: 125; local indexes settled')
