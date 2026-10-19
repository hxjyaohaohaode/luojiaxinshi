"""Isolated synthetic condition/participation fixtures, without provider access."""
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import TaskData
from app.db import dumps,ident
from app.version import VERSION

ORIGIN='http://127.0.0.1:8781'
folder=ROOT/'artifacts/mvp-acceptance';folder.mkdir(parents=True,exist_ok=True)
data=Path(tempfile.mkdtemp(prefix='action-plan-preview-',dir=folder))
app=create_app(Settings(data,origin=ORIGIN,ai_api_key='',ai_grounding=False))
report={'version':VERSION,'sample':'Synthetic fixtures; no model calls or production data','data_dir':str(data),'notices':{},'processing_notices':{}}

for engine in ('chromium','firefox','webkit'):
    c=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
    response=c.post('/api/auth/register',json={'username':'plans.'+engine,'password':'Action-Plans-Fixture-2026','display_name':'办理条件验收','accepted_terms':True})
    assert response.status_code==200,response.text
    c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf']
    body='虚构工程验收：本人先取得签章申请表，再于2027年10月20日17:00前上传。上传前须确认已收到正式立项通知。咨询可选，由本人决定。单位负责审核。'
    n=c.post('/api/notices',data={'title':'虚构验收｜前置与参加意愿','body':body,'source_label':'合成工程夹具','materials_complete':'true'}).json()
    n=c.post('/api/notices/'+n['id']+'/manual',json={'version':n['version']}).json()
    draft=n['draft'];source=n['sources'][0];section=source['sections'][0]
    evidence=[{'source_id':source['id'],'locator':section['locator'],'quote':section['text']}]
    draft['tasks']=[TaskData(title=title,evidence=evidence,scope=scope,details='合成步骤，用于校验条件、依赖与参加意愿。',
                    due_date='2027-10-20',due_time='17:00',deadline_text='2027年10月20日17:00前',deadline_evidence=evidence).model_dump()
                    for title,scope in [('取得签章申请表','personal'),('上传并记录提交回执','personal'),('可选咨询','personal'),('单位审核','other')]]
    draft['plans']={'0':{'action_kind':'required','depends_on':[],'conditions':[]},
                    '1':{'action_kind':'required','depends_on':[0],'conditions':['已收到正式立项通知']},
                    '2':{'action_kind':'optional','depends_on':[],'conditions':[]}}
    with app.state.db.connect(write=True) as conn:conn.execute('UPDATE notices SET draft=? WHERE id=?',(dumps(draft),n['id']))
    report['notices'][engine]=n['id']
    pending_notice=c.post('/api/notices',data={'title':'虚构验收｜长任务处理状态','body':body+'\n本条专用于长任务状态验收。','source_label':'合成工程夹具','materials_complete':'true'})
    assert pending_notice.status_code==200,pending_notice.text
    waiting=pending_notice.json()
    owner=c.get('/api/session').json()['user']['id'];token=ident();key=ident();now=int(time.time())
    with app.state.db.connect(write=True) as conn:
        conn.execute("UPDATE notices SET status='processing',processing_token=?,processing_at=? WHERE id=?",(token,now-240,waiting['id']))
        conn.execute("INSERT INTO ai_calls(id,user_id,notice_id,model,status,created_at) VALUES(?,?,?,'synthetic-fixture','processing',?)",(key,owner,waiting['id'],now-240))
        app.state.execution.start(conn,key,owner,'notice',waiting['id'],token)
        conn.execute("UPDATE executions SET started_at=?,stage='extracting' WHERE id=?",(now-240,key))
    report['processing_notices'][engine]={'id':waiting['id'],'execution_id':key}

(folder/('action-plan-preview-'+VERSION+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8781,access_log=False)
