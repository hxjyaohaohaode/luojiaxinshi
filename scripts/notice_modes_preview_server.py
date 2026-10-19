"""Isolated browser fixture; model requests use an in-process mock transport."""
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
import httpx
import uvicorn
from app import ai
from app.config import Settings
from app.main import create_app
from app.version import VERSION

ORIGIN='http://127.0.0.1:8781'
FOLDER=ROOT/'artifacts/mvp-acceptance'
DATA=Path(tempfile.mkdtemp(prefix='notice-modes-',dir=FOLDER))
cfg=Settings(DATA,origin=ORIGIN,ai_api_key='synthetic-browser-only',notice_fast_enabled=True,ai_grounding=False)
app=create_app(cfg)
c=TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-Requested-With':'campus-notice'})
assert c.post('/api/auth/register',json={'username':'notice.modes.fixture','password':'Notice-Modes-Fixture-2026','display_name':'虚构速度验收','accepted_terms':True}).status_code==200
c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf']
notices={}
for engine in ('chromium','firefox','webkit'):
    notices[engine]={}
    for mode in ('fast','configured'):
        result=c.post('/api/notices',data={'title':f'虚构整理方式验收 {engine} {mode}','body':f'虚构工程验收 {engine} {mode}：本人提交申请表，提交日期与地点待学院说明。','source_label':'合成材料','materials_complete':'true'})
        assert result.status_code==200,result.text
        notices[engine][mode]=result.json()['id']
c.close()

real_client=httpx.Client
def provider(request):
    assert request.url.host=='api.xiaomimimo.com' and request.url.path=='/v1/chat/completions'
    payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content']);ref=context['sources'][0]['sections'][0]['ref']
    if payload['max_completion_tokens']==20000:
        result={'title':'合成办理草稿','summary':'本人提交申请表','applicability':'needs_review','applicability_reason':'本人条件仍需核实',
            'facts':{key:{'value':'','evidence':[]} for key in ai.FACT_KEYS},'warnings':[],
            'tasks':[{'title':'提交申请表','scope':'personal','materials':['申请表'],'evidence':[ref],'action_kind':'required','depends_on':[],'conditions':[],
                'due_date':None,'due_time':None,'deadline_text':'','deadline_evidence':[]}]}
    else:
        assert payload['max_completion_tokens']==(6144 if payload['model']=='mimo-v2.6-flash' else 16384)
        result={'source_checks':[{'source_index':0,'requirements_summary':'本人须提交申请表，具体时间地点未知。','evidence_refs':[ref],'coverage':'covered'}],
            'checked_task_indices':[0],'issues':[]}
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result,ensure_ascii=False)}}],
        'usage':{'prompt_tokens':100,'completion_tokens':50}})
httpx.Client=lambda **kwargs:real_client(transport=httpx.MockTransport(provider),**kwargs)
(FOLDER/f'notice-modes-preview-{VERSION}.json').write_text(json.dumps({'version':VERSION,'data_dir':str(DATA),'notices':notices,
    'sample':'Synthetic account and notices; all provider requests intercepted by mock transport; production data and credentials unused.'},ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8781,access_log=False)
