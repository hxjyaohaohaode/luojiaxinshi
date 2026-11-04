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


def aggregate_partitions(manifests,files,groups,implementation):
    """A partition's success is never a whole-suite success on its own."""
    results={};reports={};errors=[];case_ids=set();elapsed=[]
    expected={i+1 for i,group in enumerate(groups) if group}
    for path in manifests:
        try:
            manifest=json.loads(path.read_text(encoding='utf8'))
            summary=json.loads((path.parent/'summary.json').read_text(encoding='utf8'))
            if manifest.get('files')!=files or manifest.get('shards')!=groups:
                raise ValueError('The full test-file inventory differs')
            selected=summary.get('selected_shards',[])
            if len(selected)!=1 or selected[0] not in expected:
                raise ValueError('Expected exactly one declared partition')
            if manifest.get('count')!=len(files) or manifest.get('selected_shards')!=selected:
                raise ValueError('Manifest and selected partition disagree')
            index=selected[0]
            if index in results:raise ValueError('Duplicate partition '+str(index))
            if summary.get('scope')!='partition' or summary.get('complete') is not False or not summary.get('selected_complete'):
                raise ValueError('Partition did not complete its selected files')
            if summary.get('implementation_sha256')!=implementation or not summary.get('implementation_unchanged'):
                raise ValueError('Partition code differs from the current frozen checkout')
            if len(summary.get('shards',[]))!=1:raise ValueError('Partition has an unexpected result count')
            result=summary['shards'][0]
            if result.get('shard')!=index or result.get('files')!=len(groups[index-1]):
                raise ValueError('Partition identity or assigned file count differs')
            report=path.parent/f'shard-{index}.xml'
            cases=list(ET.parse(report).getroot().iter('testcase'))
            actual={'tests':len(cases),'failures':sum(c.find('failure')is not None for c in cases),
                    'errors':sum(c.find('error')is not None for c in cases),'skipped':sum(c.find('skipped')is not None for c in cases)}
            if not cases or any(result.get(key)!=value for key,value in actual.items()):
                raise ValueError('Partition counts disagree with its real JUnit cases')
            modules=[name.removesuffix('.py').replace('/','.')for name in groups[index-1]]
            identities=[];covered=set()
            for case in cases:
                classname=case.get('classname','')
                if not any(classname==module or classname.startswith(module+'.')for module in modules):
                    raise ValueError('JUnit case is outside this partition assignment')
                covered.update(module for module in modules if classname==module or classname.startswith(module+'.'))
                identities.append((classname,case.get('name','')))
            if covered!=set(modules):raise ValueError('Assigned test file has no collected JUnit cases')
            if len(set(identities))!=len(identities) or any(key in case_ids for key in identities):
                raise ValueError('Duplicate JUnit case identity')
            case_ids.update(identities);results[index]=result;reports[index]=report
            elapsed.append(summary.get('elapsed_seconds',0))
        except (OSError,ValueError,KeyError,TypeError,ET.ParseError) as error:
            errors.append(str(path)+': '+str(error))
    missing=sorted(expected-set(results))
    if missing:errors.append('Missing partitions: '+', '.join(map(str,missing)))
    summary={'scope':'full','elapsed_seconds':max(elapsed,default=0),'file_count':len(files),
        'shards':[results[i]for i in sorted(results)],'implementation_sha256':implementation,
        'implementation_unchanged':not errors,'aggregation_errors':errors,'selected_shards':sorted(expected),
        'selected_complete':not errors and set(results)==expected,'complete':not errors and set(results)==expected}
    for key in ('tests','failures','errors','skipped'):summary[key]=sum(r.get(key,0)for r in results.values())
    summary['passed']=summary['tests']-summary['failures']-summary['errors']-summary['skipped']
    return summary,[reports[i]for i in sorted(reports)]


