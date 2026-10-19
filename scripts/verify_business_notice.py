"""Opt-in real-provider check using the supplied competition notice and topic file.

The source text is supplied project material, not a new institutional verification.
All account/profile data and the decision to participate are synthetic test inputs.
"""
import argparse
from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from app import ai
from app.config import Settings
from app.main import create_app
from app.version import VERSION
from app.model_catalog import TEXT_MODELS,validate as validate_models,channel,notice_settings
from app.console import configure_text_output


def main():
    configure_text_output()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--label',choices=['baseline','verified','verified-fix','normalized','streamed','reviewed','accelerated','accelerated-dates'],default='baseline')
    parser.add_argument('--extract-model',choices=sorted(TEXT_MODELS))
    parser.add_argument('--review-model',choices=sorted(TEXT_MODELS))
    parser.add_argument('--processing-mode',choices=['configured','fast'],default='configured')
    parser.add_argument('--keep-fixture',action='store_true',help='Keep the isolated generated draft for browser review; never use the production database.')
    args=parser.parse_args()
    if args.processing_mode=='fast' and (args.extract_model or args.review_model):parser.error('Use either the request mode or explicit model overrides')
    folder=ROOT/'artifacts/mvp-acceptance';folder.mkdir(parents=True,exist_ok=True)
    source_root=ROOT/'项目资料/官方文件'
    names=['大赛通知.md','校园通知智能转办助手_项目需求.md']
    sources={name:(source_root/name).read_bytes() for name in names}
    expected={'personal_cutoff_date':'2026-10-20','personal_cutoff_time':'00:00',
              'original_cutoff':'2026年10月19日24:00','unit_review_day':'2026-10-22',
              'minimum_distinct_steps':3,'requires_human_confirmation':True,
              'applicant_must_request_stamp':True,'applicant_must_request_topic_confirmation':True,
              'consultation_is_optional':True,'practice_requires_project_approval':True,'upload_depends_on_stamp_and_confirmation':True,
              'stamp_and_confirmation_require_the_form':True,
              'independent_review_complete':True,'maximum_provider_requests':2,
              'delivery_items_present_or_flagged':['智能体','工作台','数据看板'],
              'training_not_forced_or_flagged':True,
              'source_meaning':'The supplied notice says 19 October at 24:00; this is 20 October at 00:00. The 22 October review belongs to the institution.'}
    report={'app_version':VERSION,'sample':'Supplied real competition material; synthetic participant profile; no claim of newly verified publication.',
            'source_sha256':{name:hashlib.sha256(data).hexdigest() for name,data in sources.items()},
            'implementation_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                     ['app/ai.py','app/deadline_evidence.py','app/notice_references.py','app/models.py','app/action_plans.py','app/notice_semantics.py','app/notice_progress.py']},
            'expected_before_request':expected,'checks':{},'model_calls':0}
    path=folder/f'business-notice-{args.label}-{VERSION}.json'
    if path.exists():parser.error('Output exists; previous evidence must be preserved')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.live:
        print(json.dumps({'prepared':str(path),'model_calls':0},ensure_ascii=False));return
    original_validator=ai.validate_extraction
    def observed(raw,*rest):
        report['raw_draft']=raw
        return original_validator(raw,*rest)
    ai.validate_extraction=observed
    try:
        fixture=nullcontext(tempfile.mkdtemp(prefix='business-notice-',dir=folder)) if args.keep_fixture else tempfile.TemporaryDirectory(prefix='business-notice-',dir=folder)
        with fixture as directory:
            if args.keep_fixture:report['isolated_data_dir']=directory
            settings=replace(Settings.from_env(),data_dir=Path(directory),origin='http://testserver',ai_grounding=False)
            settings=replace(settings,ai_model=args.extract_model or settings.ai_model,notice_review_model=args.review_model or settings.notice_review_model)
            if args.processing_mode=='fast':settings=replace(settings,notice_fast_enabled=True)
            validate_models(settings)
            run_settings=notice_settings(settings,args.processing_mode)
            report.update(processing_mode=args.processing_mode,extraction_model=run_settings.ai_model,review_model=run_settings.notice_review_model,billing_channel=channel(settings.ai_base_url),
                configured_models_before=[settings.ai_model,settings.notice_review_model])
            if not settings.ai_api_key:raise RuntimeError('Configured credential is required')
            app=create_app(settings)
            with TestClient(app,base_url='http://testserver',headers={'Origin':'http://testserver','X-Requested-With':'campus-notice'}) as client:
                registered=client.post('/api/auth/register',json={'username':'business.notice.fixture','password':'Isolated-Notice-Fixture-2026','display_name':'虚构参赛负责人','accepted_terms':True})
                assert registered.status_code==200,registered.text
                client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
                profile={'school':'武汉大学','campus_role':'student','level':'全日制本科','college':'资源与环境科学学院','grade':'2025级',
                         'goals':'工程验收假设：本人已决定参加揭榜挂帅类，选择校园通知智能转办助手榜题，并担任团队负责人。团队成员和指导教师的完整资格仍需核对。'}
                assert client.put('/api/profile',json=profile).status_code==200
                record=client.post('/api/notices',data={'title':'赛事通知业务验收样本','body':sources[names[0]].decode('utf-8'),
                    'source_label':'用户提供的青春珞珈赛事通知文本，发布来源未经本次重新核验',
                    'published_at':'2026-10-02T13:38:00+08:00','materials_complete':'true'},
                    files=[('files',(names[1],sources[names[1]],'text/markdown'))])
                assert record.status_code==200,record.text
                notice=record.json();report['notice_id']=notice['id'];report['parsed_sources']=[{'name':s['name'],'status':s['status'],'sections':len(s['sections'])} for s in notice['sources']]
                assert all(s['status']=='ok' for s in notice['sources'])
                started=time.monotonic();report['model_calls']=1;report['model']=run_settings.ai_model
                response=client.post('/api/notices/'+notice['id']+'/generate',json={'version':notice['version'],'allow_external_processing':True,'processing_mode':args.processing_mode})
                report['elapsed_seconds']=round(time.monotonic()-started,3);report['http_status']=response.status_code
                if response.status_code!=200:
                    report['error']=response.json();report['checks']['request_succeeded']=False
                else:
                    report['draft']=draft=response.json()['draft'];personal=[t for t in draft['tasks'] if t['scope']=='personal']
                    uploads=[t for t in personal if any(w in t['title']+t['details'] for w in ['上传','提交报名','报名材料'])]
                    report['checks']={'request_succeeded':True,'eight_fact_categories':set(draft['facts'])==ai.FACT_KEYS,
                        'explicit_end_of_day_preserved':any(t['due_date']==expected['personal_cutoff_date'] and t['due_time']==expected['personal_cutoff_time'] for t in uploads),
                        'unit_review_not_personal_deadline':all(t['due_date']!=expected['unit_review_day'] for t in personal),
                        'multiple_personal_steps':len(personal)>=expected['minimum_distinct_steps'],
                        'applicant_requests_stamp':any('盖章' in t['title']+t['details'] or '签章' in t['title']+t['details'] for t in personal),
                        'applicant_requests_topic_confirmation':any('发榜单位' in t['title']+t['details'] and '确认' in t['title']+t['details'] for t in personal),
                        'not_automatically_confirmed':all(not t['deadline_confirmed'] and t['reminder_at'] is None and t['planned_at'] is None for t in draft['tasks']),
                        'no_tasks_before_confirmation':client.get('/api/tasks').json()==[]}
                    report['personal_steps']=[{'title':t['title'],'due_date':t['due_date'],'due_time':t['due_time'],'uncertainties':t['uncertainties']} for t in personal]
                    plans=draft.get('plans',{})
                    def plan(index):return plans.get(str(index),plans.get(index,{}))
                    def matching(words):return {i for i,t in enumerate(draft['tasks']) if t['scope']=='personal' and all(w in t['title'] for w in words)}
                    consult=matching(['咨询']);practice=matching(['实践']);stamps=matching(['签章'])|matching(['签字盖章']);confirmations=matching(['发榜单位','确认'])
                    ancestors=set();stack=list(matching(['上传']))
                    while stack:
                        index=stack.pop()
                        for dep in plan(index).get('depends_on',[]):
                            if dep not in ancestors:ancestors.add(dep);stack.append(dep)
                    report['checks'].update(consultation_is_optional=bool(consult) and all(plan(i).get('action_kind')=='optional' for i in consult),
                        practice_requires_project_approval=bool(practice) and all('立项' in ' '.join(plan(i).get('conditions',[])) for i in practice),
                        upload_depends_on_stamp_and_confirmation=bool(stamps&ancestors) and bool(confirmations&ancestors))
                    forms=matching(['下载'])|matching(['填写','报名'])
                    def predecessors(index):
                        found=set();pending=[index]
                        while pending:
                            for dep in plan(pending.pop()).get('depends_on',[]):
                                if dep not in found:found.add(dep);pending.append(dep)
                        return found
                    report['checks']['stamp_and_confirmation_require_the_form']=bool(stamps and confirmations and forms) and all(bool(predecessors(i)&forms) for i in stamps|confirmations)
                    if settings.notice_semantic_review:
                        quality=draft.get('quality',{})
                        report['checks']['independent_review_complete']=quality.get('status') in {'passed','needs_review'} and quality.get('checked_tasks')==len(draft['tasks'])
                        delivery_words=expected['delivery_items_present_or_flagged'];issues=quality.get('issues',[])
                        personal_content=' '.join(t['title']+' '+t['details']+' '+' '.join(t['materials']) for t in personal)
                        report['checks']['delivery_items_present_or_flagged']=all(word in personal_content for word in delivery_words) or any(issue['code']=='omission' and all(word in issue['message'] for word in delivery_words) for issue in issues)
                        training=[i for i,t in enumerate(draft['tasks']) if t['scope']=='personal' and '培训' in t['title']]
                        report['checks']['training_not_forced_or_flagged']=all(plan(i).get('action_kind')!='required' or any(issue['task_index']==i and issue['code']=='obligation' for issue in issues) for i in training)
                with app.state.db.connect() as conn:
                    report['usage']=[dict(r) for r in conn.execute('SELECT model,status,input_tokens,output_tokens FROM ai_calls')]
                    report['pipeline_metrics']=[json.loads(row[0]) for row in conn.execute('SELECT metrics FROM execution_metrics')]
                    report['model_calls']=sum(item.get('call_count',1) for item in report['pipeline_metrics'])
                    report['checks']['bounded_provider_calls']=report['model_calls']<=expected['maximum_provider_requests']
                    report['configured_models_after']=[settings.ai_model,settings.notice_review_model]
                    report['checks']['shared_configuration_unchanged']=report['configured_models_before']==report['configured_models_after']
    except Exception as exc:
        report['local_error']={'type':type(exc).__name__,'message':str(exc)[:250]};report['checks']['completed']=False
    finally:
        ai.validate_extraction=original_validator
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'raw_draft','draft'}},ensure_ascii=False))
    raise SystemExit(0 if report['checks'] and all(report['checks'].values()) else 1)


if __name__=='__main__':main()
