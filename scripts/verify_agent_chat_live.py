"""Paid, synthetic smoke test through the EXISTING chat and its independent review.

Uses a temporary database and a fixed message. No real user data or workspaces
are read. Server credentials are taken from the usual config, never printed.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.db import ident
from app.security import hash_password

PROMPT='仅使用本条测试消息：这是工具兼容性工程验收，没有真实个人资料。请调用一次 list_files 查看空的对话工作目录，然后用一句话说明目录是否为空。不要联网，不创建文件和子任务，只输出纯文字。'


def check():
    output=ROOT/'artifacts'/'agent-chat-live';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=output) as folder:
        settings=replace(Settings.from_env(),data_dir=Path(folder),origin='http://127.0.0.1:8794',ai_daily_limit=12,
                         agent_enabled=True,ai_grounding=True,notice_semantic_review=False,agent_mcp_servers={},agent_sandbox_image='')
        app=create_app(settings)
        with app.state.db.connect(write=True) as conn:
            conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',(ident(),'synthetic-agent',hash_password('SyntheticOnly2026!'),'工程验收','user','{}',int(time.time())))
        with TestClient(app,base_url=settings.origin) as client:
            client.headers.update({'Origin':settings.origin,'X-Requested-With':'campus-notice'})
            client.post('/api/auth/login',json={'username':'synthetic-agent','password':'SyntheticOnly2026!'}).raise_for_status()
            client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
            chat=client.post('/api/conversations',json={'title':'原聊天 Agent 合成验收'}).json()
            started=time.monotonic()
            response=client.post('/api/conversations/'+chat['id']+'/messages/stream',json={'version':chat['version'],
                'content':PROMPT,'request_id':ident(),'allow_external_processing':True})
            response.raise_for_status()
            final=client.get('/api/conversations/'+chat['id']).json()['messages'][-1]
            with app.state.db.connect() as conn:
                calls=[json.loads(r['data'])['tool'] for r in conn.execute("SELECT data FROM agent_events WHERE type='tool.completed'")]
            grounding=final.get('grounding',{})
            report={'synthetic_input':True,'route':'/api/conversations/{cid}/messages/stream','model':settings.ai_model,
                    'elapsed_seconds':round(time.monotonic()-started,2),'status':final['status'],'error':final['error'],
                    'answer':final['content'],'planning_mode':grounding.get('planning_mode'),'review_status':grounding.get('status'),
                    'tools':calls,'agent_execution':grounding.get('agent_execution'),'usage':grounding.get('usage'),
                    'stream_has_agent_events':'event: agent\n' in response.text,'validated':final.get('genui',{}).get('validated')}
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
            assert final['status']=='complete' and report['validated'] and report['planning_mode']=='agent_tool_loop',report['error']
            assert calls.count('list_files')==1 and 'research_complete' in calls and report['review_status']=='checked'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.parse_args()
    check()
