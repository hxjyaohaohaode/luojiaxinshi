"""Opt-in real API check using generated synthetic audio, no human recording."""
import argparse
import array
import io
import json
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.speech import tts_payload,synthesize,asr_payload,transcribe
from app.model_catalog import channel
from app.console import configure_text_output


def main():
    configure_text_output()
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('Real provider calls require --live')
    settings=Settings.from_env()
    if not settings.ai_api_key or channel(settings.ai_base_url)!='pay_as_you_go':
        raise SystemExit('This adapter check requires a configured ordinary MiMo API credential.')
    folder=ROOT/'artifacts/mvp-acceptance';folder.mkdir(parents=True,exist_ok=True)
    report={'sample':'Generated synthetic voice only; no microphone, real person, or voice clone.',
            'checks':{},'calls':[],'limits':'API/data-format check, not a human listening or device microphone evaluation.'}
    text='这是一段合成语音测试，请准备申请表。'
    normal=None
    for mode in ('default','design'):
        payload=tts_payload(settings,text,mode,description='清晰、自然、语速适中，适合播报简短提醒。' if mode=='design' else '')
        started=time.monotonic()
        try:
            audio=synthesize(settings,payload)
            with wave.open(io.BytesIO(audio),'rb') as reader:
                frames=reader.readframes(reader.getnframes())
                rate=reader.getframerate();seconds=reader.getnframes()/rate
                samples=array.array('h',frames) if reader.getsampwidth()==2 else []
                peak=max((abs(sample) for sample in samples),default=0)
            (folder/('speech-1.5.0-'+mode+'.wav')).write_bytes(audio)
            report['calls'].append({'model':payload['model'],'seconds':round(time.monotonic()-started,3),'audio_seconds':round(seconds,3),'sample_rate':rate,'peak':peak})
            report['checks'][mode]=seconds>0 and peak>0
            if mode=='default':normal=audio
        except Exception as exc:
            report['checks'][mode]=False;report['calls'].append({'model':payload['model'],'error_type':type(exc).__name__,'message':str(exc)[:180]})
    if normal:
        started=time.monotonic()
        try:
            result=transcribe(settings,asr_payload(settings,normal))
            report['calls'].append({'model':settings.asr_model,'seconds':round(time.monotonic()-started,3),'recognized':result['text'],'usage':result['usage']})
            report['checks']['asr_roundtrip']='申请表' in result['text'] and '测试' in result['text']
        except Exception as exc:
            report['checks']['asr_roundtrip']=False;report['calls'].append({'model':settings.asr_model,'error_type':type(exc).__name__,'message':str(exc)[:180]})
    else:report['checks']['asr_roundtrip']=False
    (folder/'speech-live-1.5.0.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if all(report['checks'].values()) else 1)


if __name__=='__main__':main()
