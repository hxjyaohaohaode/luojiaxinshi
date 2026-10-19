"""Isolated retained real draft plus synthetic manual-fallback fixtures; no AI calls."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
import uvicorn
from app.config import Settings
from app.main import create_app
from app.models import TaskData
from app.version import VERSION

FOLDER=ROOT/'artifacts/mvp-acceptance';ORIGIN='http://127.0.0.1:8781'
SOURCE=FOLDER/'business-notice-accelerated-dates-1.10.0.json'
sample=json.loads(SOURCE.read_text(encoding='utf-8'))
original=Path(sample['isolated_data_dir']).resolve();assert original.is_relative_to(FOLDER.resolve())
data=Path(tempfile.mkdtemp(prefix='resolution-preview-',dir=FOLDER))
with sqlite3.connect((original/'campus.sqlite3').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(data/'campus.sqlite3') as dest:source.backup(dest)
app=create_app(Settings(data,origin=ORIGIN,ai_api_key='',notice_semantic_review=False,ai_grounding=False))
client=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
assert client.post('/api/auth/login',json={'username':'business.notice.fixture','password':'Isolated-Notice-Fixture-2026'}).status_code==200
client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
record=client.get('/api/notices/'+sample['notice_id']).json()
assert record['status']=='draft' and not record['tasks']
legacy='之前暂存的总体核实说明需要保留，不能替代新的逐条处理。'
key='notice:'+record['id']+':'+str(record['version'])
assert client.put('/api/edit-cache/'+key,json={'revision':0,'payload':{'quality_resolution':legacy}}).status_code==200
manual={}
for engine in ('chromium','firefox','webkit'):
    n=client.post('/api/notices',data={'title':'虚构人工核对测试 '+engine,'body':'虚构工程夹具 '+engine+'：请本人准备申请表，日期和提交渠道待核实。','materials_complete':'true'}).json()
    n=client.post('/api/notices/'+n['id']+'/manual',json={'version':n['version']}).json()
    draft=n['draft'];draft['tasks']=[TaskData(title='准备申请表',materials=['申请表']).model_dump()]
    draft['quality']={'status':'unavailable','reason':'模拟复核服务暂时不可用，供界面验收。','issues':[]}
    with app.state.db.connect(write=True) as conn:conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(draft,ensure_ascii=False),n['id']))
    manual[engine]=n['id']
client.close()
(FOLDER/f'notice-resolution-preview-{VERSION}.json').write_text(json.dumps({'version':VERSION,'data_dir':str(data),'notice_id':record['id'],
    'manual_notices':manual,'quality':record['draft']['quality'],'legacy_note':legacy,'source_report':SOURCE.name,
    'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'sample':'Retained real MiMo draft/review with synthetic account; separate synthetic unavailable-review fixtures. No production data or provider calls.'},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8781,access_log=False)
