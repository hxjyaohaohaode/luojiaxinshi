"""Isolated, synthetic browser scenarios. No .env, real data or provider calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from app import genui_ai,chat_ai
from app.ai import AIError
from app.config import Settings
from app.main import create_app
from app.security import new_invite
from scripts.synthetic_auth import verified_registration

PORT=int(os.getenv('DEEP_PREVIEW_PORT','8793'))
assert 1024<=PORT<=65535
DATA=Path(os.getenv('DEEP_PREVIEW_DATA',str(ROOT/'artifacts/deep-interaction-browser-data'))).resolve()
assert DATA.is_relative_to((ROOT/'artifacts').resolve())
settings=Settings(DATA,origin=f'http://127.0.0.1:{PORT}',ai_api_key='synthetic-no-network',ai_model='offline-genui-fixture',
    ai_grounding=False,agent_enabled=False,notice_semantic_review=False,genui_ai_label='工程夹具 · 非真实模型',ai_daily_limit=1000)

UI={'renderer':'open_generative_ui','title':'本地试算与选择','initialHeight':220,'placeholderMessages':[], 'css':'',
    'html':['<section class="ui-priority" data-ui-priority="primary"><h2>当前结果</h2><output id="result">—</output><p class="ui-caption">合成验收数据，不是学校规定或真实任务。</p></section>',
        '<form class="ui-stack"><div class="ui-grid"><label class="ui-field">小时<input id="hours" type="number" min="0" max="100" step="1" value="8" required></label><label class="ui-field">天数<input id="days" type="number" min="1" max="30" step="1" value="2" required></label></div><p id="problem" role="status" hidden></p><div class="ui-action-bar"><button type="reset" data-ui-local>重置参数</button><button id="ask" type="button">分析当前选择</button></div></form>',
        '<details><summary>查看计算方法</summary><p>小时除以天数，仅作本地输入与状态同步验收。</p></details>'],
    'jsFunctions':"function setup(){CampusUI.form({inputs:{hours:{},days:{}},outputs:{result:v=>v.hours/v.days},error:'problem',prompt:{id:'ask',text:'请根据当前界面选择继续分析'}});}",
    'jsExpressions':['setup();']}
calls=[]
async def recorded(settings,sources,messages,profile,tier):
    question=next(m['content'] for m in reversed(messages) if m['role']=='user')
    calls.append({'user_messages':[m['content'] for m in messages if m['role']=='user'],'quoted':bool(messages[-1].get('reply_to'))})
    (DATA/'model-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    if '等待提示验收' in question:
        yield {'type':'phase','phase':'searching','label':'正在查找资料'}
        await asyncio.sleep(15)
        yield {'type':'phase','phase':'writing','label':'正在整理回复'}
        await asyncio.sleep(10)
        yield {'type':'phase','phase':'verifying','label':'正在核对依据'}
        await asyncio.sleep(15)
    if '互动验收' in question:raw='以下是本地工程试算界面。\n```openui\n'+json.dumps(UI,ensure_ascii=False)+'\n```'
    elif messages[-1].get('interaction'):raw='【工程夹具】服务端已收到当前界面选择：'+json.dumps(messages[-1]['interaction'].get('selections',[]),ensure_ascii=False)
    else:raw='【工程夹具】已收到这些连续消息：'+'；'.join(m['content'] for m in messages[-5:] if m['role']=='user')
    for start in range(0,len(raw),70):
        await asyncio.sleep(.12 if '慢速验收' in question else .025)
        yield {'type':'delta','text':raw[start:start+70]}
        if '中途故障验收' in question and start>70:raise AIError('合成故障：已收到的消息与部分回复均保留')
    yield {'type':'complete','result':{'answer':raw,'citations':[],'image_sources':[]},'usage':{}}
def legacy(settings,sources,messages,profile):
    return {'answer':'【工程夹具】合成原消息：活动暂记周五，尚未对照正式通知。','citations':[],'image_sources':[]},{}
genui_ai.stream_reply=recorded;chat_ai.reply=legacy
app=create_app(settings)
failed=set()
@app.middleware('http')
async def first_rejection(request,call_next):
    if request.method=='POST' and request.url.path.endswith('/messages/stream'):
        data=await request.json()
        if '首次拒收验收' in data.get('content','') and data.get('request_id') not in failed:
            failed.add(data['request_id']);return JSONResponse({'detail':'合成故障：本次尚未接收，请核对回执后使用原编号重试'},status_code=503)
    return await call_next(request)

def seed():
    client=TestClient(app,base_url=settings.origin,headers={'Origin':settings.origin,'X-Requested-With':'campus-notice'})
    with app.state.db.connect() as conn:exists=conn.execute("SELECT id FROM users WHERE username='deepbrowser'").fetchone()
    if not exists:
        token=new_invite(app.state.db,'user')
        verified_registration(client,{'invite':token,'username':'deepbrowser','display_name':'深度交互工程验收','password':'Synthetic-Only-Chat-2026','accepted_terms':True})
    else:
        client.post('/api/auth/login',json={'username':'deepbrowser','password':'Synthetic-Only-Chat-2026'}).raise_for_status()
    client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
    chat=client.post('/api/conversations',json={'title':'引用与连续消息 · 工程验收'}).json()
    initial=client.post('/api/conversations/'+chat['id']+'/messages',json={'version':chat['version'],'content':'请记住：这是本地工程验收，不涉及真实个人业务。','request_id':'synthetic-seed-question-0001'});initial.raise_for_status()
    (DATA/'seed.json').write_text(json.dumps({'conversation_id':chat['id'],'synthetic_only':True}),encoding='utf-8')
if __name__=='__main__':
    seed()
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
