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


class FixtureProvider:
    model = 'synthetic-agent-fixture'

    async def complete(self, messages, tools):
        await asyncio.sleep(.12)
        user = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
        if isinstance(user,list):user='\n'.join(p.get('text','') for p in user if p.get('type')=='text')
        if '融合媒体验收' in user:
            if messages[-1]['role'] != 'tool':
                name, arguments = 'ui_capabilities', {'components':['Video']}
            else:
                available = json.loads(messages[-1]['content'])['host_data']['resources']
                index = next(i for i, value in enumerate(available) if value['kind'] == 'video')
                name, arguments = 'submit_interface', {'lead':'这是你上传的视频。', 'nodes':[
                    {'id':'clip','type':'Video','props':{'src':{'$ref':f'resources.{index}.src'},'label':'上传的视频'}}],
                    'claims':[{'kind':'interface','text':'播放本轮用户上传的视频，未分析内容'}]}
            return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(arguments,ensure_ascii=False)}}]},{}
        if '真实生成回放验收' in user:
            # Replay only the isolated, synthetic live-test output through the
            # original chat renderer. This never calls the paid provider.
            if messages[-1]['role'] != 'tool':
                name,arguments='ui_capabilities',{'components':['Checklist','Accordion','Callout','Markdown']}
            else:
                trace=json.loads((ROOT/os.environ.get('AGENT_UI_REPLAY_DIR','artifacts/agent-adaptive-live-ui')/'synthetic-transcript.json').read_text(encoding='utf-8'))
                submitted=[call for m in trace for call in m.get('tool_calls',[]) if call['function']['name'] in ('submit_answer','submit_interface')][-1]
                name,arguments=submitted['function']['name'],json.loads(submitted['function']['arguments'])
            return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':json.dumps(arguments,ensure_ascii=False)}}]},{}
        if '排版验收' in user:
            if messages[-1]['role'] != 'tool':
                return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':'ui_capabilities','arguments':json.dumps({'components':['Section','KeyValue','Checklist','Accordion','Markdown','Button']})}}]}, {'prompt_tokens':20,'completion_tokens':10}
            authored={'answer':'**先准备报名表和课程截图，再核对提交入口。**\n\n以下是你提供的演示信息，勾选只记录本次准备进度。',
                'ui':{'state':{'ready':[]},'nodes':[
                    {'id':'facts','type':'Section','props':{'surface':'soft'},'children':[
                        {'id':'key','type':'KeyValue','props':{'items':[{'label':'截止时间','value':'2026 年 11 月 3 日 18:00'},{'label':'待确认','value':'提交入口、资格条件'}]}}]},
                    {'id':'prepare','type':'Checklist','props':{'label':'准备材料','bind':'ready','items':[{'id':'form','label':'报名表','description':'检查必填项与签字'},{'id':'schedule','label':'课程截图','description':'核对时间和完整性'}]}},
                    {'id':'details','type':'Accordion','props':{'labels':['演示原文与核对项']},'children':[
                        {'id':'original','type':'Markdown','props':{'text':'演示材料：报名截止为 2026 年 11 月 3 日 18:00，需要报名表和课程截图。\n\n提交入口和资格条件尚未提供，需查阅原通知。'}}]},
                    {'id':'action','type':'Button','props':{'label':'添加通知原文','variant':'secondary'},'on':{'click':{'kind':'host','name':'upload_material','params':{}}}}
                ]},'claims':[{'kind':'interface','text':'清单用于本次准备进度'}]}
            return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':'submit_answer','arguments':json.dumps(authored,ensure_ascii=False)}}]}, {'prompt_tokens':20,'completion_tokens':60}
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


if __name__ == '__main__':
    import uvicorn
    print('Agent engineering fixture: synthetic responses only, port 8793.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
