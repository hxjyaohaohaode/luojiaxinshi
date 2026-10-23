"""Xiaomi MiMo speech adapters. Audio is processed in memory, never auto-retried."""
import base64
import io
import json
import wave
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .ai import AIError
from .security import rate_limit

MAX_AUDIO = 5 * 1024 * 1024
MAX_SPEECH_TEXT = 2000
VOICES = {'mimo_default','冰糖','茉莉','苏打','白桦','Mia','Chloe','Milo','Dean'}


def wav_data_url(data, max_seconds=60):
    # This application deliberately accepts PCM WAV only; browsers convert locally.
    if not data or len(data)>MAX_AUDIO:
        raise ValueError('录音须大于 0 字节且不超过 5 MB')
    try:
        with wave.open(io.BytesIO(data),'rb') as audio:
            frames,rate=audio.getnframes(),audio.getframerate()
            if (audio.getcomptype()!='NONE' or audio.getnchannels() not in {1,2}
                    or audio.getsampwidth()!=2 or not 8000<=rate<=48000
                    or not 0<frames/rate<=max_seconds):
                raise ValueError('invalid_wav')
            if len(audio.readframes(frames))!=frames*audio.getnchannels()*2:
                raise ValueError('truncated_wav')
    except (wave.Error,EOFError,ValueError):
        raise ValueError(f'请使用完整的 16 位 PCM WAV 录音，时长不超过 {max_seconds} 秒') from None
    return 'data:audio/wav;base64,'+base64.b64encode(data).decode('ascii')


AI_AUDIO_MARK = 'AI生成内容'


def label_audio(data, model):
    """在 WAV 文件中写入隐式标识（RIFF LIST/INFO 元数据），满足生成合成内容的隐式标识要求。

    只在文件尾追加 LIST 块并更新 RIFF 长度，不改动音频数据；已带标识的文件原样返回。
    非 RIFF/WAVE 数据原样返回，由显式标识负责提示。
    """
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or AI_AUDIO_MARK.encode() in data[-512:]:
        return data
    def chunk(tag, text):
        value = text.encode('utf-8') + b'\0'
        if len(value) % 2:
            value += b'\0'
        return tag + len(value).to_bytes(4, 'little') + value
    info = b'INFO' + chunk(b'ICMT', f'{AI_AUDIO_MARK}；服务：珞珈信使；模型：小米 MiMo {model}') + chunk(b'ISFT', '珞珈信使 · 小米 MiMo 语音合成')
    body = data[:8 + int.from_bytes(data[4:8], 'little')] if int.from_bytes(data[4:8], 'little') + 8 <= len(data) else data
    if len(body) % 2:
        body += b'\0'
    labeled = body + b'LIST' + len(info).to_bytes(4, 'little') + info
    return labeled[:4] + (len(labeled) - 8).to_bytes(4, 'little') + labeled[8:]


def asr_payload(settings,data):
    return {'model':settings.asr_model,'messages':[{'role':'user','content':[
        {'type':'input_audio','input_audio':{'data':wav_data_url(data)}}]}],
        'asr_options':{'language':'auto'},'stream':False}


def tts_payload(settings,text,mode='default',description='',reference=None,clone_authorized=False):
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_SPEECH_TEXT:
        raise ValueError(f'播报正文须为 1—{MAX_SPEECH_TEXT} 字')
    if not isinstance(description,str) or len(description)>500:
        raise ValueError('音色描述须不超过 500 字')
    audio={'format':'wav'}
    if mode=='default':
        if settings.tts_voice not in VOICES:raise ValueError('预置音色无效')
        model=settings.tts_model
        audio['voice']=settings.tts_voice
    elif mode=='design':
        if not description.strip():raise ValueError('请填写音色描述')
        model=settings.voice_design_model
        audio['optimize_text_preview']=False
    elif mode=='clone':
        if not clone_authorized:raise ValueError('声音复刻需要确认本人声音或已获声音所有者授权')
        if not reference:raise ValueError('声音复刻需要参考录音')
        model=settings.voice_clone_model
        audio['voice']=wav_data_url(reference,30)
    else:
        raise ValueError('未知的语音模式')
    if mode!='clone' and reference:
        raise ValueError('参考录音仅用于声音复刻')
    return {'model':model,'messages':[{'role':'user','content':description.strip()},
            {'role':'assistant','content':text.strip()}],'audio':audio,'stream':False}


