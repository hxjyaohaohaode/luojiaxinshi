"""Opt-in paired provider diagnostics; never store reasoning text or write app data."""
import argparse
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import httpx
from app.ai import prepare_notice_input,validate_extraction,NOTICE_OUTPUT_TOKENS,FACT_KEYS
from app.config import Settings
from app.console import configure_text_output
from app.documents import text_source


CASES=[
    {'id':'basic','text':'虚构工程验收通知：全日制本科生请于2027年11月3日17:00前提交申请表和本人签字的情况说明至学院办公室。学院审核于2027年11月5日完成。',
     'date':'2027-11-03','time':'17:00','forbidden_personal_dates':['2027-11-05'],'required_text':['申请表','情况说明']},
    {'id':'optional','text':'虚构工程验收通知：本科生可自愿参加图书馆讲座，是否参加由本人决定。有意参加者于2027年11月6日12:00前报名。参加现场活动前须获得主办方的报名确认。',
     'date':'2027-11-06','time':'12:00','optional':True,'condition':'报名确认'},
    {'id':'unknown_event','text':'虚构工程验收通知：收到学院资格确认后的第三天，本人提交申请表。学院尚未发出资格确认，当前无法确定收到日期；具体时刻也未规定。',
     'no_dates':True,'condition':'资格确认','required_text':['申请表']},
    {'id':'conflict','text':'虚构工程验收材料甲：本人须于2027年11月8日17:00前提交申请表。材料乙：本人须于2027年11月10日12:00前提交同一申请表。两份材料没有发布时间和更正关系，尚无法判断哪份有效。',
     'conflict':True,'required_text':['11月8','11月10']},
    {'id':'end_of_day','text':'虚构工程验收通知：本人请于2028年2月29日24:00前提交课程作业；老师于2028年3月5日统一审核。',
     'date':'2028-03-01','time':'00:00','forbidden_personal_dates':['2028-03-05']},
    {'id':'prerequisites','text':'虚构工程验收通知：本人先填写并下载申请表，再持该表向学院申请签字确认，取得签字后于2027年11月9日15:00前上传该表。学院负责实施签字。不得缺少签字直接上传。',
     'date':'2027-11-09','time':'15:00','dependency':True,'required_text':['签字','上传']},
]


def quality(case,draft):
    personal=[t for t in draft['tasks'] if t['scope']=='personal']
    plans=draft.get('plans',{});all_text=json.dumps(draft,ensure_ascii=False)
    checks={'eight_facts':set(draft['facts'])==FACT_KEYS,'personal_steps':bool(personal),
            'no_auto_confirmation':all(not t['deadline_confirmed'] and t['reminder_at'] is None and t['planned_at'] is None for t in draft['tasks'])}
    if 'date' in case:checks['personal_deadline']=any(t['due_date']==case['date'] and t['due_time']==case['time'] for t in personal)
    if case.get('forbidden_personal_dates'):checks['unit_deadline_is_not_personal']=all(t['due_date'] not in case['forbidden_personal_dates'] for t in personal)
    if case.get('no_dates'):checks['unknown_event_not_invented']=all(t['due_date'] is None and t['due_time'] is None for t in draft['tasks'])
    if case.get('optional'):checks['optional_not_mandatory']=any(p['action_kind']=='optional' for p in plans.values()) and not any(p['action_kind']=='required' for p in plans.values())
    if case.get('condition'):checks['external_condition_retained']=any(case['condition'] in c for p in plans.values() for c in p['conditions'])
    if case.get('required_text'):checks['required_content_retained']=all(value in all_text for value in case['required_text'])
    if case.get('conflict'):checks['conflict_retained']=bool(draft['warnings'] or any(t['uncertainties'] for t in draft['tasks'])) and all(value in all_text for value in ['11月8','11月10'])
    if case.get('dependency'):checks['upload_requires_signature']=any(t['scope']=='personal' and '上传' in t['title'] and any('签字' in draft['tasks'][dep]['title'] for dep in plans.get(i,{}).get('depends_on',[])) for i,t in enumerate(draft['tasks']))
    if case['id']=='business':
        def plan(i):return plans.get(str(i),plans.get(i,{}))
        def matching(*words):return {i for i,t in enumerate(draft['tasks']) if t['scope']=='personal' and all(w in t['title'] for w in words)}
        def ancestors(index):
            found=set();pending=[index]
            while pending:
                for dep in plan(pending.pop()).get('depends_on',[]):
                    if dep not in found:found.add(dep);pending.append(dep)
            return found
        consult=matching('咨询');practice=matching('实践');stamps=matching('签章')|matching('签字盖章');confirmations=matching('发榜单位','确认')
        forms=matching('下载')|matching('填写','报名');uploads=matching('上传')
        checks.update(consultation_is_optional=bool(consult) and all(plan(i).get('action_kind')=='optional' for i in consult),
            practice_requires_project_approval=bool(practice) and all('立项' in ' '.join(plan(i).get('conditions',[])) for i in practice),
            upload_depends_on_stamp_and_confirmation=bool(uploads) and all(bool(ancestors(i)&stamps) and bool(ancestors(i)&confirmations) for i in uploads),
            stamp_and_confirmation_require_the_form=bool(stamps and confirmations and forms) and all(bool(ancestors(i)&forms) for i in stamps|confirmations))
    return checks


