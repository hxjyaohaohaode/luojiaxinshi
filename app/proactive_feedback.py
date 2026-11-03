"""Reversible owner corrections to presentation, never edits to school facts."""
from typing import Literal
from pydantic import Field
from .models import Strict

TABLES={'notice_recommendation_feedback'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS notice_recommendation_feedback(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 mode TEXT NOT NULL CHECK(mode IN ('auto','include','exclude')),
 note TEXT NOT NULL, notice_version INTEGER NOT NULL,
 version INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS recommendation_feedback_owner ON notice_recommendation_feedback(user_id);
INSERT OR IGNORE INTO meta VALUES('proactive_feedback_schema_version','1');
"""


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='proactive_feedback_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('个性化纠正记录版本不兼容或缺少数据表')
    conn.executescript(SCHEMA)


class Feedback(Strict):
    notice_version:int=Field(ge=1,strict=True)
    version:int=Field(ge=0,strict=True)
    mode:Literal['auto','include','exclude']
    note:str=Field(default='',max_length=1000)


def saved(conn,uid,nid):
    row=conn.execute('SELECT mode,note,notice_version,version,updated_at FROM notice_recommendation_feedback WHERE notice_id=? AND user_id=?',(nid,uid)).fetchone()
    return dict(row) if row else {'mode':'auto','version':0,'note':'','notice_version':None,'updated_at':None}


def apply(decision,feedback):
    result={**decision,'reasons':list(decision['reasons']),'feedback':feedback}
    if feedback['mode']=='include':
        result.update(recommended=True,delivery='near_term')
        result['reasons'].append('你已选择保留到相关通知；原文时效与资格判断仍保留，可随时恢复自动判断')
    elif feedback['mode']=='exclude':
        result.update(recommended=False,delivery='silent')
        result['reasons'].append('你已选择移出相关通知；完整记录仍可搜索，已有个人待办另行管理')
    return result
