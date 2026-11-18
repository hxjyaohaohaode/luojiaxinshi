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
                    if kind=='preview' and value.get('text','').strip():
                        elapsed=round(time.monotonic()-started,3)
                        self.timeline.setdefault('first_text_seconds',elapsed)
                        if model_step:first_text_by_step.setdefault(model_step,elapsed)
                    if kind=='agent' and value.get('kind')=='source.checked' and value.get('data',{}).get('observation',{}).get('quote'):
                        self.timeline.setdefault('first_source_excerpt_seconds',round(time.monotonic()-started,3))
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


def check(case='files', output_name=None, max_provider_requests=None):
    if max_provider_requests is None and case=='team_review':max_provider_requests=8
    if max_provider_requests is not None and max_provider_requests<0:raise ValueError('Request allowance must be nonnegative')
    output=ROOT/'artifacts'/(output_name or ('agent-adaptive-live' if case=='files' else 'agent-adaptive-live-'+case));output.mkdir(parents=True,exist_ok=True)
    prompts={
        'files':PROMPT,
        'agenda_plan':'请核对我 2027-03-02 上午的日历，看看哪些已保存的安排撞在一起，重叠多久？11:00 之后还能在上午安排一段连续 30 分钟的复盘吗？给出理由和建议时间，只需分析。',
        'travel_ui':'请帮我做一个可以操作的行程比较。合成的两种步行方案分别是 12 分钟和 20 分钟，09:00 出发。让我输入第一条路等待的分钟数，立即看到两条路到达的钟点和哪条更早，打平也要准确。让计算、路程示意图和简短文字自然接在一起，手机上可以直接改。',
        'paint_mix':'我想在手机上试算一个配色配方。合成条件：蓝色与白色用量比为 3 比 2，初始总量 50 克。请让我输入任意非负总克数，立即看到两种颜色各要多少克，用图形表现比例。0 克也能输入，空白或负数要指出原因并清掉旧结果。只用题中条件。',
        'direct':'用两句话解释什么是中位数，再给一个短例子。',
        'continuation':'接着刚才的合成草案，只改第二项的时长为45分钟。请列出两项的名称和当前时长。',
        'mixed_layout':'制作一个可以操作的图文互动答复。合成小组在4天内每天读6页，公式为总页数＝天数×每天页数。请绘制阅读进度示意图，展示公式，用一个可编辑输入改变天数并立即更新总页数。只用题中这些数值，以自然的文档布局连接图、公式和计算。',
        'ui':'仅用本条消息：这是一项工程测试，不是真实通知。演示活动在2026年11月3日18:00截止，需要报名表和课程截图。请先突出截止时间，再做可勾选的材料清单，原文说明按需展开。不联网，不写文件，不用模板。',
        'openui':'仅用本条消息：这是隔离的合成工程验收，没有真实学校活动。请用自由生成的 HTML/CSS/JS 制作中文准备时间工具：每天2小时、准备7天，合计14小时。需要 hours 滑块（0.5至8，步长0.5）、days 数字输入（1至30的整数）、total 输出；改变输入立即重算，空值或无效天数显示具体错误并清除旧结果。包含“按当前条件继续分析”按钮，点击时必须通过 CampusUI.sendPrompt 在本聊天发起下一轮，携带当前小时、天数与合计；不要添加本地分析文案或其他换算。自行设计布局和样式，保持简洁，适应手机。代码字段流式输出。不联网、不写文件、不创建待办或日历、不保存记忆。',
        'notice_compare':'这是合成校园资料。请把这两份附件做成一个可以操作的通知更正对照，让我能在“只看变化”和“全部条目”之间切换，选中变化能看原文与更正依据。让差异本身一眼可读；全部条目包括未变的参与年级。请自行设计界面。仅用本次材料，不联网，不写入待办、日历或记忆。',
        'prep_timeline':'这是合成资料。请做一个可直接拖动的个人准备时间轴，横轴从09:00到12:00。拟稿从09:00开始用30分钟，核对从10:00开始用30分钟，整理从11:00开始用15分钟。拖动任务块能以15分钟为步长调整开始时间，并就地更新该任务的起止时间。键盘也能移动任务。刷新时保留我已保存的选择。请自行设计界面；只做个人试排，不联网，不写入待办、日历或记忆。',
        'conflict':'仅用本条消息，纯文字作答。这是合成工程资料：同一演示活动的通知甲写“11月3日18:00截止”，通知乙写“11月3日16:00截止”。两份材料都没有发布时间、版本号或替代说明。告诉我这项活动的最终截止时间，说明依据。',
        'team_review':'请联合核对三份合成材料。说明正式截止时间、申请年级、需要的材料和提交渠道，判断群内转述能否替代正式通知；给出下一步。仅用附件，不联网，不创建待办。用纯文字回答。',
        'research':'请结合本次附件帮我把这次申请理清楚，我现在先做什么？用文字答复，只用本次会话材料，不联网，不写入待办或日历。',
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
            if case=='agenda_plan':
                for title,day,start,end,repeat in (
                    ('合成研讨','2027-02-23','09:00','10:30','weekly'),
                    ('合成实验','2027-03-02','10:00','11:00','none'),
                    ('合成交接','2027-03-02','11:00','11:30','none')):
                    client.post('/api/arrangements',json={'request_id':ident(),'data':{
                        'title':title,'start_date':day,'end_date':day,'start_time':start,'end_time':end,
                        'repeat':repeat,'repeat_until':'2027-03-09' if repeat=='weekly' else None}}).raise_for_status()
            if case=='continuation':
                with app.state.db.connect(write=True) as conn:
                    parent=ident(); now=int(time.time())
                    conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",
                                 (parent,chat['id'],'给合成小组排两项：初读20分钟、复核30分钟。',now-50))
                    conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at) VALUES(?,?,'assistant',?,'complete',?,?)",
                                 (ident(),chat['id'],'先初读20分钟，然后复核30分钟。',parent,now-45))
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
            if case in ('research','notice_compare','team_review'):
                notices={
                    '申请通知.txt':'合成校园事项。参与对象为二年级学生。申请人需准备签字申请表和成绩单，截止时间为11月3日18:00。提交渠道另行通知。',
                    '办理群转述.txt':'合成群内转述，未经发布方确认。有人说同一申请截止时间是11月3日16:00，未提供正式更正文件。'}
                if case=='team_review':
                    notices={'发布方原通知.txt':'合成读书项目原通知。对象为二年级学生。申请表需签字，另交成绩单。原截止时间为2027年4月10日17:00。提交到文科楼201室。',
                             '正式补充通知.txt':'合成项目发布方正式补充通知。替代原截止时间，现延至2027年4月12日12:00；提交改为教学楼305室。参与对象和申请材料没有变化。',
                             '群内消息.txt':'合成群内转述，有人称4月13日18:00也能补交，没有发布方确认或正式文件。'}
                if case=='notice_compare':
                    notices={'活动原通知.txt':'合成活动原通知。参与对象为二年级学生。截止时间为11月23日17:00，材料交到文科楼201室。',
                             '正式更正.txt':'合成发布方正式更正，替代原通知的截止时间与地点。截止时间改为11月24日12:00，地点改为文科楼305室。参与对象仍为二年级学生。'}
                for name,body in notices.items():
                    uploaded=client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':(name,body.encode(),'text/plain')})
                    uploaded.raise_for_status();chat=uploaded.json()
            started=time.monotonic()
            from unittest.mock import patch
            import httpx
            send_http=httpx.AsyncClient.send
            requests_made=[]
            async def meter(session,request,**kwargs):
                if str(request.url).startswith(settings.ai_base_url.rstrip('/')+'/') and request.url.path.endswith('/chat/completions'):
                    if max_provider_requests and len(requests_made)>=max_provider_requests:
                        from app.ai import AIBudgetError
                        raise AIBudgetError('合成验收已到本次设定的模型请求上限')
                    requests_made.append(round(time.monotonic()-started,3))
                return await send_http(session,request,**kwargs)
            with patch.object(httpx.AsyncClient,'send',meter):
                response=client.post('/api/conversations/'+chat['id']+'/messages/stream',json={'version':chat['version'],
                    'content':prompts[case],'reading_width':'compact' if case in ('paint_mix','travel_ui') else None,'request_id':ident(),'allow_external_processing':True,'allow_decision_routing':case in ('direct','research','continuation','mixed_layout','team_review','travel_ui','paint_mix','agenda_plan')})
            response.raise_for_status()
            final=client.get('/api/conversations/'+chat['id']).json()['messages'][-1]
            with app.state.db.connect() as conn:
                calls=[json.loads(r['data'])['tool'] for r in conn.execute("SELECT data FROM agent_events WHERE type='tool.completed'")]
            grounding=final.get('grounding',{})
            with app.state.db.connect() as conn:
                trace=[json.loads(r['body']) for r in conn.execute('SELECT body FROM agent_messages ORDER BY rowid')]
            (output/'synthetic-transcript.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
            report={'synthetic_input':True,'synthetic_question':prompts[case],'route':'/api/conversations/{cid}/messages/stream','model':settings.ai_model,
                    'elapsed_seconds':round(time.monotonic()-started,2),'status':final['status'],'error':final['error'],
                    'answer':final.get('genui',{}).get('raw',final['content']),
                    'interactive_blocks':sum(p['kind']=='ui' for p in final.get('parts',[])),
                    'planning_mode':grounding.get('planning_mode'),'decision':grounding.get('decision'),'models':grounding.get('models'),'review_status':grounding.get('status'),
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
            report['max_provider_requests']=max_provider_requests
            report['actual_mimo_request_starts']=requests_made
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
            assert final['status']=='complete' and report['validated'],report['error']
            if case=='direct':
                assert report['planning_mode']=='adaptive_direct' and report['review_status']=='checked' and '中位数' in report['answer']
                return report
            assert report['planning_mode']=='agent_tool_loop',report['planning_mode']
            if case=='team_review':
                readers=report['agent_execution']['parallel_review']['assignments']
                assert len(readers)==3 and all(r['status']=='completed' and r['verified_quotes'] for r in readers),readers
                assert max(r['start_ms'] for r in readers)<min(r['end_ms'] for r in readers)
                assert all(term in report['answer'] for term in ('二年级','成绩单','申请表','305','12:00'))
                assert len(grounding['work_summary']['cited_sources'])>=2
                assert not max_provider_requests or len(requests_made)<=max_provider_requests
            if case=='continuation':
                assert all(term in report['answer'] for term in ('20','45','初读','复核'))
            if case=='agenda_plan':
                assert 'workspace_read' in calls and all(value in report['answer'] for value in ('10:00','10:30','11:30'))
                assert '30' in report['answer'] and not final.get('agent',{}).get('operations')
            if case=='paint_mix':
                assert report['openui_blocks']==1 and report['stream_has_ui_preview']
                assert grounding['work_summary']['verified'] and not final.get('agent',{}).get('operations')
            if case=='travel_ui':
                assert report['openui_blocks']==1 and report['stream_has_ui_preview']
            if case=='mixed_layout':
                assert report['openui_blocks'] and '24' in report['answer']
            assert (case!='files' or calls.count('list_files')==1) and 'research_complete' not in calls and report['review_status']=='checked'
            if case in ('ui','openui','notice_compare','prep_timeline'):
                assert grounding['work_summary']['ui_components'] and report['interactive_blocks']
                assert all(p['spec']['complete'] and not p['spec']['errors'] for p in final['parts'] if p['kind']=='ui')
            if case in ('openui','notice_compare','prep_timeline'):
                assert report['openui_blocks']==1 and report['stream_has_ui_preview']
                assert 'generateSandboxedUi' in calls or 'compose_interface' in calls
            assert grounding['agent_execution']['answer_in_loop']
            if case=='conflict':
                assert '16:00' in report['answer'] and '18:00' in report['answer']
                assert any(word in report['answer'] for word in ('无法','不能','不确定','冲突','确认'))
            if case=='research':
                assert all(word in report['answer'] for word in ('成绩单','申请表','二年级','18:00','16:00'))
                assert any(word in report['answer'] for word in ('渠道','入口','方式'))
                assert any(word in report['answer'] for word in ('转述','群','传言'))
                assert not final.get('agent',{}).get('operations') and 'public_search' not in calls
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
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.add_argument('--case',choices=['files','agenda_plan','travel_ui','paint_mix','direct','continuation','mixed_layout','team_review','ui','openui','review','conflict','research','notice_compare','prep_timeline','clarify','memory','visual','timetable','mixed','workspace'],default='files');parser.add_argument('--output-name');parser.add_argument('--max-provider-requests',type=int,help='Override the synthetic request allowance (0 uses the normal runtime budget)');args=parser.parse_args()
    check_review() if args.case=='review' else check(args.case,args.output_name,args.max_provider_requests)