def load_business():
    folder=ROOT/'artifacts/mvp-acceptance'
    fixture=json.loads((folder/'business-notice-normalized-1.8.0.json').read_text(encoding='utf8'))
    directory=Path(fixture['isolated_data_dir']).resolve();assert directory.is_relative_to(folder.resolve())
    conn=sqlite3.connect((directory/'campus.sqlite3').as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    try:
        notice=dict(conn.execute('SELECT * FROM notices WHERE id=?',(fixture['notice_id'],)).fetchone())
        sources=[dict(r) for r in conn.execute('SELECT * FROM sources WHERE notice_id=? AND active=1',(notice['id'],))]
        for source in sources:source['sections']=json.loads(source['sections'])
        profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(notice['user_id'],)).fetchone()[0])
    finally:conn.close()
    return {'id':'business','date':'2026-10-20','time':'00:00','forbidden_personal_dates':['2026-10-22'],
            'required_text':['签字盖章','确认意见','5天'],'expected_source_hashes':fixture['source_sha256'],
            'established_business_requirements':fixture['expected_before_request']},notice,sources,profile


def request(settings,case,notice,sources,profile,thinking):
    sources,system,content=prepare_notice_input(settings,notice,sources,profile)
    payload={'model':settings.ai_model,'messages':[{'role':'system','content':system},{'role':'user','content':content}],
             'response_format':{'type':'json_object'},'thinking':{'type':thinking},'max_completion_tokens':NOTICE_OUTPUT_TOKENS,
             'stream':True,'stream_options':{'include_usage':True}}
    if thinking=='disabled':payload['temperature']=0.2
    result={'case':case['id'],'thinking':thinking,'model':settings.ai_model,'prompt_sha256':hashlib.sha256((system+content).encode()).hexdigest(),
            'first_reasoning_seconds':None,'first_answer_seconds':None,'usage':None,'checks':{}}
    started=time.monotonic();parts=[];finish=None;size=0
    try:
        with httpx.Client(timeout=httpx.Timeout(settings.ai_timeout,connect=10),follow_redirects=False,trust_env=False) as client:
            with client.stream('POST',settings.ai_base_url+'/chat/completions',headers={'Authorization':'Bearer '+settings.ai_api_key},json=payload) as response:
                result.update(http_status=response.status_code,headers_seconds=round(time.monotonic()-started,3))
                if response.status_code!=200:raise RuntimeError('provider_http_'+str(response.status_code))
                for line in response.iter_lines():
                    size+=len(line.encode());elapsed=time.monotonic()-started
                    if size>4000000 or elapsed>360:raise RuntimeError('diagnostic_budget_exceeded')
                    if not line.startswith('data:'):continue
                    value=line[5:].strip()
                    if value=='[DONE]':continue
                    packet=json.loads(value)
                    if packet.get('usage'):result['usage']=packet['usage']
                    if not packet.get('choices'):continue
                    choice=packet['choices'][0];delta=choice.get('delta') or {}
                    if delta.get('reasoning_content') and result['first_reasoning_seconds'] is None:result['first_reasoning_seconds']=round(elapsed,3)
                    if delta.get('content'):
                        if result['first_answer_seconds'] is None:result['first_answer_seconds']=round(elapsed,3)
                        parts.append(delta['content'])
                    if choice.get('finish_reason'):finish=choice['finish_reason']
        result['provider_seconds']=round(time.monotonic()-started,3)
        if finish!='stop':raise ValueError('incomplete_'+str(finish))
        raw=json.loads(''.join(parts));result['raw_draft']=raw
        draft=validate_extraction(raw,sources,notice.get('published_at'));result['draft']=draft
        result['checks']=quality(case,draft);result['status']='passed' if all(result['checks'].values()) else 'quality_failed'
    except Exception as exc:
        result.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:350])
    result['total_seconds']=round(time.monotonic()-started,3)
    return result


def main():
    configure_text_output();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--suite',choices=['business','synthetic'],default='business')
    parser.add_argument('--output',required=True,help='New JSON filename under artifacts/mvp-acceptance')
    parser.add_argument('--model',choices=['mimo-v2.6-pro','mimo-v2.6-flash'])
    parser.add_argument('--thinking',choices=['enabled','disabled','both'],default='both')
    args=parser.parse_args();name=Path(args.output)
    if name.name!=args.output or name.suffix!='.json':parser.error('Output must be a JSON filename')
    folder=ROOT/'artifacts/mvp-acceptance';folder.mkdir(parents=True,exist_ok=True);path=folder/name
    if path.exists():parser.error('Output exists; preserve previous runs')
    settings=Settings.from_env()
    if args.model:settings=replace(settings,ai_model=args.model)
    inputs=[load_business()] if args.suite=='business' else [(case,{'title':'合成性能验收','source_label':'合成工程夹具','materials_complete':True,'published_at':'2026-10-18T15:00:00+08:00'},[text_source(case['text'])],{'school':'武汉大学','level':'全日制本科'}) for case in CASES]
    modes=['enabled','disabled'] if args.thinking=='both' else [args.thinking]
    report={'suite':args.suite,'method':'At most two concurrent requests per case; diagnostic observations, not independent participants or a throughput/P95 benchmark. No reasoning text stored.',
            'model':settings.ai_model,'thinking_modes':modes,
            'expected_before_requests':[i[0] for i in inputs],'implementation_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['app/ai.py','app/notice_references.py','app/action_plans.py']},'results':[]}
    save=lambda:path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    save()
    if not args.live:print(json.dumps({'prepared':str(path),'calls':0}));return
    if not settings.ai_api_key:raise SystemExit('A configured provider credential is required')
    with ThreadPoolExecutor(max_workers=2) as pool:
        for item in inputs:
            futures=[pool.submit(request,settings,*item,thinking) for thinking in modes]
            for future in as_completed(futures):
                result=future.result();report['results'].append(result);save()
                print(json.dumps({k:v for k,v in result.items() if k not in {'raw_draft','draft'}},ensure_ascii=False),flush=True)
    raise SystemExit(0 if all(r['status']=='passed' for r in report['results']) else 1)


if __name__=='__main__':main()
