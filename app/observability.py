"""Evidence levels and private request correlation; never probes a paid provider."""
from contextvars import ContextVar
from datetime import datetime
import json
import secrets
import time
from typing import Literal

from fastapi import Depends,HTTPException
from pydantic import Field

from .db import dumps,ident
from .models import Strict,TaskData

request_id=ContextVar('campus_request_id',default='')
from .operations_monitor import TABLES as MONITOR_TABLES,SCHEMA as MONITOR_SCHEMA

TABLES={'request_audit_links','deployment_checks'}|MONITOR_TABLES
SCHEMA="""
CREATE TABLE IF NOT EXISTS request_audit_links(
 audit_id INTEGER PRIMARY KEY REFERENCES audit(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS request_audit_id ON request_audit_links(request_id);
CREATE TABLE IF NOT EXISTS deployment_checks(
 id TEXT PRIMARY KEY, instance_id TEXT NOT NULL, actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
 kind TEXT NOT NULL, result TEXT NOT NULL, environment TEXT NOT NULL, evidence TEXT NOT NULL,
 observed_at TEXT NOT NULL, recorded_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS deployment_checks_instance ON deployment_checks(instance_id,recorded_at);
INSERT OR IGNORE INTO meta VALUES('observability_schema_version','1');
"""


def initialize(conn):
    conn.executescript(SCHEMA)
    conn.executescript(MONITOR_SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta VALUES('deployment_instance_id',?)",(ident(),))


class RequestTrace:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        rid=secrets.token_hex(16);token=request_id.set(rid)
        async def traced(message):
            if message['type']=='http.response.start':
                message['headers']=[*message.get('headers',[]),(b'x-request-id',rid.encode())]
            await send(message)
        try:await self.app(scope,receive,traced)
        finally:request_id.reset(token)


class CheckEvidence(Strict):
    kind:Literal['model','email_code','sms_code','push_device','email_reminder','public_source','campus_pilot','backup_restore']
    result:Literal['passed','failed','unknown']
    environment:str=Field(min_length=2,max_length=160)
    evidence:str=Field(min_length=5,max_length=1000)
    observed_at:str=Field(min_length=20,max_length=50)


def install(app,db,settings,user,admin,own_notice):
    from .cloud_messages import CloudMessages
    from .version import VERSION
    from .operations_monitor import install as install_monitor
    install_monitor(app,db,settings,admin)

    @app.get('/api/admin/readiness')
    def readiness(current=Depends(admin)):
        from .runtime_metrics import summary as database_timings
        now=int(time.time());sender=CloudMessages(settings)
        with db.connect() as conn:
            instance=conn.execute("SELECT value FROM meta WHERE key='deployment_instance_id'").fetchone()[0]
            def latest(table,where):return conn.execute('SELECT MAX(created_at) FROM '+table+' WHERE '+where).fetchone()[0]
            services={
                'model':{'configured':bool(settings.ai_api_key),'last_recorded_acceptance':latest('ai_calls',"status='succeeded'")},
                'email_code':{'configured':sender.available('email'),'last_recorded_acceptance':latest('auth_challenges',"channel='email' AND provider_id<>''")},
                'sms_code':{'configured':sender.available('sms'),'last_recorded_acceptance':latest('auth_challenges',"channel='sms' AND provider_id<>''")},
                'email_reminder':{'configured':sender.available('email'),'last_recorded_acceptance':latest('mail_outbox',"state='accepted'")},
                'push_device':{'configured':True,'last_recorded_acceptance':latest('push_outbox',"state='accepted'")},
                'public_source':{'configured':bool(conn.execute('SELECT 1 FROM source_subscriptions WHERE enabled=1 LIMIT 1').fetchone()),
                                 'last_recorded_acceptance':conn.execute('SELECT MAX(succeeded_at) FROM source_subscriptions WHERE enabled=1').fetchone()[0]},
            }
            checks=[dict(row) for row in conn.execute('SELECT kind,result,environment,evidence,observed_at,recorded_at FROM deployment_checks WHERE instance_id=? ORDER BY recorded_at DESC,rowid DESC LIMIT 50',(instance,))]
            for name,value in services.items():
                value['connection_state']='recorded_success' if value['last_recorded_acceptance'] else 'not_observed'
                value['end_to_end']=next((item for item in checks if item['kind']==name),None)
            queues={}
            for label,table in [('push','push_outbox'),('email','mail_outbox'),('publication','campus_deliveries'),('analysis','notice_automation_jobs')]:
                queues[label]={row['state']:row['count'] for row in conn.execute('SELECT state,COUNT(*) AS count FROM '+table+' GROUP BY state')}
        workers={name:('stopped' if task.done() else 'running') for name,task in app.state.worker_tasks.items()}
        return {'version':VERSION,'evaluated_at':now,'services':services,'queues':queues,'workers':workers,
                'frontend':{'bundled':app.state.frontend_bundled},'database_locks':database_timings(db.path),'checks':checks,
                'levels':['configuration_present','recorded_connection_success','operator_recorded_end_to_end'],
                'note':'记录中的成功只证明其标注范围。供应商接受不等于设备展示；端到端记录为管理员提交的证据，系统未代替独立验收。恢复备份后旧环境的验收不自动沿用。'}

    @app.post('/api/admin/readiness/evidence')
    def record(payload:CheckEvidence,current=Depends(admin)):
        try:
            observed=TaskData.valid_datetime(payload.observed_at)
            if datetime.fromisoformat(observed).timestamp()>time.time()+300:raise ValueError('future')
        except (ValueError,TypeError):raise HTTPException(422,'观察时间须带时区，且不能写未来的验收') from None
        from .security import rate_limit
        rate_limit(db,'deployment-evidence:'+current['id'],30,3600)
        with db.connect(write=True) as conn:
            instance=conn.execute("SELECT value FROM meta WHERE key='deployment_instance_id'").fetchone()[0]
            if conn.execute('SELECT COUNT(*) FROM deployment_checks WHERE instance_id=?',(instance,)).fetchone()[0]>=1000:
                raise HTTPException(413,'当前环境已达到1000条验收记录，请导出归档后按运维流程管理')
            rid=ident();now=int(time.time())
            conn.execute('INSERT INTO deployment_checks VALUES(?,?,?,?,?,?,?,?,?)',(rid,instance,current['id'],payload.kind,payload.result,payload.environment,payload.evidence,observed,now))
        return {'id':rid,'provenance':'operator_recorded','recorded_at':now}

    @app.get('/api/notices/{nid}/trace')
    def trace(nid:str,current=Depends(user)):
        with db.connect() as conn:
            own_notice(conn,nid,current['id'])
            actions=[dict(row) for row in conn.execute('''SELECT a.id,a.action,a.task_id,a.created_at,r.request_id
                FROM audit a LEFT JOIN request_audit_links r ON r.audit_id=a.id
                WHERE a.notice_id=? AND a.user_id=? ORDER BY a.id DESC LIMIT 100''',(nid,current['id']))]
            receipts=[dict(row) for row in conn.execute('SELECT id,source_label,created_at,observed_at FROM notice_ingest_receipts WHERE notice_id=? AND user_id=? ORDER BY created_at DESC LIMIT 100',(nid,current['id']))]
            calls=[dict(row) for row in conn.execute('SELECT id,status,model,created_at FROM ai_calls WHERE notice_id=? AND user_id=? ORDER BY created_at DESC LIMIT 100',(nid,current['id']))]
            tasks=[dict(row) for row in conn.execute('SELECT id,version,status,created_at,updated_at FROM tasks WHERE notice_id=? AND user_id=? ORDER BY created_at DESC LIMIT 100',(nid,current['id']))]
            deliveries=[]
            for channel,table in [('push','push_outbox'),('email','mail_outbox')]:
                rows=conn.execute('''SELECT id,state,event_key,due_at,created_at,finished_at FROM '''+table+'''
                    WHERE user_id=? AND json_valid(payload) AND (json_extract(payload,'$.url')=? OR
                    EXISTS(SELECT 1 FROM json_each(payload,'$.receipt_refs') r WHERE r.type='text' AND substr(r.value,1,length(?)+1)=?||':') OR
                    EXISTS(SELECT 1 FROM json_each(payload,'$.event_refs') r WHERE r.type='text' AND
                      (instr(':'||r.value||':',':'||?||':')>0 OR EXISTS(
                        SELECT 1 FROM tasks t WHERE t.user_id=? AND t.notice_id=? AND instr(':'||r.value||':',':'||t.id||':')>0) OR EXISTS(
                        SELECT 1 FROM notice_ingest_updates u WHERE u.notice_id=? AND instr(':'||r.value||':',':'||u.id||':')>0))))
                    ORDER BY created_at DESC LIMIT 100''',(current['id'],'/#notice/'+nid,nid,nid,nid,current['id'],nid,nid))
                deliveries.extend({'channel':channel,**dict(row)} for row in rows)
        return {'correlation_notice_id':nid,'actions':actions,'receipts':receipts,'model_calls':calls,'tasks':tasks,'deliveries':deliveries,
                'limit_per_stage':100,'note':'HTTP请求有独立请求ID，以本人通知与事务审计关联后续步骤；历史后台事件可能没有HTTP请求ID。这里只列当前保留的可证实状态。'}
