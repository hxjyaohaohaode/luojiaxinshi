"""Real application + streamed synthetic agent arguments. No paid providers."""
import asyncio
import json
import os
import re
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app import grounding, genui_ai
from app.config import Settings
from app.main import create_app
from app.db import ident
from app.security import hash_password
from app.account import record_consent

PORT=8794
DATA=Path(os.getenv('OPENUI_PREVIEW_DATA_DIR',ROOT/'artifacts/openui-browser/data')).resolve()
if not DATA.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('OpenUI synthetic data must stay under artifacts/.')
DATA.mkdir(parents=True,exist_ok=True)
settings=Settings(DATA,origin=f'http://127.0.0.1:{PORT}',ai_api_key='synthetic-no-network',
                  ai_model='offline-openui-fixture',ai_daily_limit=10000,agent_enabled=True,ai_grounding=True)
app=create_app(settings)
replay=os.getenv('OPENUI_REPLAY_FILE','')
if replay:
    replay_path=Path(replay).resolve()
    if not replay_path.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Replay must be a synthetic artifact under artifacts/.')
    UI=json.loads(replay_path.read_text(encoding='utf-8'))
else:UI=json.loads((ROOT/'fixtures/genui/openui-planner.json').read_text(encoding='utf-8'))


class FixtureProvider:
    kind='mimo'
    model='synthetic-openui-stream'
    async def complete(self,messages,tools):return await self.complete_stream(messages,tools,lambda *_:None)
    async def complete_stream(self,messages,tools,on_text,*,on_answer_arguments=None):
        last=next((m['content'] for m in reversed(messages) if m['role']=='user'),'')
        if '界面选择' in last:
            name='submit_answer'
            args={'answer':'【合成验收回复】已收到当前准备时间与材料进度。','claims':[{'kind':'interface','text':'当前选择由用户主动提交'}]}
        else:
            name='generateSandboxedUi'
            args={**UI,'lead':'按可用时间安排准备工作。','claims':[{'kind':'interface','text':'输入会更新当前试算结果'}]}
            if 'compose_interface' in {t['function']['name'] for t in tools}:name,args='compose_interface',{'brief':'显示准备时间和材料清单，允许本地调整与继续提问。'}
            elif name not in {t['function']['name'] for t in tools}:name,args='openui_capabilities',{}
        if name not in {t['function']['name'] for t in tools}:raise RuntimeError('Required fixture tool is unavailable: '+name)
        raw=json.dumps(args,ensure_ascii=False)
        if on_answer_arguments:
            for i in range(0,len(raw),90):
                on_answer_arguments(raw[i:i+90])
                await asyncio.sleep(.04)
        return {'role':'assistant','content':'','tool_calls':[{'id':ident(),'type':'function','function':{'name':name,'arguments':raw}}]}, {'prompt_tokens':20,'completion_tokens':80}


app.state.agent_service.provider_factory=lambda *_:FixtureProvider()

async def review(settings,result,sources,question,context):
    await asyncio.sleep(float(os.getenv('OPENUI_REVIEW_DELAY','1.2')))
    return [],{},grounding.check_result(result,sources)

async def fixture_writer(_settings,sources,_messages,profile,_tier):
    from app.openui import UIStreamDecoder,encode_ui
    ui=json.loads(json.dumps(UI));refs=[]
    if replay:
        # Published artifacts use display numbers. Rehydrate the current
        # synthetic request's evidence before the normal compiler resolves
        # them again. Keep the authored CSS/JS and final HTML unchanged.
        entries=genui_ai.authoring_index(sources,profile)
        user_ids={s['id'] for s in sources if s.get('evidence_kind')=='user_input'}
        ref=next(e['ref'] for e in entries if e['source_id'] in user_ids)
        ui['html']=[re.sub(r'\[1\]','['+ref+']',part) for part in ui['html']]
        refs=[ref]
    value={'answer':'按可用时间安排准备工作。','ui':ui,'claims':[{'kind':'interface','text':'输入会更新当前试算结果','evidence_refs':refs}]}
    raw=json.dumps(value,ensure_ascii=False);decoder=UIStreamDecoder()
    yield {'type':'preview','text':value['answer']}
    for i in range(0,len(raw),90):
        packet=decoder.packet(raw[i:i+90])
        if packet:yield {'type':'ui_preview','content':packet}
        await asyncio.sleep(.04)
    yield {'type':'complete','result':{'answer':value['answer']+encode_ui(ui),'citations':[],'image_sources':[]},'repair_draft':raw,'usage':{}}

grounding.verify=review
genui_ai.stream_reply=fixture_writer
with app.state.db.connect(write=True) as conn:
    row=conn.execute("SELECT id FROM users WHERE username='openui-preview'").fetchone()
    if not row:
        uid=ident()
        conn.execute('INSERT INTO users(id,username,password,display_name,role,profile,created_at) VALUES(?,?,?,?,?,?,?)',
                     (uid,'openui-preview',hash_password('OpenUIFixture2026!'),'生成式界面验收','user','{"memory_enabled":false}',int(time.time())))
    else:uid=row['id']
    record_consent(conn,uid)

if __name__=='__main__':
    import uvicorn
    print('OpenUI synthetic agent streaming fixture, port 8794.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
