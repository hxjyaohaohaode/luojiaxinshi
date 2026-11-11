"""Owner-scoped inspection of the existing observe/analyse/notify pipeline.

Inspection never starts a model, contacts a provider, or grants a source access.
"""
import hashlib
import json
import time
from fastapi import Depends,HTTPException,Query
from .db import dumps,audit
from .proactive_feedback import Feedback,saved,apply as apply_feedback
from .notice_automation import profile_hash
from .proactive_policy import VERSION,assess,preferences


def evidence_chain(conn,uid,nid):
    from .source_coverage import coverage
    documents=[]
    for row in conn.execute('''SELECT s.id,s.name,s.kind,s.sha256,s.active,s.status,s.warning,o.data AS origin
            FROM sources s JOIN notices n ON n.id=s.notice_id
            LEFT JOIN notice_source_origins o ON o.source_id=s.id
            WHERE s.notice_id=? AND n.user_id=? ORDER BY s.created_at,s.id''',(nid,uid)):
        origin=json.loads(row['origin'] or '{}')
        reading = coverage({**dict(row), 'origin':origin})
        documents.append({**{key:row[key] for key in ('id','name','kind','sha256','active','status','warning')},
            'origin':origin,'coverage':reading,'missing_attachments':[item['url'] for item in reading['unread_attachments']]})
    notice=conn.execute('SELECT title,published_at FROM notices WHERE id=? AND user_id=?',(nid,uid)).fetchone()
    from .notice_network import relation
    related=[]
    for row in conn.execute('SELECT id,title,published_at FROM notices WHERE user_id=? AND id!=?',(uid,nid)):
        score=relation(dict(notice),dict(row))
        if score:related.append({**dict(row),'relationship':'candidate','verified':False,'score':round(score,3)})
    related=sorted(related,key=lambda r:(-r['score'],r['id']))[:10]
    return {'documents':documents,'related_notices':related,
        'policy':'直接附件链接证明引用关系；候选关联不证明适用、替代或取消效力。原文修订保留历史版本。'}

def assessment(conn,notice,profile):
    from .qq_group_intake import quiet_assessment, quiet_notices
    check=conn.execute('SELECT * FROM notice_profile_checks WHERE notice_id=?',(notice['id'],)).fetchone()
    digest=profile_hash(profile)
    current=notice['status'] in {'draft','confirmed'} and notice['draft_version']==notice['version'] and check and check['notice_version']==notice['version'] and check['profile_hash']==digest
    pref=preferences(profile)
    result=apply_feedback(assess(dict(notice),current_draft=bool(current),pref=pref),saved(conn,notice['user_id'],notice['id']))
    quiet=bool(quiet_notices(conn,notice['user_id'],notice['id']))
    if quiet:result=quiet_assessment(result)
    result['current_draft']=bool(current)
    result['decision_key']=hashlib.sha256(dumps([VERSION,notice['id'],notice['version'],digest,pref.model_dump(),result['tracking']['state'],result['feedback']['version'],quiet]).encode()).hexdigest()[:24]
    return result

def source_capabilities(conn,uid,now):
    from .source_sync import status
    result=[]
    for row in conn.execute('SELECT id,data FROM source_catalog WHERE user_id=? ORDER BY created_at DESC',(uid,)).fetchall():
        entry=json.loads(row['data']);sync=status(conn,row['id'],uid)
        enabled=bool(sync.get('enabled'))
        last=sync.get('succeeded_at')
        interval=(sync.get('config') or {}).get('interval_minutes',30)*60
        monitor=sync['state']
        if enabled and monitor=='active' and last and now-last>max(3*interval,3600):monitor='stale'
        platform=entry['platform']
        capability='website_column' if platform=='website' else 'connector_required' if platform=='wechat_public' else 'group_authorization_required' if platform in {'qq_group','wechat_group'} else 'manual'
        result.append({'id':row['id'],'name':entry['name'],'platform':platform,'capability':capability,
            'monitoring':monitor,'enabled':enabled,'last_checked_at':sync.get('checked_at'),
            'last_succeeded_at':last,'next_poll_at':sync.get('next_poll'),'error':sync.get('error',''),
            'pending_articles':sync.get('pending_count',0)})
    return result

