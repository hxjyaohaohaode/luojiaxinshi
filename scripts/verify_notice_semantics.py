"""Opt-in audit of a retained real draft; no changes to app settings or user data."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.notice_semantics import review
from app.notice_progress import Trace
from app.console import configure_text_output


def main():
    configure_text_output();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true');parser.add_argument('--output',required=True)
    parser.add_argument('--model',choices=['mimo-v2.6-flash','mimo-v2.6-pro','mimo-v2.6-pro-ultraspeed'],default='mimo-v2.6-flash')
    parser.add_argument('--thinking',choices=['enabled','disabled'],default='enabled')
    parser.add_argument('--fixture',choices=['business-notice-streamed-1.8.1.json','business-notice-reviewed-1.9.0.json','business-notice-accelerated-1.9.0.json'],default='business-notice-streamed-1.8.1.json')
    args=parser.parse_args();folder=ROOT/'artifacts/mvp-acceptance';name=Path(args.output)
    if name.name!=args.output or name.suffix!='.json':parser.error('Output must be a new JSON filename')
    path=folder/name
    if path.exists():parser.error('Previous evidence must be preserved')
    fixture=folder/args.fixture;saved=json.loads(fixture.read_text(encoding='utf8'))
    directory=Path(saved['isolated_data_dir']).resolve();assert directory.is_relative_to(folder.resolve())
    conn=sqlite3.connect((directory/'campus.sqlite3').as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    try:
        notice=dict(conn.execute('SELECT * FROM notices WHERE id=?',(saved['notice_id'],)).fetchone())
        sources=[dict(r) for r in conn.execute('SELECT * FROM sources WHERE notice_id=? AND active=1',(notice['id'],))]
        for source in sources:source['sections']=json.loads(source['sections'])
        profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(notice['user_id'],)).fetchone()[0])
    finally:conn.close()
    initial=fixture.name=='business-notice-streamed-1.8.1.json'
    expected={'flags_invented_reward_application':19,'flags_training_mandatory':10,'flags_missing_deliverables':13,
            'preserves_legitimate_stamp_request':4,'preserves_legitimate_topic_confirmation_request':5} if initial else {
            'flags_missing_delivery_action_and_deliverables':True,'preserves_legitimate_stamp_request':7,'preserves_legitimate_topic_confirmation_request':9,
            'training_is_already_unclassified':13,'checks_both_original_sources':True}
    if fixture.name=='business-notice-accelerated-1.9.0.json':expected.update(preserves_legitimate_stamp_request=6,preserves_legitimate_topic_confirmation_request=8,training_is_already_unclassified=12)
    report={'model':args.model,'thinking':args.thinking,'fixture':fixture.name,'input_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'implementation_sha256':hashlib.sha256((ROOT/'app/notice_semantics.py').read_bytes()).hexdigest(),
        'expected_before_request':expected,'model_calls':0}
    save=lambda:path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');save()
    if not args.live:print(json.dumps({'prepared':str(path),'model_calls':0}));return
    trace=Trace();report['model_calls']=1;started=time.monotonic()
    try:
        result=review(Settings.from_env(),notice,sources,profile,saved['draft'],model=args.model,trace=trace,thinking=args.thinking);report['review']=result
        indices={item['task_index'] for item in result['issues']}
        report['checks']={'missing_deliverables_flagged':any(item['code']=='omission' and any(w in item['message'] for w in ['智能体','工作台','看板']) for item in result['issues']),
            'legitimate_stamp_not_rejected':expected['preserves_legitimate_stamp_request'] not in indices,
            'legitimate_confirmation_not_rejected':expected['preserves_legitimate_topic_confirmation_request'] not in indices,
            'both_sources_checked':len(result.get('source_checks',[]))==len(sources)}
        if initial:report['checks'].update(reward_application_flagged=19 in indices,training_mandatory_flagged=10 in indices)
        else:report['checks']['training_not_mandatory_misreport']=not any(item['task_index']==expected['training_is_already_unclassified'] and item['code']=='obligation' and '必办' in item['message'] for item in result['issues'])
    except Exception as exc:report['error']={'type':type(exc).__name__,'message':str(exc)[:250]}
    finally:report.update(elapsed_seconds=round(time.monotonic()-started,3),metrics=trace.snapshot());save()
    print(json.dumps({k:v for k,v in report.items() if k!='review'},ensure_ascii=False))
    raise SystemExit(0 if report.get('checks') and all(report['checks'].values()) else 1)


if __name__=='__main__':main()
