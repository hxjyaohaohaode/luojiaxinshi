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
REVIEW_GATE=os.getenv('OPENUI_REVIEW_GATE')=='1'
review_gate=asyncio.Event()
review_gate.set()
if REVIEW_GATE:
    from pydantic import BaseModel,ConfigDict

    class ReviewGate(BaseModel):
        model_config=ConfigDict(extra='forbid')
        hold:bool

    @app.post('/api/fixture/review-gate')
    async def control_review_gate(payload:ReviewGate):
        if payload.hold:review_gate.clear()
        else:review_gate.set()
        return {'synthetic':True,'held':not review_gate.is_set()}
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
    if REVIEW_GATE:
        await asyncio.wait_for(review_gate.wait(),timeout=45)
    else:
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


def seed_published_replays(conn, owner, directories):
    """Load actual, verified synthetic replies unchanged into this loopback test database."""
    from app.conversation_tools import select_reply
    from app.genui_api import message_parts
    for dirname in directories.split(os.pathsep):
        directory=Path(dirname).resolve()
        if not directory.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Replay outside synthetic artifacts')
        report=json.loads((directory/'results.json').read_text(encoding='utf-8'))
        if not (report['synthetic_input'] and report['validated'] and report['status']=='complete'):raise ValueError('Expected verified synthetic reply')
        trace=json.loads((directory/'synthetic-transcript.json').read_text(encoding='utf-8'))
        question=report.get('synthetic_question') or next(m['content'] for m in trace if m['role']=='user')
        program=json.loads((directory/'generated-ui.json').read_text(encoding='utf-8'))
        raw=report['answer']
        if report.get('repair_history') and '\n```openui' in raw:
            from app.openui import reader_lead
            lead,canvas=raw.split('\n```openui',1)
            raw=reader_lead(lead)+'\n```openui'+canvas
        parts=message_parts(raw,1,True,settings.genui_limits,{})
        if not any(p.get('spec',{}).get('sandbox')==program for p in parts):raise ValueError('Published reply and authored artifact differ')
        sources={'user-input':{'id':'user-input','name':'本轮合成问题','evidence_kind':'user_input','sections':[{'locator':'当前问题','text':question}]}}
        for item in trace:
            if item['role']!='tool':continue
            receipt=json.loads(item['content'])
            if receipt.get('source_id') and receipt.get('sections'):
                sid=receipt['source_id']
                sources[sid]={'id':sid,'name':receipt['name'],'evidence_kind':'material','sections':receipt['sections']}
        ordered=[sources[sid] for sid in report['work_summary']['cited_sources']]
        citations=[{'source_id':src['id'],'name':src['name'],'locator':src['sections'][0]['locator'],'quote':src['sections'][0]['text']} for src in ordered]
        cid,parent,mid,now=ident(),ident(),ident(),int(time.time())
        dumps=lambda value:json.dumps(value,ensure_ascii=False)
        conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,owner,program['title'],now,now))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user',?,'complete',?)",(parent,cid,question,now))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,citations,created_at) VALUES(?,?,'assistant',?,'complete',?,?,?)",(mid,cid,raw.split('```openui')[0].strip(),parent,dumps(citations),now))
        conn.execute('INSERT INTO genui_messages(message_id,raw,parts,tier,validated,updated_at) VALUES(?,?,?,1,1,?)',(mid,raw,dumps(parts),now))
        conn.execute('INSERT INTO reply_grounding(message_id,sources,report) VALUES(?,?,?)',(mid,dumps(ordered),dumps({'status':report['review_status'],'work_summary':report['work_summary']})))
        select_reply(conn,mid)

with app.state.db.connect(write=True) as conn:
    row=conn.execute("SELECT id FROM users WHERE username='openui-preview'").fetchone()
    if not row:
        uid=ident()
        conn.execute('INSERT INTO users(id,username,password,display_name,role,profile,created_at) VALUES(?,?,?,?,?,?,?)',
                     (uid,'openui-preview',hash_password('OpenUIFixture2026!'),'生成式界面验收','user','{"memory_enabled":false}',int(time.time())))
    else:uid=row['id']
    record_consent(conn,uid)
    if directories:=os.getenv("OPENUI_PUBLISHED_REPLAYS"):seed_published_replays(conn,uid,directories)

if __name__=='__main__':
    import uvicorn
    print('OpenUI synthetic agent streaming fixture, port 8794.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
