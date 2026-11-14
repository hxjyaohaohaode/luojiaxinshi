"""Daily private SQLite snapshots; deletion retention is enforced whenever running."""
from datetime import datetime
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time


def daily_backup(db, settings):
    folder=(settings.data_dir/'backups').resolve()
    folder.mkdir(parents=True,exist_ok=True)
    days=max(1,int(os.getenv('BACKUP_RETENTION_DAYS','7')))
    for item in folder.glob('auto-*.sqlite3'):
        if item.resolve().parent==folder and item.stat().st_mtime<time.time()-days*86400:
            item.unlink()
    with db.connect() as conn:
        if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            return
    target=folder/('auto-'+datetime.now().strftime('%Y-%m-%d')+'.sqlite3')
    if target.exists():
        return
    temporary=target.with_suffix('.tmp')
    if temporary.exists():
        temporary.unlink()
    db.backup(temporary)
    temporary.replace(target)


def restore_database(source:Path,destination:Path):
    """Validate a private backup and publish it once, without replacing existing data."""
    if destination.exists() or destination.is_symlink():
        raise ValueError('恢复目标已存在，拒绝覆盖；请指定新的空目录')
    expected={'meta','users','invites','sessions','limits','edit_caches','notices',
              'sources','confirmations','tasks','audit','ai_calls'}
    temporary=None
    try:
        with closing(sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro',uri=True)) as original:
            if original.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('备份完整性检查失败')
            tables={row[0] for row in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not expected.issubset(tables):
                raise ValueError('备份缺少必要的数据表，不是完整的工作台备份')
            version=original.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version is None or version[0] not in {'1','2','3','4','5'}:
                raise ValueError('备份版本不兼容，未恢复任何数据')
            if version[0] in {'2','3','4'} and not {'account_recovery','conversations','conversation_sources','conversation_messages','conversation_promotions','source_catalog'}.issubset(tables):
                raise ValueError('备份缺少工作空间数据表')
            if version[0] in {'3','4'} and not {'external_bindings','binding_codes','integration_receipts'}.issubset(tables):
                raise ValueError('备份缺少渠道接入记录表')
            if version[0]=='4' and 'arrangements' not in tables:
                raise ValueError('备份缺少个人安排表')
            workflow_version = original.execute("SELECT value FROM meta WHERE key='workflow_schema_version'").fetchone()
            intake_version = original.execute("SELECT value FROM meta WHERE key='notice_intake_schema_version'").fetchone()
            from .notice_intake import TABLES as INTAKE_TABLES
            if intake_version and (intake_version[0] != '1' or not INTAKE_TABLES.issubset(tables)):
                raise ValueError('备份缺少通知接入数据或版本不兼容')
            from .notice_ingest import TABLES as INGEST_TABLES
            from .task_materials import TABLES as MATERIAL_TABLES
            from .source_sync import TABLES as SYNC_TABLES
            from .integrations import GROUP_TABLES
            from .publisher_sync import TABLES as PUBLISHER_TABLES
            from .push_delivery import TABLES as PUSH_TABLES
            from .notice_automation import TABLES as AUTOMATION_TABLES
            from .group_delivery import TABLES as GROUP_DELIVERY_TABLES
            from .notice_matters import TABLES as MATTER_TABLES
            from .campus import TABLES as CAMPUS_TABLES
            from .verification import TABLES as VERIFICATION_TABLES
            from .mail_delivery import TABLES as MAIL_TABLES
            from .delivery_policy import TABLES as DELIVERY_POLICY_TABLES
            from .campus_imports import TABLES as IMPORT_TABLES
            from .message_interactions import TABLES as MESSAGE_INTERACTION_TABLES
            from .proactive_feedback import TABLES as FEEDBACK_TABLES
            from .campus import SPRINT_TABLES
            from .source_fetch import TABLES as FETCH_TABLES
            from .source_sync import OBSERVATION_TABLES
            from .notice_tracking import TABLES as TRACKING_TABLES
            from .listing import TABLES as LISTING_TABLES
            from .observability import TABLES as OBSERVABILITY_TABLES
            from .notification_coordination import TABLES as COORDINATION_TABLES
            for key, required in (('campus_sprint_schema_version',SPRINT_TABLES),
                                  ('source_fetch_schema_version',FETCH_TABLES),
                                  ('source_observation_schema_version',OBSERVATION_TABLES),
                                  ('notice_tracking_schema_version',TRACKING_TABLES),
                                  ('bounded_lists_version',LISTING_TABLES),
                                  ('observability_schema_version',OBSERVABILITY_TABLES),
                                  ('notification_coordination_schema_version',COORDINATION_TABLES)):
                marker=original.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
                if marker and (marker[0]!='1' or not required.issubset(tables)):
                    raise ValueError('备份扩展版本不兼容或必要记录缺失：'+key)
            import_version=original.execute("SELECT value FROM meta WHERE key='campus_import_schema_version'").fetchone()
            if import_version and (import_version[0]!='1' or not IMPORT_TABLES.issubset(tables)):
                raise ValueError('备份缺少校园导入记录或版本不兼容')
            for meta_key,required in (('message_interaction_schema_version',MESSAGE_INTERACTION_TABLES),('proactive_feedback_schema_version',FEEDBACK_TABLES),('notice_matters_schema_version',MATTER_TABLES),('notice_ingest_schema_version',INGEST_TABLES),('task_material_schema_version',MATERIAL_TABLES),
                    ('source_sync_schema_version',SYNC_TABLES),('qq_group_schema_version',GROUP_TABLES),
                    ('publisher_sync_schema_version',PUBLISHER_TABLES),('push_delivery_schema_version',PUSH_TABLES),
                    ('notice_automation_schema_version',AUTOMATION_TABLES),('qq_group_delivery_schema_version',GROUP_DELIVERY_TABLES),('campus_schema_version',CAMPUS_TABLES),('verification_schema_version',VERIFICATION_TABLES),('mail_delivery_schema_version',MAIL_TABLES),('delivery_policy_schema_version',DELIVERY_POLICY_TABLES)):
                current=original.execute('SELECT value FROM meta WHERE key=?',(meta_key,)).fetchone()
                if current and (current[0]!='1' or not required.issubset(tables)):
                    raise ValueError('备份缺少收件、办理材料或提醒数据，或版本不兼容：'+meta_key)
            if workflow_version and (workflow_version[0] not in {'1','2','3'} or not {'task_workflows','notice_changes','calendar_checks'}.issubset(tables)):
                raise ValueError('备份缺少办理工作流数据或版本不兼容')
            memory_version=original.execute("SELECT value FROM meta WHERE key='memory_schema_version'").fetchone()
            if memory_version and (memory_version[0] not in {'1','2'} or not {'memory_projects','personal_memories','conversation_context'}.issubset(tables)
                or memory_version[0]=='2' and 'memory_policies' not in tables):
                raise ValueError('备份缺少个人记忆数据或版本不兼容')
            execution_version=original.execute("SELECT value FROM meta WHERE key='execution_schema_version'").fetchone()
            engine_version=original.execute("SELECT value FROM meta WHERE key='memory_engine_schema_version'").fetchone()
            from .memory_store import REQUIRED_TABLES,V1_TABLES,V2_TABLES,V3_TABLES,V4_TABLES,V5_TABLES
            if engine_version and (engine_version[0] not in {'1','2','3','4','5','6'} or not ({'1':V1_TABLES,'2':V2_TABLES,'3':V3_TABLES,'4':V4_TABLES,'5':V5_TABLES,'6':REQUIRED_TABLES}[engine_version[0]]).issubset(tables)):
                raise ValueError('备份缺少记忆引擎数据或版本不兼容')
            if execution_version and (execution_version[0] not in {'1','2'} or not {'executions','execution_owners'}.issubset(tables) or execution_version[0]=='2' and 'execution_metrics' not in tables):
                raise ValueError('备份缺少执行记录或版本不兼容')
            review_version=original.execute("SELECT value FROM meta WHERE key='action_review_schema_version'").fetchone()
            if review_version and (review_version[0]!='1' or 'task_reviews' not in tables):
                raise ValueError('备份缺少办理复核记录或版本不兼容')
            receipt_version=original.execute("SELECT value FROM meta WHERE key='arrangement_receipt_schema_version'").fetchone()
            if receipt_version and (receipt_version[0]!='1' or 'arrangement_receipts' not in tables):
                raise ValueError('备份缺少安排提交记录或版本不兼容')
            agent_version=original.execute("SELECT value FROM meta WHERE key='agent_schema_version'").fetchone()
            from .agent_runtime.store import TABLES as AGENT_TABLES
            if agent_version and (agent_version[0]!='1' or not AGENT_TABLES.issubset(tables)):
                raise ValueError('备份缺少智能任务记录或版本不兼容')
            if original.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('备份的数据关联不完整，未恢复任何数据')
            destination.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.campus-restore-',suffix='.tmp',dir=destination.parent)
            os.close(fd)
            temporary=Path(name)
            with closing(sqlite3.connect(temporary)) as target:
                target.row_factory=sqlite3.Row
                original.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
                target.execute('PRAGMA secure_delete=ON')
                target.execute('DELETE FROM sessions')
                target.execute('DELETE FROM invites')
                target.execute("DELETE FROM meta WHERE key='deployment_instance_id'")
                if 'notification_reconcile_state' in tables:target.execute('DELETE FROM notification_reconcile_state')
                if 'auth_challenges' in tables:target.execute('DELETE FROM auth_challenges')
                # Restore must not resurrect ownership of an old/reassigned contact.
                if 'verified_contacts' in tables:target.execute('DELETE FROM verified_contacts')
                if 'mail_outbox' in tables:target.execute('DELETE FROM mail_outbox')
                if 'mail_preferences' in tables:target.execute('UPDATE mail_preferences SET enabled=0')
                if 'binding_codes' in tables:
                    target.execute('DELETE FROM binding_codes')
                    target.execute('DELETE FROM external_bindings')
                for table in ('reply_shares','conversation_ai_consents','notice_link_previews'):
                    if table in tables:target.execute('DELETE FROM '+table)
                for table in ('qq_group_delivery_info','qq_group_attachment_files','qq_group_attachment_batches',
                              'qq_group_deliveries','qq_group_intake_settings','qq_group_subscriptions',
                              'qq_authorized_groups','qq_group_codes','push_outbox','push_devices'):
                    if table in tables:target.execute('DELETE FROM '+table)
                # Old snapshots must not silently revive revoked college privileges.
                for table in ('campus_counselor_scopes','campus_members'):
                    if table in tables:target.execute('DELETE FROM '+table)
                for table in ('campus_audience_reviews','campus_roster_previews','campus_dispatch_authority'):
                    if table in tables:target.execute('DELETE FROM '+table)
                if 'campus_deliveries' in tables:
                    target.execute("UPDATE campus_deliveries SET state='failed',error='恢复后请重新授权并核对受众' WHERE state IN ('pending','failed')")
                for table in ('source_subscriptions','publisher_subscriptions'):
                    if table in tables:
                        target.execute("UPDATE "+table+" SET enabled=0,running_until=0,error='从备份恢复，请重新确认来源授权'")
                if 'notice_automation_settings' in tables:
                    target.execute('UPDATE notice_automation_settings SET enabled=0,consented_at=NULL')
                    target.execute("UPDATE notice_automation_jobs SET state='cancelled',lease_until=NULL,error='从备份恢复，请重新确认自动整理' WHERE state IN ('queued','running')")
                target.execute("UPDATE notices SET status='failed',processing_token=NULL,error='服务恢复后请重新生成草稿' WHERE status='processing'")
                if 'conversations' in tables:
                    target.execute('UPDATE conversations SET processing_token=NULL,processing_at=NULL')
                    target.execute("UPDATE conversation_messages SET status='failed',error='服务恢复后请重试本条消息' WHERE status='processing'")
                if 'executions' in tables:
                    target.execute("UPDATE executions SET status='interrupted',stop_reason='backup_restored',finished_at=?,updated_at=? WHERE status='running'",(int(time.time()),int(time.time())))
                    target.execute('UPDATE execution_owners SET expires_at=0')
                if 'agent_turns' in tables:
                    from .agent_runtime.store import finish as finish_agent
                    for run in target.execute("SELECT * FROM agent_turns WHERE status IN ('running','waiting_approval')").fetchall():
                        finish_agent(target,dict(run),'interrupted',error='从备份恢复后请核对记录并手动重试')
                target.commit()
                if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or target.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('恢复结果未通过完整性校验，未启用该文件')
        # Same-directory hard-link creation is atomic and fails if anything already
        # occupies the destination. Unlike replace(), it cannot overwrite a new file.
        os.link(temporary,destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
