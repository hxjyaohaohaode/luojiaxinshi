"""Read-only pilot snapshot: no OTP, mail, push or model requests.

Private profile/contact values, credentials, provider payloads and user IDs are
never included. This report cannot certify external delivery or school approval.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.cloud_messages import CloudMessages
from app.proactive import assessment
from app.notice_automation import today_start
from app.source_coverage import coverage
from scripts.audit_full_suite import fingerprint


def read(path):
    try:return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username',required=True)
    parser.add_argument('--local-env',action='store_true')
    parser.add_argument('--output',default='artifacts/full-audit-result.json')
    parser.add_argument('--backend-report',default='artifacts/full-audit-complete/summary.json')
    parser.add_argument('--frontend-log',default='artifacts/full-audit-complete-frontend.log')
    args=parser.parse_args()
    if args.local_env:
        from dotenv import load_dotenv
        load_dotenv(ROOT/'.env',override=True)
    settings=Settings.from_env();sender=CloudMessages(settings)
    conn=sqlite3.connect((settings.data_dir/'campus.sqlite3').as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    user=conn.execute('SELECT id,profile FROM users WHERE username=?',(args.username,)).fetchone()
    if not user:parser.error('The selected account does not exist; no data changed')
    uid=user['id'];records=[]
    for row in conn.execute('SELECT * FROM notices WHERE user_id=?',(uid,)):
        value=assessment(conn,row,user['profile'])
        records.append({'quality':value['quality'],'relevance':value['relevance'],'tracking':value['tracking']['state'],
            'recommended':value['recommended'],'current':value['current_draft'],'status':row['status']})
    def states(table):return dict(conn.execute('SELECT state,count(*) FROM '+table+' WHERE user_id=? GROUP BY state',(uid,)).fetchall())
    sources=[]
    for row in conn.execute('SELECT s.*,c.data FROM source_subscriptions s JOIN source_catalog c ON c.id=s.source_id WHERE s.user_id=?',(uid,)):
        cfg=json.loads(row['config']);sources.append({'name':json.loads(row['data'])['name'],'enabled':bool(row['enabled']),
            'interval_minutes':cfg['interval_minutes'],'last_checked_at':row['checked_at'],
            'next_poll_at':row['next_poll'],'partial_errors':bool(row['error']),
            'unread_items':conn.execute("SELECT count(*) FROM source_subscription_items WHERE source_id=? AND error<>''",(row['source_id'],)).fetchone()[0]})
    pref=conn.execute('SELECT enabled,daily_limit FROM notice_automation_settings WHERE user_id=?',(uid,)).fetchone()
    metadata={}
    for row in conn.execute('SELECT s.status,o.data FROM sources s JOIN notices n ON n.id=s.notice_id LEFT JOIN notice_source_origins o ON o.source_id=s.id WHERE n.user_id=? AND s.active=1',(uid,)):
        origin=json.loads(row['data'] or '{}')
        reading=coverage({'status':row['status'],'origin':origin})
        if reading['reading_incomplete']:
            metadata['material_records_with_reading_gaps']=metadata.get('material_records_with_reading_gaps',0)+1
        if reading['review_required']:
            metadata['material_records_requiring_review']=metadata.get('material_records_requiring_review',0)+1
        for item in reading['unread_attachments']:
            key='unread_attachment_'+item['state']
            metadata[key]=metadata.get(key,0)+1
    backend=read(args.backend_report)
    frontend={}
    try:
        log=(ROOT/args.frontend_log).read_text(encoding='utf-8-sig')
        for key in ('tests','pass','fail','skipped','cancelled'):
            match=re.search(r'\b'+key+r'\s+(\d+)\s*$',log,re.M)
            if match:frontend[key]=int(match[1])
    except OSError:pass
    report={'generated_at':int(time.time()),'read_only':True,'actual_record_count':len(records),
        'notice_states':{key:dict(Counter(r[key] for r in records)) for key in ('status','quality','relevance','tracking')},
        'current_notice_judgements':sum(r['current'] for r in records),
        'automatic_analysis':{'enabled':bool(pref and pref['enabled']),'daily_limit':pref['daily_limit'] if pref else None,
            'used_today':conn.execute('SELECT count(*) FROM notice_automation_attempts WHERE user_id=? AND started_at>=?',(uid,today_start())).fetchone()[0],
            'jobs':states('notice_automation_jobs')},'sources':sources,'evidence_gaps':metadata,
        'side_effect_ledgers':{table:states(table) for table in ('push_outbox','mail_outbox')},
        'database':{'integrity':conn.execute('PRAGMA quick_check').fetchone()[0],
            'foreign_key_violations':len(conn.execute('PRAGMA foreign_key_check').fetchall())},
        'configuration':{'production':settings.production,'public_https':settings.production and settings.origin.startswith('https://'),
            'model':bool(settings.ai_api_key),'sms_verification':sender.available('sms'),'email':sender.available('email'),
            'qq':bool(settings.qq_bot_app_id and settings.qq_bot_secret),
            'owned_wechat':bool(settings.wechat_publisher_app_id and settings.wechat_publisher_secret)},
        'tests':{'backend':backend,'frontend':frontend,'current_code_matches_backend_run':bool(backend and backend.get('implementation_sha256')==fingerprint())},
        'ui':read('artifacts/full-audit-ui/responsive-matrix.json'),
        'smtp_authentication':read('artifacts/full-audit-smtp-auth.json'),'smtp_network':read('artifacts/full-audit-smtp-network.json'),
        'controlled_real_model_recovery':read('artifacts/full-audit-live-review-recovery.json'),
        'actual_complex_notice_reviews':read('artifacts/full-audit-actual-review-outcomes.json'),
        'current_review_gaps':read('artifacts/full-audit-current-review-gaps.json'),
        'dependency_audits':{'python':read('artifacts/full-audit-python-dependencies.json'),
            'node_official_registry':read('artifacts/full-audit-node-dependencies-official.json')},
        'publishable_secret_scan':read('artifacts/full-audit-secret-scan.json'),
        'formal_pilot_acceptance':'not_verified','unverified':['actual SMS delivery to pilot users','actual email inbox delivery',
            'Android/iOS background delivery','public HTTPS persistence/restart','five days of real scenario records','institution acceptance']}
    conn.close()
    report['git']={'head':subprocess.check_output(['git','rev-parse','--short','HEAD'],cwd=ROOT,text=True).strip(),
        'ahead_behind':subprocess.check_output(['git','rev-list','--left-right','--count','HEAD...origin/main'],cwd=ROOT,text=True).strip(),
        'local_changes':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True))}
    path=(ROOT/args.output).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('actual_record_count','notice_states','automatic_analysis','database','git')},ensure_ascii=False))
    print(json.dumps({'backend_complete':bool(backend and backend.get('complete')),'tested_code_matches':report['tests']['current_code_matches_backend_run'],
        'frontend':frontend,'formal_pilot_acceptance':report['formal_pilot_acceptance']},ensure_ascii=False))


if __name__=='__main__':main()
