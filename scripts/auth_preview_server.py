"""Disposable localhost UI acceptance app, with no external message/model calls."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.main import create_app
import uvicorn

DATA=(ROOT/'artifacts'/'pilot-ui'/'isolated-auth').resolve()
assert DATA.is_relative_to((ROOT/'artifacts').resolve())
app=create_app(Settings(DATA,origin='http://localhost:18783',ai_api_key='isolated-fixture-only',
                        ai_base_url='https://example.invalid/v1',agent_enabled=False,
                        ai_grounding=False,notice_semantic_review=False))

# Only this disposable server replaces model/network boundaries. Production
# always uses the real adapter and explicit consent. Never accepts real files.
from app import campus_imports
from app.ai import AIError
async def fixture_recognize(settings,kind,sources):
    if any(not source['name'].startswith('__fixture_') for source in sources):
        raise AIError('This isolated server accepts only named engineering fixtures')
    if kind=='courses':
        return {'rows':[{'title':'【工程测试】课表导入','weekday':1,'weeks':'1-6(单)','periods':'',
            'start_time':'08:00','end_time':'09:35','location':'工程测试教室','notes':'','evidence':'工程测试课表，仅验证交互流程'}],
            'warnings':['这是隔离的工程夹具，未调用真实模型，也不是学生真实课表。']}
    return {'rows':[{'name':'【工程测试】公众号清单','wechat_id':'gh_import_fixture','institution':'工程测试机构','evidence':'仅验证导入交互'}],
            'warnings':['这是工程夹具，非真实公众号账号。']}
async def fixture_lookup(settings,payload):
    return {'items':[],'presets':[],'status':'no_evidence','note':'隔离工程夹具，不发送真实网络检索。'}
campus_imports.recognize=fixture_recognize
campus_imports.lookup=fixture_lookup

class FixtureMessages:
    def available(self,channel):return channel=='email'
    def send_code(self,channel,destination,code,purpose,request_id):
        if channel!='email' or not destination.endswith('@example.invalid'):
            raise ValueError('Only synthetic email addresses are accepted')
        (DATA/'synthetic-code.json').write_text(json.dumps({'challenge_id':request_id,'code':code,'purpose':purpose}),encoding='utf-8')
        return 'synthetic-only-no-network'

app.state.verification.provider=FixtureMessages()
if __name__=='__main__':
    print('Isolated UI fixtures only; separate localhost cookies; external delivery disabled.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=18783,access_log=False)
