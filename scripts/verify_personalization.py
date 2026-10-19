"""Explicit opt-in real MiMo check, using only synthetic isolated records."""
import argparse
from dataclasses import replace
import json
import re
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.console import configure_text_output
from app.db import ident
from app.main import create_app
from fastapi.testclient import TestClient


def run():
    configure_text_output()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Explicitly authorize real provider calls with local credentials')
    parser.add_argument('--long-history',action='store_true',help='Exercise more than 80 logical messages and actual context compression')
    parser.add_argument('--output',help='Report filename under artifacts/mvp-acceptance; preserve earlier observations')
    args=parser.parse_args()
    if not args.live:parser.error('This check calls the real provider; pass --live to run it.')
    folder=ROOT/'artifacts/mvp-acceptance';folder.mkdir(parents=True,exist_ok=True)
    settings=Settings.from_env()
    if not settings.ai_api_key:raise SystemExit('No local model credential configured.')
    report={'sample':'synthetic only; not real student or notification evaluation','model':settings.ai_model}
    with tempfile.TemporaryDirectory(prefix='context-live-',dir=folder) as tmp:
        settings=replace(settings,data_dir=Path(tmp),origin='http://127.0.0.1:8791',production=False,ai_grounding=True,ai_workflow_timeout=300,registration_mode='public')
        app=create_app(settings)
        with TestClient(app,base_url=settings.origin,headers={'Origin':settings.origin,'X-Requested-With':'campus-notice'}) as c:
            r=c.post('/api/auth/register',json={'username':'synthetic.context','display_name':'虚构验收用户','password':'Synthetic-Verification-Only-2026','accepted_terms':True});assert r.status_code==200,r.status_code
            c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf']
            chat=c.post('/api/conversations',json={}).json();cid=chat['id']
            p=c.post('/api/memory/projects',json={'name':'青禾课程项目'}).json()
            other=c.post('/api/memory/projects',json={'name':'紫云竞赛项目'}).json()
            for item in [
                {'scope':'global','kind':'preference','content':'请称呼我验收同学，回答先给结论。'},
                {'scope':'project','project_id':p['id'],'kind':'fact','pinned':True,'content':'我在当前项目中使用的项目名称是青禾课程项目。'},
                {'scope':'project','project_id':other['id'],'kind':'fact','pinned':True,'content':'我在另一个项目中使用的项目名称是紫云竞赛项目。'}]:
                assert c.post('/api/memory/items',json=item).status_code==200
            assert c.put(f'/api/conversations/{cid}/context',json={'version':0,'project_id':p['id']}).status_code==200
            # More than the previous 80-message limit. Records are explicitly synthetic.
            with app.state.db.connect(write=True) as conn:
                parent=None
                for i in range(82):
                    role='user' if i%2==0 else 'assistant'
                    content=('合成历史记录：只把本人提交时间作为本人期限。' if role=='user' else '这是一段无事实依据的合成旧回答，用于测量历史上下文压缩。')*(1 if role=='user' else 80)
                    mid=ident()
                    if role=='user':parent=mid
                    conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,?,?,'complete',?,?)",(mid,cid,role,content,parent if role=='assistant' and args.long_history else None,int(time.time())-100+i))
            chat=c.get('/api/conversations/'+cid).json()
            body='虚构验收通知：本人须于2030年10月20日17:00前提交申请表和个人说明至学院办公室；学院于2030年10月24日审核。'
            chat=c.post(f'/api/conversations/{cid}/sources',data={'version':chat['version'],'body':body,'label':'明确标注的虚构通知'}).json()
            started=time.monotonic()
            prompt='不要联网。只用文字，简洁回答：按我保存的称呼叫我，说明当前项目名称；根据本次材料，说明本人提交的日期、时刻和两份材料。区分学院审核日期，不要把审核日期当作本人提交期限。'
            response=c.post(f'/api/conversations/{cid}/messages/stream',json={'version':chat['version'],'content':prompt,'request_id':uuid.uuid4().hex,'allow_external_processing':True})
            report['http_status']=response.status_code;report['elapsed_seconds']=round(time.monotonic()-started,3)
            result=c.get('/api/conversations/'+cid).json()
            final=result['messages'][-1];answer=final.get('content','')
            report.update(status=final['status'],answer=answer,error=final.get('error'),grounding=final.get('grounding',{}))
            report['checks']={'completed':final['status']=='complete','remembered_name':'验收同学' in answer,'correct_project':'青禾' in answer,'no_other_project':'紫云' not in answer,
                'personal_deadline':bool(re.search(r'(?:2030[年/-])?10[月/-]20日?.{0,20}17[:：]00',answer)),
                'review_date_separate':bool(re.search(r'(?:2030[年/-])?10[月/-]24日?',answer)) and '审核' in answer,
                'materials':'申请表' in answer and '个人说明' in answer,
                'history_policy':final.get('grounding',{}).get('context',{}).get('compressed') is args.long_history,
                'no_status_model':final.get('grounding',{}).get('summary_model') is None}
    name=args.output or ('personalization-long-live.json' if args.long_history else 'personalization-live.json')
    if Path(name).name!=name:raise ValueError('Output must be a filename')
    (folder/name).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('answer','grounding')},ensure_ascii=False))
    raise SystemExit(0 if all(report['checks'].values()) else 1)


if __name__=='__main__':run()
