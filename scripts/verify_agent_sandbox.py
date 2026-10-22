"""Opt-in real container check using an already-installed immutable image.

Usage: python scripts/verify_agent_sandbox.py --image python@sha256:...
No downloads, host writes, network credentials, or live application data.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.agent_runtime.sandbox import Files, command


PROBE = '''import json,os,socket
result={"uid":os.getuid(),"file":open("/workspace/input.txt").read()}
try:
 open("/workspace/escape.txt","w").write("forbidden")
 result["workspace_write_denied"]=False
except OSError:
 result["workspace_write_denied"]=True
try:
 open("/etc/escape.txt","w").write("forbidden")
 result["root_write_denied"]=False
except OSError:
 result["root_write_denied"]=True
try:
 socket.create_connection(("1.1.1.1",443),timeout=1).close()
 result["network_denied"]=False
except OSError:
 result["network_denied"]=True
result["no_new_privs"]=next(line.strip() for line in open("/proc/self/status") if line.startswith("NoNewPrivs:"))
result["effective_caps"]=next(line.strip() for line in open("/proc/self/status") if line.startswith("CapEff:"))
print(json.dumps(result))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True);args=parser.parse_args()
    output=ROOT/'artifacts'/'agent-runtime-sandbox';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=output) as folder:
        files=Files(Path(folder),'a'*32,'b'*32)
        files.write('input.txt','synthetic sandbox input','')
        result=asyncio.run(command(files,['python','-c',PROBE],args.image))
        if result['exit_code']!=0:raise RuntimeError(result['output'])
        checks=json.loads(result['output'])
        assert checks['uid']==65534 and checks['file']=='synthetic sandbox input'
        assert checks['workspace_write_denied'] and checks['root_write_denied'] and checks['network_denied']
        assert checks['no_new_privs'].endswith('1') and checks['effective_caps'].endswith('0000000000000000')
        assert not (files.root/'escape.txt').exists()
        report={'image':args.image,'synthetic':True,'checks':checks}
        (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
