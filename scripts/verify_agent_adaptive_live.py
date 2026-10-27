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


class StreamTimeline:
    """Record actual ASGI event emission times; never log bodies or credentials."""
    def __init__(self,app,timeline):self.app,self.timeline=app,timeline
    async def __call__(self,scope,receive,send):
        if scope.get('type')!='http' or not scope.get('path','').endswith('/messages/stream'):
            return await self.app(scope,receive,send)
        started=time.monotonic()
        model_step=0
        first_text_by_step={}
        async def timed(message):
            nonlocal model_step
            body=message.get('body',b'')
            if message['type']=='http.response.body':
                for frame in body.decode('utf-8').split('\n\n'):
                    fields=dict(line.split(': ',1) for line in frame.splitlines() if ': ' in line)
                    if 'data' not in fields:continue
                    value=json.loads(fields['data']);kind=fields.get('event')
                    if kind=='agent' and value.get('kind')=='model.started' and value.get('data',{}).get('agent_id')=='root':model_step+=1
                    if kind=='preview':
                        elapsed=round(time.monotonic()-started,3)
                        self.timeline.setdefault('first_text_seconds',elapsed)
                        if model_step:first_text_by_step.setdefault(model_step,elapsed)
                    if kind=='done' and first_text_by_step:
                        self.timeline['last_model_first_text_seconds']=first_text_by_step[max(first_text_by_step)]
            if message['type']=='http.response.body' and b'event: ui_preview\n' in body:
                for line in body.decode('utf-8').splitlines():
                    if not line.startswith('data: '):continue
                    content=json.loads(line[6:]).get('content',{})
                    if any(part.get('text') for part in content.get('html',[])):
                        self.timeline.setdefault('first_html_seconds',round(time.monotonic()-started,3))
                    if content.get('localReady'):
                        self.timeline.setdefault('local_controls_seconds',round(time.monotonic()-started,3))
            await send(message)
        await self.app(scope,receive,timed)


