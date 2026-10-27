"""Launch an isolated synthetic agent and verify all three browser engines."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'artifacts/ci-openui-browser'


def ensure_fixture_port_free(port=8794):
    with socket.socket() as probe:
        # POSIX retains the closed fixture's accepted sockets in TIME_WAIT.
        # Like Uvicorn, permit that state while still rejecting a live listener.
        # Windows uses exclusive binding instead: SO_REUSEADDR there can admit
        # another active listener and must not be used for this ownership check.
        if os.name=='nt':probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        else:probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe.bind(('127.0.0.1',port))
        except OSError:raise SystemExit(f'Port {port} is occupied; no existing process was reused or stopped.') from None


def main():
    ensure_fixture_port_free()
    OUT.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONUNBUFFERED='1')
    for key in ('MIMO_API_KEY','AI_API_KEY','OPENAI_API_KEY'):env.pop(key,None)
    flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
    results=[]
    verify_script=os.getenv('OPENUI_VERIFY_SCRIPT','scripts/verify_openui.mjs')
    if verify_script not in ('scripts/verify_openui.mjs','scripts/verify_openui_generated.mjs','scripts/verify_chat_layout.mjs','scripts/verify_chat_interactions.mjs','scripts/verify_task_board.mjs','scripts/verify_chat_recovery.mjs'):raise ValueError('Unknown OpenUI verification script')
    if verify_script=='scripts/verify_chat_recovery.mjs':env['OPENUI_REVIEW_DELAY']='4'
    if verify_script=='scripts/verify_task_board.mjs':env.update(CAMPUS_VERIFY_ORIGIN='http://127.0.0.1:8794',CAMPUS_VERIFY_USER='openui-preview',CAMPUS_VERIFY_PASSWORD='OpenUIFixture2026!')
    scratch=tempfile.TemporaryDirectory(prefix='fixture-',dir=OUT)
    try:
        data=scratch.name
        env['OPENUI_PREVIEW_DATA_DIR']=str(Path(data).resolve())
        with (OUT/'fixture.log').open('w',encoding='utf-8') as log:
            fixture=subprocess.Popen([sys.executable,'scripts/openui_preview_server.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,**flags)
            try:
                deadline=time.monotonic()+45
                while True:
                    if fixture.poll() is not None:raise RuntimeError('OpenUI synthetic fixture exited before startup')
                    try:
                        with urlopen('http://127.0.0.1:8794/api/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:pass
                    if time.monotonic()>deadline:raise RuntimeError('OpenUI fixture startup timed out')
                    time.sleep(.15)
                for name in os.getenv('OPENUI_BROWSERS','chromium,firefox,webkit').split(','):
                    if name not in ('chromium','firefox','webkit'):raise ValueError('Unknown browser engine')
                    target=('artifacts/chat-recovery/' if verify_script=='scripts/verify_chat_recovery.mjs' else 'artifacts/task-board-refinements/' if verify_script=='scripts/verify_task_board.mjs' else 'artifacts/chat-interactions/' if verify_script=='scripts/verify_chat_interactions.mjs' else 'artifacts/chat-layout/' if verify_script=='scripts/verify_chat_layout.mjs' else 'artifacts/openui-live/browser/' if env.get('OPENUI_REPLAY_FILE') else 'artifacts/openui-browser/')+name
                    run_env=dict(env,OPENUI_BROWSER=name,OPENUI_ARTIFACT_DIR=target)
                    with (OUT/(name+'.log')).open('w',encoding='utf-8') as output:
                        try:code=subprocess.run(['node',verify_script],cwd=ROOT,env=run_env,stdout=output,stderr=subprocess.STDOUT,timeout=150).returncode
                        except subprocess.TimeoutExpired:code=124
                    results.append({'browser':name,'returncode':code,'report':target+'/report.json'})
                    print(name+': '+('passed' if code==0 else 'FAILED'),flush=True)
            finally:
                if fixture.poll() is None:
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(fixture.pid),'/T','/F'],capture_output=True,timeout=10,**flags)
                    else:fixture.terminate()
                try:fixture.wait(timeout=15)
                except subprocess.TimeoutExpired:fixture.kill();fixture.wait(timeout=10)
    finally:
        target=Path(scratch.name).resolve()
        if target.parent!=OUT.resolve() or not target.name.startswith('fixture-'):raise RuntimeError('Refusing cleanup outside OpenUI artifacts')
        for attempt in range(12):
            try:scratch.cleanup();break
            except PermissionError as error:
                if getattr(error,'winerror',None) not in {5,32,33} or attempt==11:raise
                time.sleep(min(.1*(attempt+1),1))
    (OUT/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if not results or any(r['returncode'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
