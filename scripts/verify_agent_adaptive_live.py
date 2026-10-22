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


def check(case='files', output_name=None):
    output=ROOT/'artifacts'/(output_name or ('agent-adaptive-live' if case=='files' else 'agent-adaptive-live-'+case));output.mkdir(parents=True,exist_ok=True)
    prompts={
        'files':PROMPT,
        'ui':'仅用本条消息：这是一项工程测试，不是真实通知。演示活动在2026年11月3日18:00截止，需要报名表和课程截图。请先突出截止时间，再做可勾选的材料清单，原文说明按需展开。不联网，不写文件，不用模板。',
        'conflict':'仅用本条消息，纯文字作答。这是合成工程资料：同一演示活动的通知甲写“11月3日18:00截止”，通知乙写“11月3日16:00截止”。两份材料都没有发布时间、版本号或替代说明。告诉我这项活动的最终截止时间，说明依据。',
        'clarify':'仅用本条消息，这是合成工程测试，没有真实账户或活动资料。帮我完成报名。请用一句话回复。',
        'memory':'我长期用中文写报告，所有项目都习惯先看结论再看依据。请用纯文字简短回复，不联网。',
        'visual':'帮我看看这张作业图，我接下来应该做什么？这是工程测试，只用本次材料，不联网、不保存长期记忆。',
        'mixed':'帮我看这批工程测试材料，整理能马上开始的准备顺序。不要漏掉后面的图片、音频和视频；无法理解的内容如实说明。不联网、不保存长期记忆。',
        'workspace':'这是隔离工程验收。先告诉我现在的完整日期和年份，再直接创建明天上午9点至10点的日历安排“工程测试项目讨论”，并创建明天下午4点“工程测试准备报告”的个人待办。不要联网，不读取资料库，不保存长期记忆。用简短文字报告实际执行结果。',
    }
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
            if case in ('visual','mixed'):
                import io
                from PIL import Image,ImageDraw,ImageFont
                count=1 if case=='visual' else 6
                for index in range(count):
                    picture=Image.new('RGB',(640,300),'white');draw=ImageDraw.Draw(picture)
                    draw.multiline_text((25,30),f'ENGINEERING TEST - PAGE {index+1}\nBuild a reading website\nRequired: login, search, book list\nSubmit: source code + short report\nDeadline: October 31 (year not stated)',fill='black',font=ImageFont.load_default(size=23),spacing=13)
                    buffer=io.BytesIO();picture.save(buffer,format='PNG')
                    uploaded=client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':(f'page-{index+1}.png',buffer.getvalue(),'image/png')})
                    uploaded.raise_for_status();chat=uploaded.json()
                if case=='mixed':
                    sys.path.insert(0,str(ROOT/'tests'))
                    from media_fixtures import wav,mp4
                    for name,raw in [('tone.wav',wav()),('colors.mp4',mp4()),('notes.txt',b'Engineering test. Prepare the repository and a report outline first.')]:
                        uploaded=client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':(name,raw)})
                        uploaded.raise_for_status();chat=uploaded.json()
            started=time.monotonic()
            response=client.post('/api/conversations/'+chat['id']+'/messages/stream',json={'version':chat['version'],
                'content':prompts[case],'request_id':ident(),'allow_external_processing':True})
            response.raise_for_status()
            final=client.get('/api/conversations/'+chat['id']).json()['messages'][-1]
            with app.state.db.connect() as conn:
                calls=[json.loads(r['data'])['tool'] for r in conn.execute("SELECT data FROM agent_events WHERE type='tool.completed'")]
            grounding=final.get('grounding',{})
            with app.state.db.connect() as conn:
                trace=[json.loads(r['body']) for r in conn.execute('SELECT body FROM agent_messages ORDER BY rowid')]
            (output/'synthetic-transcript.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
            report={'synthetic_input':True,'route':'/api/conversations/{cid}/messages/stream','model':settings.ai_model,
                    'elapsed_seconds':round(time.monotonic()-started,2),'status':final['status'],'error':final['error'],
                    'answer':final.get('genui',{}).get('raw',final['content']),
                    'interactive_blocks':sum(p['kind']=='ui' for p in final.get('parts',[])),
                    'planning_mode':grounding.get('planning_mode'),'review_status':grounding.get('status'),
                    'harness':grounding.get('harness'),'work_summary':grounding.get('work_summary'),'tools':calls,'agent_execution':grounding.get('agent_execution'),'usage':grounding.get('usage'),
                    'review_issues':grounding.get('review_issues'),'repair_history':grounding.get('repair_history'),
                    'memory_operations':grounding.get('memory_operations',[]),
                    'stream_has_agent_events':'event: agent\n' in response.text,'validated':final.get('genui',{}).get('validated')}
            report['case']=case
            if case=='workspace':
                from app.agent_runtime.clock import current_time
                from datetime import date,timedelta
                arrangements=client.get('/api/arrangements').json();tasks=client.get('/api/tasks').json()
                report['operations']=final.get('agent',{}).get('operations',[])
                report['actual_arrangements']=arrangements;report['actual_tasks']=tasks
                report['clock']=current_time()
                (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                tomorrow=(date.fromisoformat(report['clock']['date'])+timedelta(days=1)).isoformat()
                assert len(arrangements)==1 and arrangements[0]['data']['start_date']==tomorrow
                assert arrangements[0]['data']['start_time']=='09:00' and arrangements[0]['data']['end_time']=='10:00'
                assert len(tasks)==1 and tasks[0]['data']['planned_at'].startswith(tomorrow+'T16:00')
                assert len(report['operations'])==2 and all(x['status']=='committed' for x in report['operations'])
                report['undo_statuses']=[client.post(f'/api/conversations/{chat["id"]}/agent/operations/{item["operation_id"]}/undo').status_code for item in report['operations']]
                assert report['undo_statuses']==[200,200]
            report['tool_errors']=[json.loads(r['content'])['error'] for r in trace if r.get('role')=='tool' and isinstance(json.loads(r['content']),dict) and json.loads(r['content']).get('error')]
            submissions=[json.loads(c['function']['arguments']) for m in trace for c in m.get('tool_calls',[])
                         if c['function']['name'] in ('submit_answer','submit_interface')]
            report['claims']=submissions[-1].get('claims',[]) if submissions else []
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
            assert final['status']=='complete' and report['validated'] and report['planning_mode']=='agent_tool_loop',report['error']
            assert (case!='files' or calls.count('list_files')==1) and 'research_complete' not in calls and report['review_status']=='checked'
            if case=='ui':
                assert grounding['work_summary']['ui_components'] and report['interactive_blocks']
                assert all(p['spec']['complete'] and not p['spec']['errors'] for p in final['parts'] if p['kind']=='ui')
            assert grounding['agent_execution']['answer_in_loop']
            if case=='conflict':
                assert '16:00' in report['answer'] and '18:00' in report['answer']
                assert any(word in report['answer'] for word in ('无法','不能','不确定','冲突','确认'))
            if case=='clarify':
                assert not any(tool in calls for tool in ('write_file','exec_command','mcp_call','spawn_agent'))
                assert any(word in report['answer'] for word in ('请','哪','提供','需要'))
            if case=='memory':
                assert 'memory_capabilities' in calls and 'ui_capabilities' not in calls
                assert report['memory_operations'] and not report['interactive_blocks']
                assert any(r['status'] in ('accepted','used','session_saved') for r in report['memory_operations'])
            return report


def check_review():
    import asyncio
    from app import grounding
    settings=Settings.from_env()
    source=grounding.source('synthetic','工程测试原句',[{'locator':'第1段','text':'演示事项于2026年11月3日18:00截止。'}],'material')
    candidate={'answer':'演示事项于2026年11月3日19:00截止。[1]',
               'citations':[{'source_id':source['id'],'locator':'第1段','quote':source['sections'][0]['text']}],
               'claims':[{'kind':'fact','text':'2026年11月3日19:00截止','citation_indices':[1]}],'image_sources':[]}
    started=time.monotonic()
    issues,usage,_=asyncio.run(grounding.verify(settings,candidate,[source],'核对演示截止时间。',{}))
    report={'synthetic':True,'elapsed_seconds':round(time.monotonic()-started,2),
            'review_options':grounding.review_options(settings,candidate,[source]),'rejected':bool(issues),'issues':issues,'usage':usage}
    output=ROOT/'artifacts/agent-adaptive-review';output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert issues,'The independent reviewer must reject a changed deadline even in the lower-latency mode'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.add_argument('--case',choices=['files','ui','review','conflict','clarify','memory','visual','mixed','workspace'],default='files');parser.add_argument('--output-name');args=parser.parse_args()
    check_review() if args.case=='review' else check(args.case,args.output_name)
