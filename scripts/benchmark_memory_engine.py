"""Reproducible local capacity/latency check using synthetic records only."""
import json
import argparse
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.db import Database
from app.memory import recall

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'memory-engine-benchmark')
folder=parser.parse_args().output.resolve()
if not folder.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Synthetic benchmarks must stay in artifacts/')
folder.mkdir(parents=True,exist_ok=True)
db=Database(folder/('synthetic-'+uuid.uuid4().hex+'.sqlite3'))
now=int(time.time());owner='synthetic-owner';chat='synthetic-chat';project='other-project'
start=time.perf_counter()
with db.connect(write=True) as conn:
    conn.execute("INSERT INTO users VALUES(?,?,?,'工程夹具','user','{}',?)",(owner,owner,'not-a-login-password',now))
    conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(chat,owner,'性能夹具',now,now))
    conn.execute('INSERT INTO memory_projects VALUES(?,?,?, ?,1,?,?)',(project,owner,'另一个项目','隔离用夹具',now,now))
    records=[]
    for index in range(10000):
        text=f'合成事项编号 {index}：课程 {index%30} 的申请材料包括项目说明和本人确认的课程计划；处理方法是先核对正式原文，再准备资料，提交后保留回执。'
        records.append((f'm{index:05}',owner,'global' if index%2 else 'project',None if index%2 else project,'',
            'preference' if index%500==1 else 'fact',text,None,1,0,1,now,now))
    conn.executemany('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',records)
insert_ms=(time.perf_counter()-start)*1000
latencies=[];results=[]
for query in ['课程申请的材料和提交回执','我习惯怎样核对通知','准备项目说明与计划','课程 17 的办理方法']*4:
    start=time.perf_counter()
    selected,report=recall(db,owner,chat,query,{'profile':True,'memory':True})
    latencies.append((time.perf_counter()-start)*1000)
    assert len(selected)<=12 and report['context_bytes']<=8000
    assert all(item['scope']=='global' for item in selected)
    results.append({'query':query,'count':len(selected),'context_bytes':report['context_bytes'],'latency_ms':round(latencies[-1],2)})
with db.connect() as conn:
    assert conn.execute('SELECT count(*) FROM memory_fts').fetchone()[0]==10000
    assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
output={'synthetic':True,'database':str(db.path),'stored':10000,'eligible_scope':5000,
    'algorithm':report.get('algorithm'),'memory_schema':3,
    'insertion_ms':round(insert_ms,2),'queries':len(latencies),'latency_ms':{
        'median':round(statistics.median(latencies),2),'p95':round(sorted(latencies)[int(.95*(len(latencies)-1))],2),
        'max':round(max(latencies),2)},'results':results,
    'provider_calls':0,'limits':'Local lexical retrieval benchmark, not a dense semantic recall or external-model quality benchmark.'}
(folder/'report.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in output.items() if key not in ('results','database')},ensure_ascii=False))
