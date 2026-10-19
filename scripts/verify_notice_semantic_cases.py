"""Predeclared paired semantic challenges, synthetic originals, opt-in provider calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.documents import text_source
from app.notice_semantics import review
from app.notice_progress import Trace
from app.console import configure_text_output


def step(title,**fields):return {'title':title,'scope':'personal','details':'','materials':[],**fields}
def plan(kind='required',deps=(),conditions=()):return {'action_kind':kind,'depends_on':list(deps),'conditions':list(conditions)}


def cases():
    pairs=[
        ('award','虚构通知：学院审核获奖名单后直接向获奖学生发放奖金，学生无需另行申请。',
         [step('学院审核获奖名单后直接发放奖金',scope='other')],{0:plan()},
         [step('本人填写奖金申请表并提交申请')],{0:plan()},'procedure'),
        ('optional','虚构通知：同学可自愿参加讲座，有意者报名。报名后收到主办方确认方可到场参加。',
         [step('自愿报名讲座'),step('自愿到场参加讲座')],{0:plan('optional'),1:plan('optional',[0],['已收到主办方确认'])},
         [step('必须报名讲座'),step('必须到场参加讲座')],{0:plan(),1:plan(deps=[0],conditions=['已收到主办方确认'])},'obligation'),
        ('deliverables','虚构通知：参赛团队须提交一个手机应用和一份测试报告，由老师验收。',
         [step('提交手机应用与测试报告',materials=['手机应用','测试报告'])],{0:plan()},
         [step('提交手机应用',materials=['手机应用'])],{0:plan()},'omission'),
        ('actor','虚构通知：本人于2027年11月20日17:00前提交申请表，学院于2027年11月30日前完成审核。',
         [step('本人提交申请表',due_date='2027-11-20',due_time='17:00'),step('学院完成审核',scope='other',due_date='2027-11-30',due_time=None)],{0:plan(),1:plan()},
         [step('本人提交申请表',due_date='2027-11-20',due_time='17:00'),step('本人完成学院审核',due_date='2027-11-30',due_time=None)],{0:plan(),1:plan()},'actor'),
        ('dependency','虚构通知：本人先下载并填写申请表，再持该表向学院申请签章；取得签章后方可上传该表。',
         [step('下载并填写申请表'),step('向学院申请取得签章'),step('上传已签章申请表')],{0:plan(),1:plan(deps=[0]),2:plan(deps=[1])},
         [step('下载并填写申请表'),step('向学院申请取得签章'),step('上传已签章申请表')],{0:plan(),1:plan(deps=[0]),2:plan(deps=[0])},'dependency'),
        ('condition','虚构通知：学院负责资格审核；只有资格审核通过的学生方可提交申请。',
         [step('提交申请'),step('学院审核学生资格',scope='other')],{0:plan('optional',conditions=['已通过学院资格审核']),1:plan()},
         [step('提交申请'),step('学院审核学生资格',scope='other')],{0:plan('optional'),1:plan()},'condition')]
    result=[]
    for key,text,good,good_plans,bad,bad_plans,code in pairs:
        for variant,tasks,plans in [('supported',good,good_plans),('changed',bad,bad_plans)]:
            result.append({'id':key+'-'+variant,'text':text,'expected':{'no_issues':variant=='supported','issue_code':code if variant=='changed' else None},
                'draft':{'summary':'请逐项核对虚构通知','applicability':'needs_review','applicability_reason':'个人资格待本人核实','facts':{},'warnings':[],
                         'tasks':deepcopy(tasks),'plans':deepcopy(plans)}})
    return result


def run(settings,case):
    trace=Trace();started=time.monotonic();result={'id':case['id']}
    try:
        found=review(settings,{'published_at':None},[text_source(case['text'])],{'campus_role':'student'},case['draft'],trace=trace)
        result['review']=found;expected=case['expected']
        result['passed']=not found['issues'] if expected['no_issues'] else any(issue['code']==expected['issue_code'] for issue in found['issues'])
    except Exception as exc:result.update(passed=False,error={'type':type(exc).__name__,'message':str(exc)[:250]})
    result.update(metrics=trace.snapshot(),elapsed_seconds=round(time.monotonic()-started,3));return result


def main():
    configure_text_output();parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--output',required=True)
    parser.add_argument('--case',action='append',choices=[c['id'] for c in cases()],help='Only run these predeclared cases; never overwrite earlier evidence.')
    args=parser.parse_args()
    name=Path(args.output)
    if name.name!=args.output or name.suffix!='.json':parser.error('Output must be a new JSON filename')
    folder=ROOT/'artifacts/mvp-acceptance';path=folder/name
    if path.exists():parser.error('Previous evidence must be preserved')
    selected=[case for case in cases() if not args.case or case['id'] in args.case]
    report={'method':'Predeclared synthetic cases; at most two concurrent calls. Not a real-user or independent-corpus accuracy estimate.',
        'implementation_sha256':hashlib.sha256((ROOT/'app/notice_semantics.py').read_bytes()).hexdigest(),
        'case_definition_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'expected_before_requests':selected,'results':[]}
    save=lambda:path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');save()
    if not args.live:print(json.dumps({'prepared':str(path),'calls':0}));return
    settings=Settings.from_env();report.update(model=settings.notice_review_model,thinking='enabled');save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,settings,case) for case in report['expected_before_requests']]
        for future in as_completed(futures):
            result=future.result();report['results'].append(result);save();print(json.dumps({k:v for k,v in result.items() if k!='review'},ensure_ascii=False),flush=True)
    raise SystemExit(0 if all(r['passed'] for r in report['results']) else 1)


if __name__=='__main__':main()
