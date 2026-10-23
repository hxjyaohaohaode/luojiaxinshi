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
                if 'binding_codes' in tables:
                    target.execute('DELETE FROM binding_codes')
                    target.execute('DELETE FROM external_bindings')
                for table in ('reply_shares','conversation_ai_consents','notice_link_previews'):
                    if table in tables:target.execute('DELETE FROM '+table)
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
