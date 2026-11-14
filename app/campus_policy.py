"""Explicit publication validity and evidence-limited delivery statistics.

No date is inferred from notice text. A publication's policy is immutable for
each official version, just like its body and originals. Callers must authorize
the owned notice or manageable publication before exposing these projections.
"""
from datetime import datetime, timezone
import time

from pydantic import Field, field_validator

from .models import Strict, TaskData


SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_publication_policy(
 publication_id TEXT NOT NULL, version INTEGER NOT NULL,
 valid_until TEXT, reference_only INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(publication_id,version),
 FOREIGN KEY(publication_id,version)
 REFERENCES campus_publication_versions(publication_id,version) ON DELETE CASCADE);
"""


class PublicationPolicy(Strict):
    valid_until: str | None = Field(default=None, max_length=50)
    reference_only: bool = False

    @field_validator('valid_until')
    @classmethod
    def validity(cls, value):
        result = TaskData.valid_datetime(value)
        if result is not None:
            parsed = datetime.fromisoformat(result)
            if not 2000 <= parsed.year <= 2100:
                raise ValueError('有效期须在2000至2100年之间')
            return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')
        return None


def policy_changes(payload):
    return payload.model_dump(include={'valid_until','reference_only'} & payload.model_fields_set)


def stored_policy(conn, pid, version):
    row = conn.execute('SELECT valid_until,reference_only FROM campus_publication_policy '
                       'WHERE publication_id=? AND version=?', (pid, version)).fetchone()
    return {'valid_until':row['valid_until'] if row else None,
            'reference_only':bool(row['reference_only']) if row else False}


def save_policy(conn, pid, version, changes=None):
    values = {**stored_policy(conn,pid,version-1), **(changes or {})}
    conn.execute('INSERT INTO campus_publication_policy VALUES(?,?,?,?)',
                 (pid,version,values['valid_until'],int(values['reference_only'])))


def publication_policy(conn, pid, version, now=None):
    return policy_projection(stored_policy(conn,pid,version),now)


def policy_projection(values, now=None):
    """Re-evaluate an immutable version's explicit policy without a DB read."""
    moment = int(time.time()) if now is None else now
    expired = bool(values['valid_until'] and datetime.fromisoformat(values['valid_until']).timestamp() <= moment)
    return {**values, 'expired':expired,
            'external_notifications':'suppressed' if values['reference_only'] or expired else 'eligible',
            'label':'仅作历史参考' if values['reference_only'] else '已超过发布方标注的有效期' if expired
                    else '有效期内' if values['valid_until'] else '未设置有效期'}


def notice_publication_context(conn, notice_id, now=None):
    """Describe the exact received version; this function grants no access."""
    row = conn.execute('SELECT publication_id,delivered_version FROM campus_deliveries '
                       'WHERE notice_id=? AND delivered_version>0', (notice_id,)).fetchone()
    if row is None:return None
    return {'publication_id':row['publication_id'],'version':row['delivered_version'],
            **publication_policy(conn,row['publication_id'],row['delivered_version'],now)}


def suppress_external_notice(conn, notice_id, now=None):
    context = notice_publication_context(conn,notice_id,now)
    return bool(context and context['external_notifications']=='suppressed')


def delivery_evidence(conn, pid):
    """Count only provider ledger entries explicitly linked to receipt IDs.

    Personal-task completion, workflows, mail addresses and device identifiers
    are deliberately absent. A multi-notice digest counts once for each notice
    it can prove it included; two devices never become two distinct recipients.
    Older payloads without receipt references cannot prove this association.
    """
    channels = {}
    for channel,table in (('push','push_outbox'),('email','mail_outbox')):
        rows = conn.execute(f"""SELECT o.state,COUNT(DISTINCT o.id) AS events,
            COUNT(DISTINCT o.user_id) AS recipients
            FROM {table} o JOIN campus_deliveries d ON d.user_id=o.user_id
            WHERE d.publication_id=? AND d.notice_id IS NOT NULL AND json_valid(o.payload)
              AND COALESCE(o.finished_at,o.created_at)>=?
              AND EXISTS(SELECT 1 FROM json_each(CASE WHEN json_valid(o.payload) THEN o.payload ELSE '{{}}' END,'$.receipt_refs') ref
                WHERE ref.type='text' AND substr(ref.value,1,length(d.notice_id)+1)=d.notice_id||':')
            GROUP BY o.state""", (pid,int(time.time())-30*86400)).fetchall()
        counts = {row['state']:{'events':row['events'],'recipients':row['recipients']} for row in rows}
        channels[channel] = {'states':counts,
            'accepted_events':counts.get('accepted',{}).get('events',0),
            'accepted_recipients':counts.get('accepted',{}).get('recipients',0)}
    return {'channels':channels,'evidence_window_days':30,
            'opened':{'count':None,'state':'unknown','note':'当前没有能够证明本人打开的发布级记录'},
            'explicit_receipt':{'count':None,'state':'unknown','note':'当前未采集发布级显式确认回执'},
            'note':'仅统计现存30天渠道台账中明确包含此通知的收件事件；供应商接受不表示设备展示、本人打开或办理完成。0表示没有现存证据，不证明从未发送。'}
