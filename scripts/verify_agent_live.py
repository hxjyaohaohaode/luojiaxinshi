"""Explicit live MiMo protocol smoke test with an isolated synthetic account.

This script can incur API charges. It sends only the fixed synthetic prompt and
the tool schemas; it never reads the application's live database or materials.
"""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.db import Database, ident
from app.execution import Runtime
from app.agent_runtime.runtime import Service
from app.agent_runtime.types import NewThread, StartTurn

PROMPT='这是工具兼容性工程测试，不含真实用户数据。只调用一次 list_files，然后返回 RUNTIME_OK；不要调用任何其他工具，不创建子任务、不联网。'


async def check():
    output=ROOT/'artifacts'/'agent-runtime-live';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=output) as folder:
        settings=replace(Settings.from_env(),data_dir=Path(folder),ai_daily_limit=5)
        db=Database(settings.data_dir/'campus.sqlite3');runtime=Runtime(db);runtime.tick()
        uid=ident()
        with db.connect(write=True) as conn:
            conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',(uid,'synthetic-user','disabled','工程夹具','user','{}',int(time.time())))
        service=Service(db,settings,runtime.owner)
        thread=service.store.create(uid,NewThread(approval_policy='deny'))
        async def heartbeat():
            while True:
                await asyncio.sleep(10);runtime.tick()
        pulse=asyncio.create_task(heartbeat())
        try:
            row=service.submit(uid,thread['id'],StartTurn(prompt=PROMPT,request_id=ident(),allow_external_processing=True))
            await service.tasks[row['id']]
            with db.connect() as conn:
                result=dict(conn.execute('SELECT status,answer,error,usage FROM agent_turns WHERE id=?',(row['id'],)).fetchone())
                names=[json.loads(r[0])['tool'] for r in conn.execute("SELECT data FROM agent_events WHERE turn_id=? AND type='tool.completed'",(row['id'],))]
            report={'provider':'mimo','model':settings.ai_model,'synthetic_input':True,'status':result['status'],
                    'answer':result['answer'],'error':result['error'],'usage':json.loads(result['usage']),'tools':names}
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
            if result['status']!='completed' or names!=['list_files'] or 'RUNTIME_OK' not in result['answer']:
                raise SystemExit(1)
        finally:
            pulse.cancel();await asyncio.gather(pulse,return_exceptions=True);await service.close();runtime.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.parse_args()
    asyncio.run(check())
