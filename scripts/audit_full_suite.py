"""Run every backend test file exactly once, in isolated bounded processes.

Grouping is deterministic and independent of previous reports.
Per-shard logs, current collected counts, JUnit and exit codes are retained.
No provider credentials or application data are read by this coordinator.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent


def fingerprint():
    digest=hashlib.sha256()
    for folder in ('app','static','tests','scripts','schema','deploy','.github'):
        for path in sorted((ROOT/folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or (path.suffix not in {'.py','.js','.mjs','.css','.html','.json','.ps1','.sh','.yml','.yaml'} and path.name not in {'Dockerfile','.dockerignore'}):continue
            digest.update(path.relative_to(ROOT).as_posix().encode());digest.update(path.read_bytes())
    for name in ('manage.py','start.ps1','stop.ps1','requirements.lock','requirements-dev.txt','.env.example',
                 'Dockerfile','.dockerignore','compose.yaml','Caddyfile','package.json','package-lock.json','pytest.ini','.gitattributes'):
        path=ROOT/name
        if path.exists():digest.update(name.encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def combine_junit(reports,destination):
    """Keep every real testcase in one CI artifact, including failed shards."""
    root=ET.Element('testsuites')
    for report in reports:
        if not report.exists():continue
        value=ET.parse(report).getroot()
        if value.tag=='testsuite':root.append(value)
        elif value.tag=='testsuites':root.extend(list(value))
        else:raise ValueError('Unexpected JUnit root in '+str(report))
    destination.parent.mkdir(parents=True,exist_ok=True)
    ET.ElementTree(root).write(destination,encoding='utf-8',xml_declaration=True)


def run_shard(index,group,out,timeout):
    xml=out/f'shard-{index+1}.xml';log=out/f'shard-{index+1}.log'
    xml.unlink(missing_ok=True)
    command=[sys.executable,'-m','pytest',*group,'-vv','--junitxml='+str(xml),
        '-o','cache_dir='+str(out/f'cache-{index+1}'),'-o','faulthandler_timeout=90','--durations=8']
    env=dict(os.environ,CAMPUS_AUTO_LOAD_ENV='0',PYTHONUNBUFFERED='1',PYTHONFAULTHANDLER='1')
    for key in ('MIMO_API_KEY','AI_API_KEY','OPENAI_API_KEY','ALIYUN_ACCESS_KEY_ID',
                'ALIYUN_ACCESS_KEY_SECRET','SMTP_AUTHORIZATION_CODE','SMTP_PASSWORD',
                'DATA_DIR','APP_ENV','APP_ORIGIN','APP_HOST','APP_PORT'):
        env.pop(key,None)
    timed_out=False
    with log.open('w',encoding='utf-8') as stream:
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,**options)
        try:code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True;code=124
            stream.write('\nOwned test shard exceeded its deadline; its process tree is being stopped.\n');stream.flush()
            if process.poll()is None:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
                else:os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=15)
    result={'shard':index+1,'exit_code':code,'files':len(group),'timed_out':timed_out}
    if xml.exists():
        suites=list(ET.parse(xml).getroot().iter('testsuite'))
        result.update({key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=4,choices=range(1,5))
    parser.add_argument('--output',default='artifacts/full-audit-suite')
    parser.add_argument('--junitxml',type=Path,help='Optional combined JUnit report for the exact same shard results')
    parser.add_argument('--shard-timeout',type=int,default=2400,help='Maximum seconds per owned shard; timeout is a failure')
    args=parser.parse_args();out=(ROOT/args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if args.shard_timeout<1:parser.error('Shard timeout must be positive')
    files=sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').rglob('test_*.py'))
    if not files:parser.error('No backend test files found; an empty run cannot pass')
    groups=[files[index::args.workers]for index in range(args.workers)]
    (out/'manifest.json').write_text(json.dumps({'files':files,'count':len(files),'shards':groups},indent=2),encoding='utf-8')
    started=time.monotonic()
    before=fingerprint()
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_shard,i,g,out,args.shard_timeout) for i,g in enumerate(groups) if g]):
            result=future.result();results.append(result);print(json.dumps(result),flush=True)
    after=fingerprint()
    summary={'elapsed_seconds':round(time.monotonic()-started,2),'file_count':len(files),'shards':sorted(results,key=lambda x:x['shard']),
        'implementation_sha256':before,'implementation_unchanged':before==after}
    for key in ('tests','failures','errors','skipped'):summary[key]=sum(r.get(key,0) for r in results)
    summary['passed']=summary['tests']-summary['failures']-summary['errors']-summary['skipped']
    summary['complete']=len(results)==len([g for g in groups if g]) and all('tests' in r for r in results)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if args.junitxml:
        combine_junit([out/f'shard-{i+1}.xml'for i,g in enumerate(groups)if g],args.junitxml)
    print(json.dumps(summary),flush=True)
    return 0 if summary['complete'] and summary['implementation_unchanged'] and all(r['exit_code']==0 for r in results) else 1


if __name__=='__main__':raise SystemExit(main())