def check(case='files', output_name=None):
    output=ROOT/'artifacts'/(output_name or ('agent-adaptive-live' if case=='files' else 'agent-adaptive-live-'+case));output.mkdir(parents=True,exist_ok=True)
    prompts={
        'files':PROMPT,
        'ui':'仅用本条消息：这是一项工程测试，不是真实通知。演示活动在2026年11月3日18:00截止，需要报名表和课程截图。请先突出截止时间，再做可勾选的材料清单，原文说明按需展开。不联网，不写文件，不用模板。',
        'openui':'仅用本条消息：这是隔离的合成工程验收，没有真实学校活动。请用自由生成的 HTML/CSS/JS 制作中文准备时间工具：每天2小时、准备7天，合计14小时。需要 hours 滑块（0.5至8，步长0.5）、days 数字输入（1至30的整数）、total 输出；改变输入立即重算，空值或无效天数显示具体错误并清除旧结果。包含“按当前条件继续分析”按钮，点击时必须通过 CampusUI.sendPrompt 在本聊天发起下一轮，携带当前小时、天数与合计；不要添加本地分析文案或其他换算。使用已注入的共享设计系统，保持简洁，适应手机。代码字段流式输出。不联网、不写文件、不创建待办或日历、不保存记忆。',
        'conflict':'仅用本条消息，纯文字作答。这是合成工程资料：同一演示活动的通知甲写“11月3日18:00截止”，通知乙写“11月3日16:00截止”。两份材料都没有发布时间、版本号或替代说明。告诉我这项活动的最终截止时间，说明依据。',
        'clarify':'仅用本条消息，这是合成工程测试，没有真实账户或活动资料。帮我完成报名。请用一句话回复。',
        'memory':'我长期用中文写报告，所有项目都习惯先看结论再看依据。请用纯文字简短回复，不联网。',
        'visual':'帮我看看这张作业图，我接下来应该做什么？这是工程测试，只用本次材料，不联网、不保存长期记忆。',
        'timetable':'你看看这个课表的内容。',
        'mixed':'帮我看这批工程测试材料，整理能马上开始的准备顺序。不要漏掉后面的图片、音频和视频；无法理解的内容如实说明。不联网、不保存长期记忆。',
        'workspace':'这是隔离工程验收。先告诉我现在的完整日期和年份，再直接创建明天上午9点至10点的日历安排“工程测试项目讨论”，并创建明天下午4点“工程测试准备报告”的个人待办。不要联网，不读取资料库，不保存长期记忆。用简短文字报告实际执行结果。',
    }
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=output) as folder:
        settings=replace(Settings.from_env(),data_dir=Path(folder),origin='http://127.0.0.1:8794',ai_daily_limit=12,
                         agent_enabled=True,ai_grounding=True,notice_semantic_review=False,agent_mcp_servers={},agent_sandbox_image='')
        app=create_app(settings)
        stream_timeline={};app.add_middleware(StreamTimeline,timeline=stream_timeline)
        with app.state.db.connect(write=True) as conn:
            conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',(ident(),'synthetic-agent',hash_password('SyntheticOnly2026!'),'工程验收','user','{}',int(time.time())))
        with TestClient(app,base_url=settings.origin) as client:
            client.headers.update({'Origin':settings.origin,'X-Requested-With':'campus-notice'})
            client.post('/api/auth/login',json={'username':'synthetic-agent','password':'SyntheticOnly2026!'}).raise_for_status()
            client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
            chat=client.post('/api/conversations',json={'title':'原聊天 Agent 合成验收'}).json()
            if case in ('visual','mixed','timetable'):
                import io
                from PIL import Image,ImageDraw,ImageFont
                count=6 if case=='mixed' else 1
                for index in range(count):
                    picture=Image.new('RGB',(640,300),'white');draw=ImageDraw.Draw(picture)
                    text=('SYNTHETIC TIMETABLE - NOT A REAL STUDENT\nWeek 8, October 25-31, 2026\nMonday 14:00-15:30: Data Mining, Room A101\nTuesday 09:00-10:30: Java, Room B202\nThursday 08:00-09:30: Systems Design, A103\nOther days: no entries shown' if case=='timetable' else f'ENGINEERING TEST - PAGE {index+1}\nBuild a reading website\nRequired: login, search, book list\nSubmit: source code + short report\nDeadline: October 31 (year not stated)')
                    draw.multiline_text((25,30),text,fill='black',font=ImageFont.load_default(size=20 if case=='timetable' else 23),spacing=13)
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
            report['stream_has_ui_preview']='event: ui_preview\n' in response.text
            report['openui_blocks']=sum(p['kind']=='ui' and bool(p['spec'].get('sandbox')) for p in final.get('parts',[]))
            if report['openui_blocks']:
                authored=next(p['spec']['sandbox'] for p in final['parts'] if p['kind']=='ui' and p['spec'].get('sandbox'))
                (output/'generated-ui.json').write_text(json.dumps(authored,ensure_ascii=False,indent=2),encoding='utf-8')
            report['case']=case
            report['stream_timeline']=stream_timeline
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
                         if c['function']['name'] in ('submit_answer','submit_interface','generateSandboxedUi')]
            report['claims']=submissions[-1].get('claims',[]) if submissions else []
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
            assert final['status']=='complete' and report['validated'] and report['planning_mode']=='agent_tool_loop',report['error']
            assert (case!='files' or calls.count('list_files')==1) and 'research_complete' not in calls and report['review_status']=='checked'
            if case in ('ui','openui'):
                assert grounding['work_summary']['ui_components'] and report['interactive_blocks']
                assert all(p['spec']['complete'] and not p['spec']['errors'] for p in final['parts'] if p['kind']=='ui')
            if case=='openui':
                assert report['openui_blocks']==1 and report['stream_has_ui_preview']
                assert 'generateSandboxedUi' in calls or 'compose_interface' in calls
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
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.add_argument('--case',choices=['files','ui','openui','review','conflict','clarify','memory','visual','timetable','mixed','workspace'],default='files');parser.add_argument('--output-name');args=parser.parse_args()
    check_review() if args.case=='review' else check(args.case,args.output_name)
