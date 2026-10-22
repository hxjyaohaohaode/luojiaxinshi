"""Synthetic capacity, hierarchy, deep-source recall and snapshot benchmark."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.db import Database,dumps
from app.memory import recall
from app.memory_tree import reconcile,snapshot
from app.memory_tree_queries import entries,status
from app.memory_resources import ingest_resource
from app.context_snapshot import capture,bind_memories,assert_current

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'artifacts/memory-v7-benchmark')
folder=parser.parse_args().output.resolve()
if not folder.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Synthetic output must stay in artifacts/')
folder.mkdir(parents=True,exist_ok=True)
db=Database(folder/('synthetic-'+uuid.uuid4().hex+'.sqlite3'))
uid='synthetic-owner';cid='synthetic-chat';pid='unselected-project';now=int(time.time())
with db.connect(write=True) as conn:
    conn.execute("INSERT INTO users VALUES(?,?,?,'工程夹具','user','{}',?)",(uid,uid,'not-a-login-password',now))
    conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,uid,'合成测试',now,now))
    conn.execute('INSERT INTO memory_projects VALUES(?,?,?,?,1,?,?)',(pid,uid,'隔离项目','',now,now))
    conn.executemany('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',[
        (f'm{i:05}',uid,'global' if i%2 else 'project',None if i%2 else pid,'','fact',
         f'课程申请编号 {i}，申请材料包括项目说明与课程计划；提交后保留回执并记录后续办理。',None,1,0,1,now,now) for i in range(10000)])
start=time.perf_counter()
with db.connect(write=True) as conn:reconcile(conn,uid)
tree_build_ms=(time.perf_counter()-start)*1000
with db.connect(write=True) as conn:
    for i in range(20):
        sid=f'document-{i}'
        text='实验背景与器材配置。'*650+f'氙灯观测协议编号 D{i:02}，更换周期是 {240+i} 小时，提交地点是光学楼 {900+i}。'
        conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,cid,f'实验协议 {i}.txt','text','','synthetic','ok','[]','',now))
        conn.execute('INSERT INTO material_library VALUES(?,?,?,?)',(sid,f'实验协议 {i}',dumps([{'locator':'完整正文','text':text}]),len(text)))
        ingest_resource(conn,uid,'resource_material',sid)
    reconcile(conn,uid)
access={'profile':True,'memory':True,'library':True,'attachments':True,'schedule':True}
latencies=[];snapshots=[];tree_latencies=[];browse_latencies=[];status_latencies=[];page_bytes=[];results=[]
for question in ['课程申请材料与提交回执','氙灯观测协议 D17 的更换周期','D04 协议的提交地点','课程计划办理记录']*4:
    start=time.perf_counter();got,report=recall(db,uid,cid,question,access);latencies.append((time.perf_counter()-start)*1000)
    assert len(got)<=12 and report['context_bytes']<=8000 and all(m['scope']=='global' for m in got)
    if '氙灯' in question:assert any(m.get('origin')=='source_passage' and '257' in m['content'] for m in got)
    start=time.perf_counter()
    with db.connect() as conn:snap=bind_memories(conn,uid,cid,capture(conn,uid,cid,access,set()),got)
    for _ in range(3):
        with db.connect() as conn:assert_current(conn,uid,cid,snap)
    snapshots.append((time.perf_counter()-start)*1000)
    start=time.perf_counter()
    with db.connect(write=True) as conn:snapshot(conn,uid)
    tree_latencies.append((time.perf_counter()-start)*1000)
    browse_query=['课程','氙灯','D17',''][len(results)%4]
    start=time.perf_counter()
    with db.connect(write=True) as conn:page=entries(conn,uid,q=browse_query,view='auto')
    browse_latencies.append((time.perf_counter()-start)*1000)
    assert len(page['memories'])+len(page['passages'])<=50
    if browse_query=='D17':assert any('D17' in p['content'] for p in page['passages'])
    page_bytes.append(len(dumps(page).encode('utf-8')))
    start=time.perf_counter()
    with db.connect() as conn:token=status(conn,uid)
    status_latencies.append((time.perf_counter()-start)*1000)
    assert len(token['token'])==64
    results.append({'query':question,'count':len(got),'context_bytes':report['context_bytes'],'source_passages':report['source_passages']})
def stats(values):return {'median':round(statistics.median(values),2),'p95':round(sorted(values)[int(.95*(len(values)-1))],2),'max':round(max(values),2)}
with db.connect() as conn:
    count=conn.execute('SELECT count(*) FROM memory_source_units').fetchone()[0]
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not conn.execute('PRAGMA foreign_key_check').fetchall()
result={'synthetic':True,'schema':6,'base_memories':10000,'eligible_base_scope':5000,'source_documents':20,
        'source_passages':count,'queries':len(latencies),'tree_initial_classification_ms':round(tree_build_ms,2),
        'recall_ms':stats(latencies),'snapshot_bind_and_three_checks_ms':stats(snapshots),'tree_read_ms':stats(tree_latencies),
        'browse_page_ms':stats(browse_latencies),'change_token_ms':stats(status_latencies),'browse_page_max_bytes':max(page_bytes),
        'provider_calls':0,'results':results,'limits':'Local synthetic engineering benchmark; not external-model semantic accuracy or a production latency guarantee.'}
(folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))
