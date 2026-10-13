"""隔离的浏览器验收服务。仅绑定本机 8767，全部模型响应均为工程夹具。"""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import genui_ai, chat_ai
from app.ai import AIError
from app.config import Settings
from app.main import create_app

DATA = ROOT / 'artifacts/genui-browser-data'
DATA.mkdir(parents=True, exist_ok=True)
# 只复用此前的合成验收账户；绝不读取 data/ 的实际账户。
seed = ROOT / 'artifacts/browser-test-data/campus.sqlite3'
if seed.exists() and not (DATA / 'campus.sqlite3').exists():
    with sqlite3.connect(seed) as src, sqlite3.connect(DATA / 'campus.sqlite3') as dst:
        src.backup(dst)

SIMPLE = '这是一条工程夹具回复。简单问题只保留清楚的文字。'
RAW = (ROOT / 'fixtures/genui/study-plan.md').read_text(encoding='utf-8')
SCENARIOS=json.loads((ROOT/'fixtures/genui/scenarios.json').read_text(encoding='utf-8'))
GALLERY = json.loads((ROOT / 'fixtures/genui/gallery.json').read_text(encoding='utf-8'))

def fixture(question):
    if '纯文字' in question:return SIMPLE
    if '界面选择' in question:return '已收到你在表单中的选择。这是结构化事件的本机验收回复。'
    selected = next((name for name in GALLERY if name in question), None)
    if selected:
        return '以下为本机工程示例，不代表学校正式信息。\n\n```genui\n'+'\n'.join(json.dumps(op, ensure_ascii=False) for op in GALLERY[selected])+'\n```'
    if '故障' in question:
        return RAW.replace('{"op":"end"}', '{"op":"node","id":"broken","type":"UnknownWidget","props":{"fallback":"这一块暂不支持"}}\n{not valid json}\n{"op":"end"}')
    key='compare' if '对比' in question else 'data' if '趋势' in question else 'plan' if '清单' in question else 'calculate'
    scene=SCENARIOS[key]
    return scene['intro']+'\n\n```genui\n'+'\n'.join(json.dumps(op,ensure_ascii=False) for op in scene['ops'])+'\n```'

async def recorded(settings, sources, messages, profile, tier):
    question = next((m['content'] for m in reversed(messages) if m['role']=='user'), '')
    raw=fixture(question)
    for start in range(0,len(raw),33):
        await asyncio.sleep(0.18 if '停止' in question else 0.025)
        yield {'type':'delta','text':raw[start:start+33]}
        if '中断' in question and start>500:raise AIError('工程故障注入：连接中断，已收到的内容保留。')
    yield {'type':'complete','result':{'answer':raw,'citations':[],'image_sources':[]},'usage':{}}

def legacy(*args, **kwargs):
    return {'answer':SIMPLE,'citations':[],'image_sources':[]},{}

genui_ai.stream_reply=recorded
chat_ai.reply=legacy
settings=Settings(DATA, origin='http://127.0.0.1:8767', ai_model='offline-genui-fixture', ai_api_key='synthetic-no-network', ai_daily_limit=1000, genui_debug=False, genui_ai_label='工程示例 · 非真实模型')
app=create_app(settings)
counts={}
@app.middleware('http')
async def count_requests(request, call_next):
    # 只统计方法和路径，不记录正文、身份、查询串或密钥。
    if request.url.path.startswith('/api/'):
        key=request.method+' '+request.url.path
        counts[key]=counts.get(key,0)+1
        (DATA/'request-counts.json').write_text(json.dumps(counts,ensure_ascii=False,indent=2),encoding='utf-8')
    return await call_next(request)

if __name__=='__main__':
    import uvicorn
    print('工程验收服务：仅合成回复，数据目录 artifacts/genui-browser-data', flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8767,access_log=False)
