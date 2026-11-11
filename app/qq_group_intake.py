"""Per-member QQ group routing, evidence, and receipt history."""
import json
import re
import time
import unicodedata
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from .db import dumps
from .models import Strict

RULE_VERSION = 'qq-group-routing-v1'
Category = Literal['notice', 'discussion', 'review']
Filter = Literal['all', 'notice', 'discussion', 'review', 'unclassified']
TABLES = {'qq_group_intake_settings', 'qq_group_delivery_info', 'qq_group_receipt_routes'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS qq_group_intake_settings(
 user_id TEXT NOT NULL,app_id TEXT NOT NULL,group_id TEXT NOT NULL,
 name TEXT NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('notices','all')),
 keywords TEXT NOT NULL,version INTEGER NOT NULL,
 PRIMARY KEY(user_id,app_id,group_id),
 FOREIGN KEY(user_id,app_id,group_id) REFERENCES qq_group_subscriptions(user_id,app_id,group_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS qq_group_delivery_info(
 delivery_id TEXT PRIMARY KEY REFERENCES qq_group_deliveries(id) ON DELETE CASCADE,
 category TEXT NOT NULL CHECK(category IN ('notice','discussion','review')),
 reasons TEXT NOT NULL,rule_version TEXT NOT NULL,quiet INTEGER NOT NULL,
 source_label TEXT NOT NULL,result TEXT NOT NULL DEFAULT '',repeats INTEGER NOT NULL DEFAULT 0,
 media_id TEXT REFERENCES qq_group_attachment_batches(id) ON DELETE SET NULL,
 media_state TEXT NOT NULL DEFAULT 'none',media_total INTEGER NOT NULL DEFAULT 0,
 media_saved INTEGER NOT NULL DEFAULT 0,media_note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS qq_group_delivery_media ON qq_group_delivery_info(media_id);
CREATE INDEX IF NOT EXISTS qq_group_deliveries_history
 ON qq_group_deliveries(user_id,app_id,group_id,created_at DESC);
CREATE TABLE IF NOT EXISTS qq_group_receipt_routes(
 receipt_id TEXT PRIMARY KEY REFERENCES notice_ingest_receipts(id) ON DELETE CASCADE,
 category TEXT NOT NULL,quiet INTEGER NOT NULL,rule_version TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES('qq_group_intake_schema_version','1');
"""

REASONS = {
    'change': '含更正、改期或撤回表述，需核对原文',
    'material': '消息含附件、卡片或需要补齐的材料',
    'deadline': '含日期、时刻或相对期限',
    'action': '含办理、提交或活动要求',
    'announcement': '含通知或公示表述',
    'keyword': '命中你为这个群设置的关注词',
    'link': '含链接，需核对出处和正文',
    'reaction': '整条消息只有常见应答、感谢或表情',
    'uncertain': '现有文字不足以判断是否为通知',
}
CHANGE = re.compile(r'更正|纠正|改期|变更|调整|顺延|延期|推迟|提前|延长|撤回|取消|恢复办理|作废|另行通知|以.{0,18}为准|不再.{0,8}(?:提交|报名|办理)')
TIME = re.compile(r'截止|截至|逾期|今(?:天|晚|早)|明(?:天|晚|早|日)|后天|(?:本|下|这)(?:周|星期)|周[一二三四五六日天]|'
                  r'\d{1,2}月\s*\d{1,2}[日号]?|(?:20\d{2}[-/.])?\d{1,2}[-/.]\d{1,2}|'
                  r'\d{1,2}:\d{2}|\d{1,2}(?:点|时)(?:半|钟|\d{1,2}分)?')
ACTION = re.compile(r'报名|申报|申领|申请|提交|上报|报送|补交|补件|缴费|签到|签字|选课|补考|考试|填报|'
                    r'填写|领取|携带|务必|请.{0,12}(?:到|带|看|交|核对)|停课|调课|集合|答辩|预约')
ANNOUNCEMENT = re.compile(r'通知|公示|公告|通报|安排|名单|征集|温馨提示|转发')
LINK = re.compile(r'https?://|www\.|(?:[a-z0-9-]+\.)+(?:edu\.cn|gov\.cn|qq\.com)\b', re.I)
REACTION = re.compile(r'收到(?:了|啦)?|好的?(?:呀|哒|啦)?|好嘞|好滴|谢谢(?:老师|大家|同学)?(?:啦|了)?|'
                      r'感谢(?:老师|大家)?|辛苦(?:啦|了)?|明白(?:了)?|了解(?:了)?|知道(?:了)?|'
                      r'可以的|嗯{1,4}|哦{1,3}|哈{2,12}|呵{2,8}|笑死(?:了)?|ok|okay|thx|thanks', re.I)
REACTION_PARTS = re.compile(r'[\s,，。.!！?？~～、;；]+')
EMOJI_WORDS = re.compile(r'\[(?:表情|点赞|抱拳|握手|鼓掌|比心|收到)\]')
REACTION_EMOJI = re.compile(r'[👍👎🙏👏🙌🤝👌✌🤗🤭😂🤣😄😆😊🙂😉😁😀😅😃😆😌🙃😎😋😹😭🥲🥹🥰😍😘❤💕💖💗💓💞💯✅][\ufe0f\U0001f3fb-\U0001f3ff]*')


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='qq_group_intake_schema_version'").fetchone()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('QQ 群分流记录版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold().strip()


def discussion_only(text):
    if not text or len(text) > 44:
        return False
    # Restrict automatic folding to complete reaction messages. A timestamp,
    # mention, substantive sentence or placeholder of unknown meaning stays visible.
    remaining = REACTION_EMOJI.sub(' ', EMOJI_WORDS.sub(' ', text))
    tokens = [part for part in REACTION_PARTS.split(remaining) if part]
    return all(REACTION.fullmatch(part) for part in tokens) and (bool(tokens) or remaining != text)


def classify(text, *, material=False, keywords=()):
    text = normalized(text)
    signals = [
        code for code, pattern in (('change', CHANGE), ('deadline', TIME), ('action', ACTION),
                                   ('announcement', ANNOUNCEMENT), ('link', LINK))
        if pattern.search(text)
    ]
    if material:
        signals.insert(0, 'material')
    if any(normalized(word) in text for word in keywords if normalized(word)):
        signals.append('keyword')
    if material or 'change' in signals or 'link' in signals and not {'action', 'announcement'}.intersection(signals):
        return 'review', signals
    if signals:
        return 'notice', signals
    if discussion_only(text):
        return 'discussion', ['reaction']
    return 'review', ['uncertain']


class GroupIntakeSettings(Strict):
    version: int = Field(ge=0, strict=True)
    name: str = Field(default='', max_length=60)
    mode: Literal['notices', 'all'] = 'notices'
    keywords: list[str] = Field(default_factory=list, max_length=12)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        return ' '.join(value.split())

    @field_validator('keywords')
    @classmethod
    def clean_keywords(cls, values):
        words = {}
        for value in values:
            word = ' '.join(value.split())
            if not word or len(word) > 30:
                raise ValueError('每个关注词须为 1 至 30 字')
            words.setdefault(normalized(word), word)
        return list(words.values())


def subscription(conn, uid, app_id, group_id):
    row = conn.execute('''SELECT s.*,COALESCE(p.name,'') AS name,COALESCE(p.mode,'notices') AS mode,
        COALESCE(p.keywords,'[]') AS keywords,COALESCE(p.version,0) AS version
        FROM qq_group_subscriptions s LEFT JOIN qq_group_intake_settings p USING(user_id,app_id,group_id)
        WHERE s.user_id=? AND s.app_id=? AND s.group_id=?''', (uid, app_id, group_id)).fetchone()
    if row is None:
        raise HTTPException(404, '群接收记录不存在或本人已停止接收')
    return row


def preferences(row):
    return {'name': row['name'], 'mode': row['mode'], 'keywords': json.loads(row['keywords']),
            'version': row['version']}


def save_settings(conn, uid, app_id, group_id, value):
    current = subscription(conn, uid, app_id, group_id)
    if current['version'] != value.version:
        raise HTTPException(409, '群设置已有更新，请重新打开收件与规则后核对')
    conn.execute('''INSERT INTO qq_group_intake_settings VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(user_id,app_id,group_id) DO UPDATE SET name=excluded.name,mode=excluded.mode,
        keywords=excluded.keywords,version=excluded.version''',
        (uid, app_id, group_id, value.name, value.mode, dumps(value.keywords), value.version+1))
    return preferences(subscription(conn, uid, app_id, group_id))


def quiet_notices(conn, uid, nid=None):
    """A current receipt from any other channel or an explicit include wins."""
    scope = 'AND r.notice_id=?' if nid is not None else ''
    args = (uid,) if nid is None else (uid, nid)
    return {row[0] for row in conn.execute(f'''SELECT r.notice_id
        FROM notice_ingest_receipts r
        JOIN notices n ON n.id=r.notice_id AND n.user_id=r.user_id AND n.fingerprint=r.fingerprint
        LEFT JOIN qq_group_receipt_routes q ON q.receipt_id=r.id
        WHERE r.user_id=? {scope} AND n.status!='confirmed'
        AND NOT EXISTS(SELECT 1 FROM tasks t WHERE t.notice_id=n.id AND t.status!='cancelled')
        AND NOT EXISTS(SELECT 1 FROM notice_ingest_updates u WHERE u.notice_id=n.id AND u.state='pending')
        AND NOT EXISTS(SELECT 1 FROM notice_recommendation_feedback f
            WHERE f.notice_id=n.id AND f.user_id=n.user_id AND f.mode='include')
        GROUP BY r.notice_id HAVING COUNT(*)=SUM(CASE WHEN q.quiet=1 THEN 1 ELSE 0 END)''', args)}


def quiet_assessment(decision):
    return {**decision,'recommended':False,'delivery':'silent',
            'reasons':[*decision['reasons'],'此消息按 QQ 群设置归入普通讨论，可在全部记录查看。']}


def record_receipt(conn, receipt_id, info):
    if receipt_id and info:
        conn.execute('''INSERT OR IGNORE INTO qq_group_receipt_routes(receipt_id,category,quiet,rule_version)
            VALUES(?,?,?,?)''', (receipt_id, info['category'], info['quiet'], info['rule_version']))


def history(conn, uid, app_id, group_id, *, before=None, category='all', limit=25, now=None):
    current = subscription(conn, uid, app_id, group_id)
    base = (uid, app_id, group_id)
    filter_sql = '' if category == 'all' else "AND COALESCE(i.category,'unclassified')=?"
    cursor_sql = '' if before is None else 'AND d.rowid<?'
    records = conn.execute(f'''SELECT d.rowid AS cursor,d.id,d.title,d.state,d.created_at,d.finished_at,
        d.error,n.id AS notice_id,i.category,i.reasons,i.rule_version,i.quiet,i.result,i.repeats,
        CASE WHEN i.media_state='waiting' AND (b.id IS NULL OR b.state='ready') THEN 'ready'
             ELSE i.media_state END AS media_state,i.media_total,i.media_saved,i.media_note,
        (SELECT j.state FROM notice_automation_jobs j WHERE j.notice_id=n.id AND j.user_id=d.user_id
          AND (j.input_version=n.version OR j.result_version=n.version)
          ORDER BY j.created_at DESC,j.rowid DESC LIMIT 1) AS automation_state
        FROM qq_group_deliveries d LEFT JOIN qq_group_delivery_info i ON i.delivery_id=d.id
        LEFT JOIN qq_group_attachment_batches b ON b.id=i.media_id
        LEFT JOIN notices n ON n.id=d.notice_id AND n.user_id=d.user_id
        WHERE d.user_id=? AND d.app_id=? AND d.group_id=? {filter_sql} {cursor_sql}
        ORDER BY d.rowid DESC LIMIT ?''',
        (*base, *((category,) if filter_sql else ()), *((before,) if cursor_sql else ()), limit+1)).fetchall()
    items = []
    for row in records[:limit]:
        item = {key: row[key] for key in ('id','title','state','created_at','finished_at','error','notice_id',
                'rule_version','result','media_state','media_total','media_saved','media_note','automation_state')}
        item.update(category=row['category'] or 'unclassified', quiet=bool(row['quiet']), repeats=row['repeats'] or 0,
                    reasons=[REASONS[code] for code in json.loads(row['reasons'] or '[]') if code in REASONS])
        items.append(item)
    since = (int(time.time()) if now is None else now)-7*86400
    counts = {'notice': 0, 'discussion': 0, 'review': 0, 'unclassified': 0, 'pending': 0,
              'failed': 0, 'delivered': 0, 'superseded': 0, 'repeats': 0, 'merged': 0}
    for row in conn.execute('''SELECT COALESCE(i.category,'unclassified') AS category,d.state,
        count(*) AS total,COALESCE(sum(i.repeats),0) AS repeats,
        sum(CASE WHEN i.result='merged' THEN 1 ELSE 0 END) AS merged
        FROM qq_group_deliveries d LEFT JOIN qq_group_delivery_info i ON i.delivery_id=d.id
        WHERE d.user_id=? AND d.app_id=? AND d.group_id=? AND d.created_at>=?
        GROUP BY category,d.state''', (*base, since)):
        counts[row['category']] += row['total']
        counts[row['state']] += row['total']
        counts['repeats'] += row['repeats']
        counts['merged'] += row['merged']
    return {'settings': preferences(current), 'counts': counts, 'items': items,
            'next_before': records[limit-1]['cursor'] if len(records)>limit else None}
