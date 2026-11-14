"""账号层面的个人信息权利：隐私政策同意记录、政策信息与注销账号。

注销会删除用户行；本人业务数据通过外键 ON DELETE CASCADE 一并删除（包括通知、附件、
对话、待办、日程、记忆及其全文索引）。不受外键约束的残留（限流键、Agent 工作目录）
在同一次注销中单独清理。自动备份按 BACKUP_RETENTION_DAYS 轮换，隐私政策如实说明。
注销前为仍有权限的协作对方保留最小脱敏回执，原文件分享随原协作一并关闭。
"""
import os
import shutil
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .security import DUMMY_PASSWORD, rate_limit, verify_password

# 版本用于展示内容与记录同意时的原文版本；更新不会触发登录后的重复确认。
POLICY_VERSION = '2026-11-14'
CONFIRM_PHRASE = '注销账号'

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_consents(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 version TEXT NOT NULL, accepted_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,version));
"""


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=256)
    confirm: str = Field(max_length=20)


def record_consent(conn, uid, now=None):
    conn.execute('INSERT OR IGNORE INTO account_consents VALUES(?,?,?)', (uid, POLICY_VERSION, int(now or time.time())))


def consent_state(conn, uid):
    row = conn.execute('SELECT accepted_at FROM account_consents WHERE user_id=? AND version=?', (uid, POLICY_VERSION)).fetchone()
    return {'version': POLICY_VERSION, 'accepted': row is not None, 'accepted_at': row['accepted_at'] if row else None}


def retention_days():
    try:
        return max(1, int(os.getenv('BACKUP_RETENTION_DAYS', '7')))
    except ValueError:
        return 7


def legal_information(settings):
    from .model_catalog import public_configuration
    ai = public_configuration(settings)
    return {
        'version': POLICY_VERSION,
        'operator_name': settings.operator_name,
        'operator_contact': settings.operator_contact,
        'model_provider': '小米 MiMo',
        'ai_configured': bool(ai.get('configured')),
        'backup_retention_days': retention_days(),
        'registration_mode': settings.registration_mode,
        'collaboration_retention':'注销会关闭原协作与文件分享，对方仅保留参与事项的必要动作、时间和自己填写的说明，已注销身份显示为已注销账号。',
    }


def deletion_impact(conn,uid):
    from .collaboration import IN_SCOPE
    affected=conn.execute(f'''SELECT
        sum(CASE WHEN c.recipient_id=? THEN 1 ELSE 0 END) AS student_receipts,
        sum(CASE WHEN c.sender_id=? AND {IN_SCOPE} THEN 1 ELSE 0 END) AS staff_receipts
        FROM collaboration_cases c WHERE c.sender_id=? OR c.recipient_id=?''',(uid,uid,uid,uid)).fetchone()
    counts={label:conn.execute('SELECT count(*) FROM '+table+' WHERE user_id=?',(uid,)).fetchone()[0]
            for label,table in [('notices','notices'),('tasks','tasks'),('conversations','conversations'),
                               ('arrangements','arrangements'),('publication_drafts','campus_drafts'),
                               ('publication_cancellations','campus_submission_cancellations')]}
    return {'deleted':counts,'retained_counterparty_receipts':int(affected['student_receipts'] or 0)+int(affected['staff_receipts'] or 0),
            'shared_file_access':'revoked','backup_retention_days':retention_days(),
            'retention_note':'本人通知、附件、对话、待办、日程、发布草稿和已停止的发布请求记录将删除。协作对方只保留参与事项的必要动作、时间和自己填写的说明；你的身份、私人说明和文件授权会移除。',
            'publication_note':'已向他人发布的学院公告及不可变原件仍属于对方收到的正式版本；发布者姓名改为已注销发布者，不再授予新访问权限。'}


def install(app, db, settings, user):
    with db.connect(write=True) as conn:
        conn.executescript(SCHEMA)

    @app.get('/api/legal')
    def legal():
        # 未登录也可阅读，注册前就能看到完整说明。
        return legal_information(settings)

    @app.post('/api/account/consent')
    def accept_policy(current=Depends(user)):
        with db.connect(write=True) as conn:
            record_consent(conn, current['id'])
            return consent_state(conn, current['id'])

    @app.get('/api/account/deletion-impact')
    def impact(current=Depends(user)):
        with db.connect() as conn:
            return deletion_impact(conn,current['id'])

    @app.post('/api/account/delete')
    def delete_account(payload: DeleteAccount, request: Request, current=Depends(user)):
        rate_limit(db, 'account-delete:' + current['id'], 5, 900)
        if payload.confirm.strip() != CONFIRM_PHRASE:
            raise HTTPException(422, f'请输入“{CONFIRM_PHRASE}”确认')
        with db.connect() as conn:
            record = conn.execute('SELECT password FROM users WHERE id=?', (current['id'],)).fetchone()
        if not verify_password(payload.password, record['password'] if record else DUMMY_PASSWORD):
            raise HTTPException(400, '密码不正确，账号没有注销')
        uid, username = current['id'], current['username']
        with db.connect(write=True) as conn:
            from .collaboration import preserve_counterparty_receipts
            from .campus_roster import forget_deleted_member
            retained=preserve_counterparty_receipts(conn,uid)
            forget_deleted_member(conn,uid)
            conn.execute("UPDATE campus_publications SET publisher_name='已注销发布者' WHERE publisher_id=?",(uid,))
            conn.execute('DELETE FROM users WHERE id=?', (uid,))
            # 限流键里含账号名，一并清除。
            conn.execute("DELETE FROM limits WHERE key LIKE ? OR key LIKE ?", ('%:' + username, '%:' + uid))
        projection_cache = getattr(app.state, 'workspace_projection_cache', None)
        if projection_cache is not None:projection_cache.forget(uid)
        workspace = (settings.data_dir / 'agent-workspaces' / uid).resolve()
        root = (settings.data_dir / 'agent-workspaces').resolve()
        if workspace.parent == root and workspace.is_dir():
            shutil.rmtree(workspace, ignore_errors=True)
        response = JSONResponse({'ok': True, 'backup_retention_days': retention_days(),
                                 'retained_counterparty_receipts':retained,'shared_file_access':'revoked'})
        response.delete_cookie('campus_session', path='/', secure=settings.production, samesite='strict')
        return response