def complete(settings,payload,max_bytes):
    if not settings.ai_api_key:raise AIError('小米 MiMo 尚未配置，请在服务端填写 MIMO_API_KEY 后重启')
    try:
        with httpx.Client(timeout=httpx.Timeout(settings.ai_timeout,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',settings.ai_base_url+'/chat/completions',
                               headers={'Authorization':'Bearer '+settings.ai_api_key},json=payload) as response:
                if response.status_code!=200:
                    errors={401:'小米 API Key 无效',403:'当前账号未获该模型权限',404:'小米模型或接口不存在',429:'小米额度不足或请求受限'}
                    raise AIError(errors.get(response.status_code,'小米语音服务暂不可用')+'；可稍后手动重试')
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>max_bytes:raise AIError('语音返回超过本应用上限，请缩短内容后重试')
                    chunks.append(chunk)
        data=json.loads(b''.join(chunks))
        choice=data['choices'][0]
        if choice.get('finish_reason')!='stop':raise AIError('语音结果未完整结束，请缩短内容后重试')
        return choice['message'],data.get('usage') or {}
    except (httpx.TimeoutException,httpx.NetworkError):
        raise AIError('小米语音连接超时或中断，本次可能已计费；请自行选择重试') from None
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        raise AIError('小米语音返回格式异常，请稍后重试') from None


def transcribe(settings,payload):
    message,usage=complete(settings,payload,200000)
    text=message.get('content')
    if not isinstance(text,str) or len(text)>10000:
        raise AIError('没有得到有效听写文字，请重新录音')
    # An empty successful ASR response is a quiet/unrecognised segment, not a
    # transport failure. Keep earlier text and continue with subsequent speech.
    return {'text':text.strip(),'no_speech':not bool(text.strip()),'model':payload['model'],'usage':usage}


def synthesize(settings,payload):
    message,_=complete(settings,payload,24*1024*1024)
    try:
        audio=base64.b64decode(message['audio']['data'],validate=True)
        with wave.open(io.BytesIO(audio),'rb') as wav:
            if wav.getnframes()<1 or not wav.getframerate():raise ValueError('empty_audio')
            if len(wav.readframes(wav.getnframes()))!=wav.getnframes()*wav.getnchannels()*wav.getsampwidth():
                raise ValueError('truncated_audio')
        return audio
    except (ValueError,KeyError,TypeError,wave.Error,EOFError):
        raise AIError('小米语音返回的音频无效，未播放') from None


def install_speech(app,db,settings,user,heavy_lock):
    from threading import BoundedSemaphore
    speech_slots=BoundedSemaphore(2)
    from .speech_cache import SpeechCache
    cache=SpeechCache(db)
    @app.get('/api/speech/config')
    def config(current=Depends(user)):
        from .model_catalog import public_configuration
        provider=public_configuration(settings)
        return {'configured':provider['speech_available'],'provider':'Xiaomi MiMo',
                'unavailable_reason':'当前语音适配器需要普通按量 API 凭证，不能混用 Token Plan 通道。' if provider['billing_channel']=='token_plan' else '',
                'models':{'asr':settings.asr_model,'default':settings.tts_model,'design':settings.voice_design_model,'clone':settings.voice_clone_model},
                'voice':settings.tts_voice,'max_recording_seconds':60,'max_clone_seconds':30,'max_text_chars':MAX_SPEECH_TEXT}

    def invoke(current,payload,operation):
        if not settings.ai_api_key:raise HTTPException(503,'请在服务端填写 MIMO_API_KEY 并重启后使用语音')
        from .model_catalog import channel
        if channel(settings.ai_base_url)=='token_plan':raise HTTPException(503,'当前语音适配器需要普通按量 API 凭证，未向订阅通道发送录音或文字')
        # Dictation remains responsive while an agent is answering or parsing.
        # Speech has its own bounded lane; it cannot start another chat job.
        if not speech_slots.acquire(False):raise HTTPException(429,'语音服务正在处理其他录音，请稍后重试')
        try:
            day=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            rate_limit(db,'speech:'+current['id']+':'+day,settings.ai_daily_limit,86400)
            return transcribe(settings,payload) if operation=='asr' else synthesize(settings,payload)
        except AIError as exc:
            raise HTTPException(502,str(exc)) from None
        finally:
            speech_slots.release()

    async def read_audio(form,key):
        upload=form.get(key)
        if upload is None:return None
        if not hasattr(upload,'read'):raise ValueError('请上传 WAV 录音文件')
        return await upload.read(MAX_AUDIO+1)

    @app.post('/api/speech/transcribe')
    async def recognize(request:Request,current=Depends(user)):
        try:
            async with request.form(max_files=1,max_fields=2) as form:
                if form.get('allow_external_processing')!='true':raise HTTPException(422,'请确认录音可发送至小米 MiMo 识别')
                payload=asr_payload(settings,await read_audio(form,'audio'))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        return await run_in_threadpool(invoke,current,payload,'asr')

    @app.post('/api/speech/synthesize')
    async def speak(request:Request,current=Depends(user)):
        try:
            async with request.form(max_files=1,max_fields=7) as form:
                if form.get('allow_external_processing')!='true':raise HTTPException(422,'请确认播报文字及所选录音可发送至小米 MiMo')
                payload=tts_payload(settings,form.get('text',''),form.get('mode','default'),form.get('description',''),
                                    await read_audio(form,'reference'),form.get('clone_authorized')=='true')
                message_id=form.get('message_id') or None
                if message_id:
                    with db.connect() as conn:
                        owned=conn.execute('''SELECT 1 FROM conversation_messages m JOIN conversations c
                          ON c.id=m.conversation_id WHERE m.id=? AND c.user_id=? AND m.status='complete' AND m.role='assistant' ''',
                                           (message_id,current['id'])).fetchone()
                    if not owned:raise HTTPException(404,'这条回复已不可用，请刷新对话')
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        if not settings.ai_api_key:raise HTTPException(503,'请在服务端填写 MIMO_API_KEY 并重启后使用语音')
        from .model_catalog import channel
        if channel(settings.ai_base_url)=='token_plan':raise HTTPException(503,'当前语音适配器需要普通按量 API 凭证')
        # Reference recordings are deliberately excluded from persistent reuse.
        if form.get('mode','default')=='clone':
            # 声音复刻涉及他人声音权益与深度合成规定，默认关闭；部署方确有书面授权流程时再开启。
            if not settings.voice_clone_enabled:raise HTTPException(403,'本部署没有开放声音复刻')
            audio=await run_in_threadpool(invoke,current,payload,'tts');cached=False
        else:
            audio,cached=await run_in_threadpool(cache.get_or_create,current['id'],message_id,settings,payload,
                                                lambda:invoke(current,payload,'tts'))
        return Response(label_audio(audio,payload['model']),media_type='audio/wav',headers={'Cache-Control':'no-store','X-Speech-Model':payload['model'],
                                                            'X-Speech-Cache':'hit' if cached else 'miss','X-AI-Generated':'true'})
