"""Deployment-wide campus capacity; independent from request/security bounds."""
from dataclasses import asdict, dataclass, fields
import json

from fastapi import Depends, HTTPException


@dataclass(frozen=True)
class UsageLimits:
    notices: int = 10000
    conversations: int = 2000
    sources: int = 1000
    storage_bytes: int = 10 * 1024**3
    materials_per_task: int = 200
    versions_per_material: int = 100
    submissions_per_task: int = 500
    registered_users: int = 200000
    memory_projects: int = 1000
    arrangements: int = 20000
    tasks: int = 100000
    agent_threads: int = 2000
    automation_daily_default: int = 200
    automation_daily_max: int = 1000

    def __post_init__(self):
        for key, value in asdict(self).items():
            if type(value) is not int or value < 1 or value > (1024**5 if key == 'storage_bytes' else 1000000):
                raise ValueError('USAGE_LIMITS_JSON 的 '+key+' 必须是范围内的正整数')
        if self.automation_daily_default > self.automation_daily_max:
            raise ValueError('自动整理默认额度不能高于可设置的最大额度')

    @classmethod
    def parse(cls, raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) - {f.name for f in fields(cls)}:
            raise ValueError('USAGE_LIMITS_JSON 包含未知配置项或不是 JSON 对象')
        return cls(**value)


DEFAULTS = UsageLimits()


def limits_for(conn):
    return getattr(conn, 'usage_limits', DEFAULTS)


def check_count(conn, uid, table, field, label, extra=1):
    # Identifiers come only from this fixed mapping, never from request data.
    allowed = {'notices':'notices', 'conversations':'conversations', 'source_catalog':'sources',
               'memory_projects':'memory_projects', 'arrangements':'arrangements',
               'tasks':'tasks', 'agent_threads':'agent_threads'}
    if allowed.get(table) != field:
        raise ValueError('Unknown account capacity')
    if type(extra) is not int or extra < 0:raise ValueError('Capacity increment must be nonnegative')
    if not extra:return
    limit = getattr(limits_for(conn), field)
    count = conn.execute('SELECT COUNT(*) FROM '+table+' WHERE user_id=?', (uid,)).fetchone()[0]
    if count + extra > limit:
        raise HTTPException(413, f'{label}将超过当前账号容量（{limit:,}），可导出并清理旧内容，或由管理员调整容量')


def check_storage(conn, uid, extra=0):
    from .notice_ingest import personal_storage_bytes
    if type(extra) is not int or extra < 0:raise ValueError('Storage increment must be nonnegative')
    if not extra:return
    limit = limits_for(conn).storage_bytes
    if personal_storage_bytes(conn, uid) + extra > limit:
        raise HTTPException(413, f'账号原件与本人材料将超过 {limit / 1024**3:g} GB 容量，可清理旧文件或由管理员调整容量')


def install(app, db, settings, user):
    @app.get('/api/account/usage')
    def usage(current=Depends(user)):
        from .notice_ingest import personal_storage_bytes
        with db.connect() as conn:
            uid = current['id']
            used = {field:conn.execute('SELECT COUNT(*) FROM '+table+' WHERE user_id=?', (uid,)).fetchone()[0]
                    for field, table in [('notices','notices'), ('conversations','conversations'),
                                         ('sources','source_catalog'), ('memory_projects','memory_projects'),
                                         ('arrangements','arrangements'), ('tasks','tasks')]}
            used['storage_bytes'] = personal_storage_bytes(conn, uid)
            return {'used':used, 'limits':{**asdict(limits_for(conn)), 'ai_daily':settings.ai_daily_limit}}