def run_shard(index,group,out,timeout):
    xml=out/f'shard-{index+1}.xml';log=out/f'shard-{index+1}.log'
    xml.unlink(missing_ok=True)
    command=[sys.executable,'-m','pytest',*group,'-vv','--junitxml='+str(xml),
        '-o','cache_dir='+str(out/f'cache-{index+1}'),'-o','faulthandler_timeout=90','--durations=8']
    env=dict(os.environ,CAMPUS_AUTO_LOAD_ENV='0',PYTHONUNBUFFERED='1',PYTHONFAULTHANDLER='1')
    for key in ('MIMO_API_KEY','AI_API_KEY','OPENAI_API_KEY','ALIYUN_ACCESS_KEY_ID',
                'ALIYUN_ACCESS_KEY_SECRET','SMTP_AUTHORIZATION_CODE','SMTP_PASSWORD',
                'DATA_DIR','APP_ENV','APP_ORIGIN','APP_HOST','APP_PORT','PYTEST_ADDOPTS'):
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
    parser.add_argument('--only-shard',type=int,choices=range(1,5),help='Run one declared partition; the report does not claim whole-suite completion')
    parser.add_argument('--merge-partitions',type=Path,help='Validate and merge independently uploaded partition reports')
    args=parser.parse_args();out=(ROOT/args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if args.shard_timeout<1:parser.error('Shard timeout must be positive')
    files=sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').rglob('test_*.py'))
    if not files:parser.error('No backend test files found; an empty run cannot pass')
    groups=[files[index::args.workers]for index in range(args.workers)]
    if args.only_shard and (args.only_shard>args.workers or not groups[args.only_shard-1]):parser.error('Selected partition must contain assigned files')
    if args.only_shard and args.merge_partitions:parser.error('Cannot run and merge a partition at the same time')
    selected=[(i,g)for i,g in enumerate(groups)if g and (not args.only_shard or i+1==args.only_shard)]
    (out/'manifest.json').write_text(json.dumps({'files':files,'count':len(files),'shards':groups,'selected_shards':[i+1 for i,g in selected]},indent=2),encoding='utf-8')
    started=time.monotonic()
    before=fingerprint()
    if args.merge_partitions:
        summary,reports=aggregate_partitions(sorted(args.merge_partitions.resolve().rglob('manifest.json')),files,groups,before)
        summary['implementation_unchanged'] &= fingerprint()==before
        summary['complete'] &= summary['implementation_unchanged']
        summary['aggregation_seconds']=round(time.monotonic()-started,2)
        (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
        if args.junitxml:combine_junit(reports,args.junitxml)
        print(json.dumps(summary),flush=True)
        return 0 if summary['complete'] and not summary['failures'] and not summary['errors'] and all(r['exit_code']==0 for r in summary['shards']) else 1
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_shard,i,g,out,args.shard_timeout) for i,g in selected]):
            result=future.result();results.append(result);print(json.dumps(result),flush=True)
    after=fingerprint()
    summary={'scope':'partition' if args.only_shard else 'full','selected_shards':[i+1 for i,g in selected],
        'elapsed_seconds':round(time.monotonic()-started,2),'file_count':len(files),'shards':sorted(results,key=lambda x:x['shard']),
        'implementation_sha256':before,'implementation_unchanged':before==after}
    for key in ('tests','failures','errors','skipped'):summary[key]=sum(r.get(key,0) for r in results)
    summary['passed']=summary['tests']-summary['failures']-summary['errors']-summary['skipped']
    summary['selected_complete']=len(results)==len(selected) and all(r.get('tests',0)>0 for r in results)
    summary['complete']=not args.only_shard and summary['selected_complete']
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    if args.junitxml:
        combine_junit([out/f'shard-{i+1}.xml'for i,g in selected],args.junitxml)
    print(json.dumps(summary),flush=True)
    return 0 if summary['selected_complete'] and summary['implementation_unchanged'] and not summary['failures'] and not summary['errors'] and all(r['exit_code']==0 for r in results) else 1


if __name__=='__main__':raise SystemExit(main())
