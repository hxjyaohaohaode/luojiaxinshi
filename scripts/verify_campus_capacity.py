"""Measure a full default-capacity synthetic account; no server or model calls."""
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.db import dumps,ident
from app.documents import text_source
from app.main import create_app
from app.notice_ingest import fingerprint
from app.security import new_invite
from fastapi.testclient import TestClient


def main():
    output=ROOT/'artifacts'/'campus-capacity-matters';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='campus-capacity-') as directory:
        cfg=Settings(Path(directory),ai_api_key='',ai_grounding=False,notice_semantic_review=False,agent_enabled=False)
        app=create_app(cfg);db=app.state.db
        client=TestClient(app,base_url=cfg.origin)
        client.headers.update({'Origin':cfg.origin,'X-Requested-With':'campus-notice'})
        response=client.post('/api/auth/register',json={'invite':new_invite(db,'user'),'username':'capacity.synthetic',
            'password':'Synthetic-Capacity-2026-only!','display_name':'合成容量验收','accepted_terms':True})
        assert response.status_code==200,response.text
        session=client.get('/api/session').json();client.headers['X-CSRF-Token']=session['csrf'];uid=session['user']['id']
        now=int(time.time());nids=[]
        with db.connect(write=True) as conn:
            for i in range(cfg.usage_limits.notices-1):
                nid=ident();nids.append(nid);source=text_source(f'第{i}期课程通知。请在课程平台核对考核要求。容量验收材料编号 {i}。'+('合成资料文本。'*80))
                conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (nid,uid,f'第{i}期课程考核安排','合成来源','',0,fingerprint([source]),now,now))
                conn.execute('INSERT INTO sources(id,notice_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (ident(),nid,source['name'],source['kind'],source['content'],source['sha256'],source['status'],dumps(source['sections']),source['warning'],now))
        timings={}
        def measured(label,fn):
            start=time.perf_counter();result=fn();timings[label]=round((time.perf_counter()-start)*1000,2);assert result.status_code==200,result.text;return result.json()
        last=measured('intake_at_10000_records_ms',lambda:client.post('/api/notices',data={'body':'最终第10000则独立容量验收通知'}))
        records=measured('list_10000_records_ms',lambda:client.get('/api/notices'))
        assert len(records)==10000
        found=measured('full_text_search_10000_records_ms',lambda:client.get('/api/notices/search',params={'q':'材料编号 9988。'}))
        assert len(found)==1
        measured('matter_candidates_10000_records_ms',lambda:client.get('/api/notices/'+nids[0]+'/matter'))
        replay=measured('duplicate_replay_at_capacity_ms',lambda:client.post('/api/notices',data={'body':'最终第10000则独立容量验收通知'}))
        assert replay['id']==last['id']
        assert client.post('/api/notices',data={'body':'第10001则被部署容量拒绝'}).status_code==413
        report={'synthetic':True,'live_model_calls':0,'external_messages':0,'notices':len(records),
            'payload_bytes':len(dumps(records).encode()),'timings':timings,'capacity_boundary':'10000 succeeds; new 10001 rejected; duplicate replay succeeds',
            'scope':'single-process local test; not a multi-user concurrency or campus production capacity claim'}
        (output/'capacity-benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