def install(app,db,settings,user):
    @app.get('/api/admin/runtime')
    def runtime_status(current=Depends(user)):
        if current['role']!='admin':raise HTTPException(403,'需要系统管理员权限')
        from urllib.parse import urlsplit
        from .cloud_messages import CloudMessages
        from .notice_automation import POLL_SECONDS as analysis_poll
        workers={}
        for name,task in app.state.worker_tasks.items():
            state='running'
            if task.done():state='cancelled' if task.cancelled() else 'failed' if task.exception() else 'stopped'
            workers[name]=state
        now=int(time.time())
        with db.connect() as conn:
            conn.execute('SELECT 1').fetchone()
            queue={r['state']:r['total'] for r in conn.execute('SELECT state,count(*) AS total FROM notice_automation_jobs GROUP BY state')}
            oldest=conn.execute("SELECT min(created_at) FROM notice_automation_jobs WHERE state='queued'").fetchone()[0]
            stale=conn.execute("SELECT count(*) FROM notice_automation_jobs j JOIN notices n ON n.id=j.notice_id WHERE j.state='queued' AND j.input_version!=n.version").fetchone()[0]
            sources={r['state']:r['total'] for r in conn.execute("SELECT CASE WHEN enabled=0 THEN 'paused' WHEN error<>'' THEN 'incomplete' WHEN succeeded_at IS NULL THEN 'waiting' ELSE 'checked' END AS state,count(*) AS total FROM source_subscriptions GROUP BY state")}
            channels={table:{r['state']:r['total'] for r in conn.execute('SELECT state,count(*) AS total FROM '+table+' GROUP BY state')}
                for table in ('push_outbox','mail_outbox')}
        origin=urlsplit(settings.origin);sender=CloudMessages(settings)
        return {'generated_at':now,'database':'readable','worker_observation':'started' if workers else 'not_started',
            'workers':workers,'configuration':{'production':settings.production,
                'public_https':origin.scheme=='https' and origin.hostname not in {'localhost','127.0.0.1','::1'},
                'registration_mode':settings.registration_mode,'model':bool(settings.ai_api_key),
                'sms_verification':sender.available('sms'),'email':sender.available('email'),
                'operator_contact':bool(settings.operator_contact)},
            'analysis':{'jobs':queue,'oldest_wait_seconds':max(0,now-oldest) if oldest else 0,
                'obsolete_queued':stale,'poll_seconds':analysis_poll},'sources':sources,'delivery':channels,
            'external_delivery_verified':False,'note':'任务存活和配置存在不代表外部通道已送达；缺失与读取失败需分别核对。'}

    from .workspace_sync import install as install_workspace_sync
    install_workspace_sync(app,db,user)

    @app.put('/api/proactive/notices/{nid}/feedback')
    def feedback(nid:str,payload:Feedback,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=conn.execute('SELECT version FROM notices WHERE id=? AND user_id=?',(nid,current['id'])).fetchone()
            if not row:raise HTTPException(404,'通知不存在或无权访问')
            previous=saved(conn,current['id'],nid)
            if row['version']!=payload.notice_version or previous['version']!=payload.version:
                raise HTTPException(409,'通知或纠正记录已有更新，请读取最新内容后再操作')
            now=int(time.time())
            conn.execute('INSERT INTO notice_recommendation_feedback VALUES(?,?,?,?,?,?,?) ON CONFLICT(notice_id) DO UPDATE SET mode=excluded.mode,note=excluded.note,notice_version=excluded.notice_version,version=excluded.version,updated_at=excluded.updated_at',
                (nid,current['id'],payload.mode,payload.note,payload.notice_version,payload.version+1,now))
            result=saved(conn,current['id'],nid)
            audit(conn,current['id'],nid,'recommendation_feedback',before=previous,after=result)
            from .push_delivery import reconcile as reconcile_push
            from .mail_delivery import reconcile as reconcile_mail
            reconcile_push(conn,current['id'],now);reconcile_mail(conn,current['id'],now)
        return result

    @app.get('/api/proactive/status')
    def status(current=Depends(user)):
        from .cloud_messages import CloudMessages
        from .mail_delivery import preference
        from .notice_automation import status as automation_status
        from .agent_runtime.runtime import MODEL_CALL_LIMIT,REPEATED_TOOL_LIMIT
        from .source_sync import POLL_SECONDS
        from .notice_automation import POLL_SECONDS as AUTOMATION_POLL_SECONDS
        uid=current['id'];now=int(time.time())
        with db.connect() as conn:
            profile=conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]
            sources=source_capabilities(conn,uid,now)
            auto=automation_status(conn,uid)
            device_count=conn.execute('SELECT count(*) FROM push_devices WHERE user_id=? AND enabled=1',(uid,)).fetchone()[0]
            mail=preference(conn,uid)
            delivery={}
            for table,label in [('push_outbox','web_push'),('mail_outbox','email')]:
                delivery[label]={r['state']:r['total'] for r in conn.execute('SELECT state,count(*) AS total FROM '+table+' WHERE user_id=? GROUP BY state',(uid,))}
        return {'version':VERSION,'generated_at':now,'preferences':preferences(profile).model_dump(),
            'sources':sources,'coverage':{key:sum(s['monitoring']==key for s in sources) for key in ['active','waiting','error','stale','paused','manual','syncing']},
            'automation':{'enabled':auto['enabled'],'consented':bool(auto['consented_at']),
                'used_today':auto['used_today'],'daily_limit':auto['daily_limit'],'jobs':auto['counts']},
            'channels':{'web_push':{'enabled_devices':device_count},
                'email':{'configured':CloudMessages(settings).available('email'),'enabled_and_verified':bool(mail)},
                'sms':{'configured_for_verification':CloudMessages(settings).available('sms'),'notification_delivery':False},
                'wechat':{'owned_account_configured':bool(settings.wechat_publisher_app_id and settings.wechat_publisher_secret),'arbitrary_accounts_connected':False},
                'qq':{'application_configured':bool(settings.qq_bot_app_id and settings.qq_bot_secret)}},
            'delivery_states':delivery,'harness':{'chat_model_call_limit':MODEL_CALL_LIMIT,
                'repeated_tool_limit':REPEATED_TOOL_LIMIT,'source_poll_seconds':POLL_SECONDS,
                'automation_poll_seconds':AUTOMATION_POLL_SECONDS,
                'notice_analysis_model_call_limit':4 if settings.notice_auto_repair and settings.notice_semantic_review else 2 if settings.notice_semantic_review else 1,
                'mutations_require_business_validation':True,'provider_acceptance_is_not_read_receipt':True}}

    @app.get('/api/proactive/notices')
    def decisions(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=50),current=Depends(user)):
        with db.connect() as conn:
            profile=conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()[0]
            count=conn.execute('SELECT count(*) FROM notices WHERE user_id=?',(current['id'],)).fetchone()[0]
            rows=conn.execute('SELECT * FROM notices WHERE user_id=? ORDER BY updated_at DESC,id LIMIT ? OFFSET ?',
                              (current['id'],page_size,(page-1)*page_size)).fetchall()
            items=[{'id':row['id'],'title':row['title'],'version':row['version'],'status':row['status'],
                    'assessment':assessment(conn,row,profile)} for row in rows]
        return {'page':page,'page_size':page_size,'total':count,'items':items}

    @app.get('/api/proactive/notices/{nid}')
    def decision(nid:str,current=Depends(user)):
        with db.connect() as conn:
            notice=conn.execute('SELECT * FROM notices WHERE id=? AND user_id=?',(nid,current['id'])).fetchone()
            if not notice:raise HTTPException(404,'通知不存在或无权访问')
            profile=conn.execute('SELECT profile FROM users WHERE id=?',(current['id'],)).fetchone()[0]
            jobs=[dict(r) for r in conn.execute('SELECT id,input_version,result_version,state,attempts,error,created_at,started_at,finished_at FROM notice_automation_jobs WHERE notice_id=? AND user_id=? ORDER BY created_at DESC LIMIT 10',(nid,current['id']))]
            result=assessment(conn,notice,profile)
            keys=[r[0] for r in conn.execute('SELECT external_key FROM notice_ingest_receipts WHERE notice_id=? AND user_id=?',(nid,current['id']))]
            automatic=any(not key.startswith(('manual:','conversation:')) for key in keys)
            baseline=bool(conn.execute('SELECT 1 FROM notice_delivery_suppressions WHERE notice_id=?',(nid,)).fetchone())
            disposition=conn.execute('SELECT disposition FROM notice_dispositions WHERE notice_id=?',(nid,)).fetchone()
            active=(not disposition or disposition[0]=='inbox') and notice['status']!='confirmed'
            if not automatic or baseline or not active:result['delivery']='silent'
            chain=evidence_chain(conn,current['id'],nid)
            draft=json.loads(notice['draft'] or '{}')
        return {'notice_id':nid,'notice_version':notice['version'],'assessment':result,'analysis_runs':jobs,
                'applicability_reason':draft.get('applicability_reason',''),
                'evidence_chain':chain,
                'gates':{'automatic_receipt':automatic,'initial_snapshot':baseline,'inbox_active':active},
                'next_action':'核对个人条件或原文' if result['requires_review'] else '按当前个人通知偏好安排提醒'}
