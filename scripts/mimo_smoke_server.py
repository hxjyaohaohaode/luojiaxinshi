"""Isolated local UI smoke test, no external model calls or production data."""
import base64
import io
from pathlib import Path
import sys
import tempfile
import wave

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.config import Settings
from app.main import create_app
from app import speech, ai, chat_ai, genui_ai

def no_external(*args,**kwargs):
    raise ai.AIError('工程语音验收服务不调用外部模型')

async def no_external_stream(*args,**kwargs):
    raise ai.AIError('工程语音验收服务不调用外部模型')
    yield

def fixture(*args):
    payload=args[1]
    if payload['model']=='mimo-v2.5-asr':return {'content':'工程测试：请于10月20日核对申请。'},{}
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*16000)
    return {'audio':{'data':base64.b64encode(output.getvalue()).decode()}},{}

if __name__=='__main__':
    import uvicorn
    speech.complete=fixture
    ai.generate=chat_ai.reply=no_external
    genui_ai.stream_reply=no_external_stream
    with tempfile.TemporaryDirectory(prefix='mimo-ui-') as data:
        app=create_app(Settings(Path(data),origin='http://127.0.0.1:8779',ai_api_key='synthetic-ui-test'))
        uvicorn.run(app,host='127.0.0.1',port=8779,access_log=False)
