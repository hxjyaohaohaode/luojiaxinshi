"""Independent administrator incidents from local, observable operating evidence.

No student reminder, provider request, email or device delivery is emitted here.
Expiry dates and aggregate budget thresholds are explicitly operator supplied.
"""
from datetime import datetime, timezone, timedelta
import json
import hashlib
import shutil
import time

from fastapi import Depends, HTTPException
from pydantic import Field, field_validator

from .db import dumps, ident
from .models import Strict, TaskData

TABLES={'deployment_monitor_settings','deployment_incidents','deployment_incident_events','deployment_monitor_reads'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS deployment_monitor_settings(
 instance_id TEXT PRIMARY KEY,data TEXT NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS deployment_incidents(
 id TEXT PRIMARY KEY,instance_id TEXT NOT NULL,condition_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('open','resolved')),opened_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL,resolved_at INTEGER,acknowledged_at INTEGER,
 acknowledged_by TEXT REFERENCES users(id) ON DELETE SET NULL,details TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS deployment_incident_open
 ON deployment_incidents(instance_id,condition_key) WHERE state='open';
CREATE INDEX IF NOT EXISTS deployment_incident_history ON deployment_incidents(instance_id,updated_at);
CREATE TABLE IF NOT EXISTS deployment_incident_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,instance_id TEXT NOT NULL,
 incident_id TEXT NOT NULL REFERENCES deployment_incidents(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,created_at INTEGER NOT NULL,details TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS deployment_incident_event_instance ON deployment_incident_events(instance_id,id);
CREATE TABLE IF NOT EXISTS deployment_monitor_reads(
 instance_id TEXT NOT NULL,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_id INTEGER NOT NULL,PRIMARY KEY(instance_id,user_id));
"""


class MonitorSettings(Strict):
    queue_age_minutes:int=Field(default=15,ge=1,le=10080)
    source_failure_minutes:int=Field(default=30,ge=1,le=10080)
    disk_min_free_mb:int=Field(default=512,ge=1,le=1048576)
    backup_age_hours:int=Field(default=36,ge=1,le=720)
    quota_budget_units:int|None=Field(default=None,ge=1,le=100000000)
    credential_expiries:dict[str,str]=Field(default_factory=dict,max_length=20)

    @field_validator('credential_expiries')
    @classmethod
    def valid_expiry(cls,value):
        result={}
        for label,date in value.items():
            if not 1<=len(label.strip())<=80 or any(ord(c)<32 for c in label):
                raise ValueError('凭证监测填写1—80字用途标签，不填写密钥')
            result[label.strip()]=TaskData.valid_datetime(date)
        return result


class Seen(Strict):
    through_event_id:int=Field(ge=0)


class MonitorSettingsUpdate(MonitorSettings):
    expected_revision:str=Field(pattern=r'^[0-9a-f]{64}$')


def instance(conn):
    return conn.execute("SELECT value FROM meta WHERE key='deployment_instance_id'").fetchone()[0]


def settings_for(conn):
    row=conn.execute('SELECT data FROM deployment_monitor_settings WHERE instance_id=?',(instance(conn),)).fetchone()
    return MonitorSettings.model_validate_json(row[0]) if row else MonitorSettings()


def settings_revision(policy):
    return hashlib.sha256(dumps(policy.model_dump()).encode()).hexdigest()


def collect(db,settings,now=None):
    """Only bounded aggregate metadata; no notification bodies or destinations."""
    now=int(time.time() if now is None else now);measurements={}
    def add(key,title,state,**evidence):
        measurements[key]={'title':title,'state':state,'observed_at':now,**evidence}
    with db.connect() as conn:
        policy=settings_for(conn)
        for label,table,stamp,states in [
            ('push','push_outbox','due_at',('pending','leased')),
            ('email','mail_outbox','due_at',('pending','sending')),
            ('publication','campus_deliveries','updated_at',('pending',)),
            ('analysis','notice_automation_jobs','created_at',('queued','running'))]:
            marks=','.join('?' for _ in states)
            row=conn.execute(f'SELECT COUNT(*) AS n,MIN({stamp}) AS oldest FROM {table} WHERE state IN ({marks}) AND {stamp}<=?',(*states,now)).fetchone()
            age=max(0,now-row['oldest']) if row['oldest'] is not None else 0
            add('queue:'+label,{'push':'设备推送队列','email':'邮件提醒队列','publication':'校园派发队列','analysis':'自动整理队列'}[label],
                'problem' if age>=policy.queue_age_minutes*60 else 'healthy',pending=row['n'],oldest_age_seconds=age,threshold_seconds=policy.queue_age_minutes*60)
        # At least two completed consecutive failed/partial acquisitions, over
        # the configured duration. A current failure alone is not "persistent".
        failed=0;oldest=0
        for sub in conn.execute("SELECT source_id FROM source_subscriptions WHERE enabled=1 AND error<>''"):
            runs=conn.execute('SELECT started_at,data FROM source_acquisition_runs WHERE source_id=? AND finished_at IS NOT NULL ORDER BY started_at DESC,rowid DESC LIMIT 100',(sub[0],)).fetchall()
            consecutive=[]
            for run in runs:
                if json.loads(run['data']).get('state') not in {'failed','partial'}:break
                consecutive.append(run['started_at'])
            if len(consecutive)>=2 and now-min(consecutive)>=policy.source_failure_minutes*60:
                failed+=1;oldest=max(oldest,now-min(consecutive))
        add('source:continuous','来源持续失败','problem' if failed else 'healthy',affected_sources=failed,
            oldest_age_seconds=oldest,threshold_seconds=policy.source_failure_minutes*60,
            scope='仅已启用来源；暂停或移除后退出监测，不等同外部网站恢复')
        has_users=bool(conn.execute('SELECT 1 FROM users LIMIT 1').fetchone())
        # These are existing enforcement counters, not money or provider billing.
        day=datetime.fromtimestamp(now,timezone(timedelta(hours=8))).date().isoformat()
        units=conn.execute("SELECT COALESCE(SUM(count),0) FROM limits WHERE reset_at>? AND (key LIKE ? OR key LIKE 'agent-model:%')",(now,'ai:%:'+day)).fetchone()[0]
        add('budget:quota','模型额度计数预算','unknown' if policy.quota_budget_units is None else 'problem' if units>=policy.quota_budget_units else 'healthy',
            used_units=units,threshold_units=policy.quota_budget_units,
            scope='合计现有AI日额度与Agent滚动额度计数；不是模型调用账单、金额或供应商余额；未配置预算时未知')
    try:
        free=shutil.disk_usage(settings.data_dir).free
        add('disk:free','数据盘剩余空间','problem' if free<policy.disk_min_free_mb*1024*1024 else 'healthy',free_bytes=free,threshold_bytes=policy.disk_min_free_mb*1024*1024)
    except OSError:
        add('disk:free','数据盘剩余空间','unknown',reason='本次不能读取磁盘空间；不会因此自动关闭已有告警')
    try:
        backups=[p.stat().st_mtime for p in (settings.data_dir/'backups').glob('auto-*.sqlite3') if p.is_file() and not p.is_symlink()]
        latest=max(backups,default=None);age=max(0,now-latest) if latest is not None else None
        state='healthy' if not has_users else 'problem' if age is None or age>policy.backup_age_hours*3600 else 'healthy'
        add('backup:age','自动备份新鲜度',state,last_snapshot_at=latest,age_seconds=age,threshold_seconds=policy.backup_age_hours*3600,
            scope='只检查快照存在及修改时间；完整性和实际恢复另行验收')
    except OSError:
        add('backup:age','自动备份新鲜度','unknown',reason='本次不能读取备份目录；不会因此自动关闭已有告警')
    if not policy.credential_expiries:
        add('credentials:coverage','凭证有效期','unknown',reason='未登记供应商明确给出的到期时间；不能从密钥存在推断未过期')
    for label,date in policy.credential_expiries.items():
        expires=datetime.fromisoformat(date).timestamp()
        add('credential:'+label,'凭证期限：'+label,'problem' if expires<=now+7*86400 else 'healthy',expires_at=date,
            seconds_remaining=int(expires-now),provenance='operator_recorded',warning_seconds=7*86400)
    return {'evaluated_at':now,'settings':policy.model_dump(),'measurements':measurements,
            'scope':'独立管理员站内告警，每60秒检查；确认不等于恢复。恢复消息只表示当前检查不再触发（可能含配置改变或停用）。不自动发送邮件或手机提醒。'}


def reconcile(conn,snapshot):
    now=snapshot['evaluated_at'];iid=instance(conn);measurements=snapshot['measurements']
    active={row['condition_key']:dict(row) for row in conn.execute("SELECT * FROM deployment_incidents WHERE instance_id=? AND state='open'",(iid,))}
    def event(rid,kind,details):
        conn.execute('INSERT INTO deployment_incident_events(instance_id,incident_id,kind,created_at,details) VALUES(?,?,?,?,?)',(iid,rid,kind,now,dumps(details)))
    for key,value in measurements.items():
        if value['state']!='problem':continue
        if key in active:
            conn.execute('UPDATE deployment_incidents SET details=?,updated_at=? WHERE id=?',(dumps(value),now,active[key]['id']))
        else:
            rid=ident()
            conn.execute("INSERT INTO deployment_incidents VALUES(?,?,?,'open',?,?,NULL,NULL,NULL,?)",(rid,iid,key,now,now,dumps(value)))
            event(rid,'opened',value)
    for key,row in active.items():
        value=measurements.get(key,{'state':'healthy','reason':'监测项目已移除，不代表供应商已接通'})
        if value['state']!='healthy':continue
        conn.execute("UPDATE deployment_incidents SET state='resolved',updated_at=?,resolved_at=?,details=? WHERE id=?",(now,now,dumps(value),row['id']))
        event(row['id'],'resolved',value)
    conn.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('deployment_monitor_snapshot',dumps({'instance_id':iid,**snapshot})))
    # Open incidents are retained. Resolved history and events are bounded.
    conn.execute("DELETE FROM deployment_incidents WHERE instance_id=? AND state='resolved' AND id NOT IN (SELECT id FROM deployment_incidents WHERE instance_id=? AND state='resolved' ORDER BY updated_at DESC LIMIT 500)",(iid,iid))


def tick(db,settings,now=None):
    snapshot=collect(db,settings,now)
    with db.connect(write=True) as conn:reconcile(conn,snapshot)
    return snapshot


def install(app,db,settings,admin):
    @app.get('/api/admin/monitor')
    def monitor(current=Depends(admin)):
        with db.connect() as conn:
            iid=instance(conn)
            saved=conn.execute("SELECT value FROM meta WHERE key='deployment_monitor_snapshot'").fetchone()
            snapshot=json.loads(saved[0]) if saved else None
            if snapshot and snapshot.get('instance_id')!=iid:snapshot=None
            read=conn.execute('SELECT event_id FROM deployment_monitor_reads WHERE instance_id=? AND user_id=?',(iid,current['id'])).fetchone()
            seen=read[0] if read else 0
            incidents=[{**dict(row),'details':json.loads(row['details'])} for row in conn.execute('SELECT id,condition_key,state,opened_at,updated_at,resolved_at,acknowledged_at,details FROM deployment_incidents WHERE instance_id=? ORDER BY state ASC,updated_at DESC LIMIT 100',(iid,))]
            events=[{**dict(row),'details':json.loads(row['details'])} for row in conn.execute('SELECT id,incident_id,kind,created_at,details FROM deployment_incident_events WHERE instance_id=? ORDER BY id DESC LIMIT 100',(iid,))]
            unread=conn.execute('SELECT COUNT(*) FROM deployment_incident_events WHERE instance_id=? AND id>?',(iid,seen)).fetchone()[0]
            policy=settings_for(conn)
            return {'snapshot':snapshot,'settings':policy.model_dump(),'settings_revision':settings_revision(policy),'incidents':incidents,'events':events,'unread_events':unread,'seen_through':seen}

    @app.post('/api/admin/monitor/scan')
    def scan(current=Depends(admin)):
        from .security import rate_limit
        rate_limit(db,'monitor-scan:'+current['id'],12,60)
        return tick(db,settings)

    @app.put('/api/admin/monitor/settings')
    def configure(payload:MonitorSettingsUpdate,current=Depends(admin)):
        with db.connect(write=True) as conn:
            if payload.expected_revision!=settings_revision(settings_for(conn)):
                raise HTTPException(409,'监测设置已由另一页面更新，请重新打开后核对')
            policy=MonitorSettings.model_validate(payload.model_dump(exclude={'expected_revision'}))
            conn.execute('INSERT INTO deployment_monitor_settings VALUES(?,?,?) ON CONFLICT(instance_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',(instance(conn),policy.model_dump_json(),int(time.time())))
        return tick(db,settings)

    @app.post('/api/admin/monitor/incidents/{rid}/acknowledge')
    def acknowledge(rid:str,current=Depends(admin)):
        now=int(time.time())
        with db.connect(write=True) as conn:
            iid=instance(conn)
            row=conn.execute('SELECT * FROM deployment_incidents WHERE id=? AND instance_id=?',(rid,iid)).fetchone()
            if not row:raise HTTPException(404,'当前环境没有此告警')
            if not row['acknowledged_at']:
                conn.execute('UPDATE deployment_incidents SET acknowledged_at=?,acknowledged_by=? WHERE id=?',(now,current['id'],rid))
                conn.execute('INSERT INTO deployment_incident_events(instance_id,incident_id,kind,created_at,details) VALUES(?,?,?,?,?)',(iid,rid,'acknowledged',now,dumps({'meaning':'管理员已确认接手；不代表故障恢复'})))
        return {'id':rid,'acknowledged':True,'state':row['state']}

    @app.post('/api/admin/monitor/seen')
    def mark_seen(payload:Seen,current=Depends(admin)):
        with db.connect(write=True) as conn:
            iid=instance(conn)
            maximum=conn.execute('SELECT COALESCE(MAX(id),0) FROM deployment_incident_events WHERE instance_id=?',(iid,)).fetchone()[0]
            if payload.through_event_id>maximum:raise HTTPException(422,'只能确认当前已展示的告警消息')
            conn.execute('INSERT INTO deployment_monitor_reads VALUES(?,?,?) ON CONFLICT(instance_id,user_id) DO UPDATE SET event_id=MAX(event_id,excluded.event_id)',(iid,current['id'],payload.through_event_id))
        return {'seen_through':payload.through_event_id}
