"""Loopback-only browser/SDK fixture. Never opens the live data directory or provider."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app import genui_ai, grounding
from app.account import record_consent
from app.db import ident
from app.main import create_app
from app.security import hash_password

PORT = 8793
DATA = Path(os.getenv('AGENT_PREVIEW_DATA_DIR', ROOT / 'artifacts' / 'agent-runtime-preview')).resolve()
if not DATA.is_relative_to((ROOT / 'artifacts').resolve()):
    raise ValueError('Synthetic Agent data must stay under artifacts/.')
settings = Settings(DATA, origin=f'http://127.0.0.1:{PORT}', ai_api_key='synthetic-no-network',
                    ai_grounding=True, notice_semantic_review=False, ai_daily_limit=1000)
app = create_app(settings)


def fixture_checklist():
    return {'title':'本次准备','preferredWidth':690,'css':'fieldset{display:grid;gap:12px} details{margin-block:14px}',
            'html':['<fieldset><legend>准备材料</legend><label><input type="checkbox" id="form">报名表</label>'
                    '<label><input type="checkbox" id="schedule">课程截图</label></fieldset>',
                    '<details><summary>演示原文与核对项</summary><p>演示活动在 2026 年 11 月 3 日 18:00 截止。提交入口和资格条件尚未提供。</p></details>']}


class FixtureProvider:
    model = 'synthetic-agent-fixture'

    async def complete(self, messages, tools):
        await asyncio.sleep(.12)
        user = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
        if isinstance(user,list):user='\n'.join(p.get('text','') for p in user if p.get('type')=='text')
        if '日历待办验收' in user:
            used=[c['function']['name'] for m in messages for c in m.get('tool_calls',[])]
            if 'workspace_capabilities' not in used:
                calls=[('workspace_capabilities',{})]
            elif 'calendar_write' not in used:
                calls=[('calendar_write',{'operation':'create','data':{'title':'工程测试：项目讨论','start_date':'2027-10-23','end_date':'2027-10-23','start_time':'09:00','end_time':'10:00'}}),
                       ('task_write',{'operation':'create','fields':{'title':'工程测试：准备报告','planned_at':'2027-10-22T16:00:00+08:00'}})]
            else:
                refs=[e['ref'] for m in messages if m['role']=='tool' for e in json.loads(m['content']).get('evidence_index',[]) if e.get('source_id','').startswith('workspace-')]
                calls=[('submit_answer',{'answer':'已添加项目讨论，并创建报告准备待办。','claims':[{'kind':'fact','text':'已添加项目讨论，并创建报告准备待办。','evidence_refs':refs}]})]
            return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}} for name,args in calls]},{}
        if any(key in user for key in ('融合媒体验收','排版验收')):
            tools_available={t['function']['name'] for t in tools}
            if 'openui_capabilities' in tools_available:
                name,args='openui_capabilities',{}
            elif 'generateSandboxedUi' in tools_available:
                if '融合媒体验收' in user:
                    discovery=next(json.loads(m['content']) for m in reversed(messages) if m['role']=='tool' and 'resources' in m['content'])
                    video=next(item for item in discovery['resources'] if item['kind']=='video')
                    ui={'title':'视频原件','preferredWidth':720,'css':'video{display:block;width:100%;aspect-ratio:16/9}',
                        'html':[f'<video controls data-material="{video["id"]}" aria-label="上传的视频"></video>']}
                else:ui=fixture_checklist()
                name,args='generateSandboxedUi',{'renderer':'open_generative_ui','lead':'以下是本次合成材料。',**ui,
                    'claims':[{'kind':'interface','text':'呈现本轮用户提供的材料'}]}
            else:name,args='compose_interface',{'brief':user}
            return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]},{}
        chat = any(t['function']['name'] == 'research_complete' for t in tools)
        if messages[-1]['role'] == 'tool':
            if chat:
                name,arguments='research_complete',{'web_reason':'离线工程测试','presentation':'text'}
                result={'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]}
            else:
                result = {'role':'assistant','content':'【合成验收回复】已完成本次工具流程。这是离线工程夹具。'}
        else:
            name, arguments = ('write_file', {'path':'材料清单-'+uuid.uuid4().hex[:8]+'.md','content':'# 合成材料清单\n\n- 核对通知原文\n- 准备报名表\n\n本文件仅用于工程验收。'}) if '审批' in user else ('campus_search',{'query':user[:500],**({'scopes':[]} if chat else {})})
            result = {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(arguments,ensure_ascii=False)}}]}
        return result, {'prompt_tokens':20,'completion_tokens':10}


app.state.agent_service.provider_factory = lambda *_: FixtureProvider()


async def fixture_writer(settings, sources, messages, profile, tier):
    if profile.get('_ui_composition_only'):
        from app.openui import encode_ui
        if '融合媒体验收' in str(messages):
            from app.chat_media import resource_index
            source=next(item for item in resource_index(sources) if item['kind']=='video')
            ui={'title':'视频原件','preferredWidth':720,'css':'video{display:block;width:100%;aspect-ratio:16/9}',
                'html':[f'<video controls data-material="{source["id"]}" aria-label="上传的视频"></video>']}
        else:ui=fixture_checklist()
        ui={'renderer':'open_generative_ui',**ui}
        draft={'answer':'以下是本次合成材料。','ui':ui,'claims':[{'kind':'interface','text':'呈现本轮合成材料'}]}
        yield {'type':'complete','result':{'answer':draft['answer']+encode_ui(ui),'citations':[],'image_sources':[]},'repair_draft':json.dumps(draft,ensure_ascii=False),'usage':{}}
        return
    text='【合成验收回复】你提供的要求是：'
    source=next(s for s in sources if s['evidence_kind']=='user_input');part=source['sections'][0]
    result={'answer':text+part['text']+'[1]','citations':[{'source_id':source['id'],'locator':part['locator'],'quote':part['text']}],
            'image_sources':[],'claims':[{'kind':'fact','text':part['text'],'citation_indices':[1]}]}
    yield {'type':'complete','result':result,'usage':{}}


async def fixture_review(settings, result, sources, question, context):
    return [],{},grounding.check_result(result,sources)


genui_ai.stream_reply=fixture_writer
grounding.verify=fixture_review
with app.state.db.connect(write=True) as conn:
    if not conn.execute("SELECT 1 FROM users WHERE username='agent-preview'").fetchone():
        conn.execute('INSERT INTO users(id,username,password,display_name,role,profile,created_at) VALUES(?,?,?,?,?,?,?)',
                     (ident(),'agent-preview',hash_password('AgentPreviewFixture2026!'),'合成验收账号','user','{}',int(time.time())))
    # 合成账号直接写库，不经过注册页；按已同意当前版本的隐私政策与用户协议处理，否则登录后会弹出同意框挡住操作。
    record_consent(conn, conn.execute("SELECT id FROM users WHERE username='agent-preview'").fetchone()[0])


if __name__ == '__main__':
    import uvicorn
    print('Agent engineering fixture: synthetic responses only, port 8793.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
