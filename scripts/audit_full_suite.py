"""Run every backend test file exactly once, in isolated bounded processes.

The old complete JUnit report only balances work; it never supplies results.
Per-shard logs, current collected counts, JUnit and exit codes are retained.
No provider credentials or application data are read by this coordinator.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import hashlib
import json
import os
from pathlib import Path
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=4,choices=range(1,5))
    parser.add_argument('--output',default='artifacts/full-audit-suite')
    parser.add_argument('--junitxml',type=Path,help='Optional combined JUnit report for the exact same shard results')
    args=parser.parse_args();out=(ROOT/args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    files=sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').rglob('test_*.py'))
    if not files:parser.error('No backend test files found; an empty run cannot pass')
    weights={name:1. for name in files}
    previous=list((ROOT/'artifacts/full-audit-suite').glob('shard-*.xml')) or [ROOT/'artifacts/proactive-full-tests.xml']
    for report in previous:
        if not report.exists():continue
        for case in ET.parse(report).getroot().iter('testcase'):
            name=case.get('classname','').replace('.','/')+'.py'
            if not name.startswith('tests/'):name='tests/'+name
            if name in weights:weights[name]+=float(case.get('time',0))
    groups=[[] for _ in range(args.workers)];cost=[0.]*args.workers
    for name in sorted(files,key=lambda p:(-weights[p],p)):
        index=min(range(args.workers),key=lambda i:cost[i]);groups[index].append(name);cost[index]+=weights[name]
    (out/'manifest.json').write_text(json.dumps({'files':files,'count':len(files),'shards':groups},indent=2),encoding='utf-8')
    started=time.monotonic()
    before=fingerprint()
    def run(index,group):
        xml=out/f'shard-{index+1}.xml';log=out/f'shard-{index+1}.log'
        command=[sys.executable,'-m','pytest',*group,'-q','--junitxml='+str(xml),
            '-o','cache_dir='+str(out/f'cache-{index+1}'),'--durations=8']
        with log.open('w',encoding='utf-8') as stream:
            process=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        result={'shard':index+1,'exit_code':process.returncode,'files':len(group)}
        if xml.exists():
            suites=list(ET.parse(xml).getroot().iter('testsuite'))
            result.update({key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')})
        return result
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run,i,g) for i,g in enumerate(groups) if g]):
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
