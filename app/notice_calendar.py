"""Project formal corrections onto the owner's existing tasks and calendar."""
from collections import Counter
import json
import re
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException

from .ai import normalized
from .db import audit, dumps
from .deadline_evidence import analyze
from .workflow import ChangeDecision, ChangeProposal, ChangeTarget

Mode = Literal['off', 'review', 'verified_auto', 'allow_sync']
TABLES = {'notice_calendar_policy', 'notice_calendar_receipts'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_calendar_policy(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, mode TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notice_calendar_receipts(
 update_id TEXT PRIMARY KEY REFERENCES notice_ingest_updates(id) ON DELETE CASCADE,
 change_id TEXT REFERENCES notice_changes(id) ON DELETE SET NULL,
 outcome TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('notice_calendar_schema_version','1');
"""


def initialize(conn):
    marker = conn.execute("SELECT value FROM meta WHERE key='notice_calendar_schema_version'").fetchone()
    if marker:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if marker[0] != '1' or not TABLES.issubset(tables):
            raise ValueError('通知联动权限或回执表缺失')
    conn.executescript(SCHEMA)


def policy(conn, uid):
    row = conn.execute('SELECT mode FROM notice_calendar_policy WHERE user_id=?', (uid,)).fetchone()
    return row[0] if row else 'review'


def set_policy(conn, uid, mode):
    conn.execute('INSERT INTO notice_calendar_policy VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET mode=excluded.mode', (uid, mode))


def last_receipts(conn, uid):
    return [dict(row) for row in conn.execute('''SELECT c.outcome,c.reason,c.change_id,c.created_at,n.id AS notice_id,n.title
        FROM notice_calendar_receipts c JOIN notice_ingest_updates u ON u.id=c.update_id JOIN notices n ON n.id=u.notice_id
        WHERE n.user_id=? ORDER BY c.created_at DESC,c.rowid DESC LIMIT 12''',(uid,))]


def quoted(entries, index):
    result = []
    for item in entries or []:
        if not isinstance(item,dict):continue
        quote = item.get('quote','').strip()
        body = index.get((item.get('source_id'),item.get('locator')), '')
        if quote and normalized(quote) in normalized(body):
            result.append(quote)
    return list(dict.fromkeys(result))


def date_bound(day, clock, quotes, published):
    support = analyze(quotes, published)
    return day and support.supports_date(day,clock) and (not clock or support.supports_time(day,clock))


def correction(before, proposed, index, published):
    evidence = quoted(proposed.get('evidence'), index)
    patch, citations = {}, []
    dates = quoted(proposed.get('deadline_evidence'),index)
    day, clock = proposed.get('due_date'), proposed.get('due_time')
    if (day,clock)!=(before.get('due_date'),before.get('due_time')) and date_bound(day,clock,dates,published):
        # A missing time in a draft is insufficient to withdraw an existing one.
        if clock or not before.get('due_time'):
            patch.update(due_date=day, due_time=clock, deadline_text=' '.join(dates)[:500])
            citations.extend(dates)
    interval = proposed.get('scheduled')
    if interval:
        cited = quoted(interval.get('evidence'),index)
        fields = ('start_date','start_time','end_date','end_time','all_day','timezone')
        old = before.get('scheduled') or {}
        if (any(interval.get(k)!=old.get(k) for k in fields) and interval.get('start_date')
                and all(not interval.get(daykey) or date_bound(interval[daykey],interval.get(timekey),cited,published)
                        for daykey,timekey in [('start_date','start_time'),('end_date','end_time')])
                and all(not old.get(k) or interval.get(k) for k in ('start_time','end_date','end_time'))):
            patch['scheduled']={**interval,'confirmed':False,'evidence':[]}
            citations.extend(cited)
    location = proposed.get('location','').strip()
    if location and location != before.get('location') and any(location in line for line in evidence):
        patch['location']=location
        citations.extend(line for line in evidence if location in line)
    added=[m for m in proposed.get('materials',[]) if m not in before.get('materials',[]) and any(m in line for line in evidence)]
    if added and len(before.get('materials',[]))+len(added)<=30:
        patch['materials']=[*before.get('materials',[]),*added]
        citations.extend(line for line in evidence if any(m in line for m in added))
    return patch, list(dict.fromkeys(citations))


def supersede(conn, nid):
    rows=conn.execute("""SELECT c.update_id,c.change_id FROM notice_calendar_receipts c
        JOIN notice_ingest_updates u ON u.id=c.update_id JOIN notice_changes n ON n.id=c.change_id
        WHERE u.notice_id=? AND n.state='pending' AND c.outcome='proposed'""",(nid,)).fetchall()
    for row in rows:
        conn.execute("UPDATE notice_changes SET state='dismissed',version=version+1,updated_at=? WHERE id=?",(int(time.time()),row['change_id']))
        conn.execute("UPDATE notice_calendar_receipts SET outcome='superseded',reason='已有更新版本，请核对最新原文。' WHERE update_id=?",(row['update_id'],))


def personally_changed(conn, tid, patch):
    keys=set(patch)
    for row in conn.execute("SELECT before_json,after_json FROM audit WHERE task_id=? AND action IN ('update_task','confirm_revision','change_applied')",(tid,)):
        a,b=(json.loads(raw or '{}') for raw in row)
        if b.get('calendar_automatic'):continue
        a,b=a.get('data',a),b.get('data',b)
        if any(a.get(k)!=b.get(k) for k in keys):return True
    return False


def sync_revision(conn, uid, nid, propose, decide):
    notice=conn.execute('SELECT * FROM notices WHERE id=? AND user_id=?',(nid,uid)).fetchone()
    mode=policy(conn,uid)
    if not notice or mode=='off' or notice['draft_version']!=notice['version'] or not notice['draft']:return
    update=conn.execute('''SELECT u.id AS update_id,r.* FROM notice_ingest_updates u JOIN notice_ingest_receipts r ON r.id=u.receipt_id
        WHERE u.notice_id=? AND r.user_id=? AND r.fingerprint=? AND u.state='pending'
        ORDER BY u.created_at DESC,u.rowid DESC LIMIT 1''',(nid,uid,notice['fingerprint'])).fetchone()
    if not update or conn.execute('SELECT 1 FROM notice_calendar_receipts WHERE update_id=?',(update['update_id'],)).fetchone():return
    tasks=[(row,json.loads(row['data'])) for row in conn.execute("SELECT * FROM tasks WHERE notice_id=? AND user_id=? AND status='pending'",(nid,uid))]
    if not tasks:return
    def record(outcome,reason,cid=None):
        conn.execute('INSERT INTO notice_calendar_receipts VALUES(?,?,?,?,?)',(update['update_id'],cid,outcome,reason,int(time.time())))
        audit(conn,uid,nid,'notice_calendar_sync',after={'update_id':update['update_id'],'mode':mode,'outcome':outcome,'reason':reason,'change_id':cid})
    key=update['external_key'].split(':',2)
    url=update['source_url']
    try:parsed=urlsplit(url)
    except ValueError:return record('needs_review','发布链接无效，请核对当前原文。')
    subscription=conn.execute('SELECT config FROM source_subscriptions WHERE user_id=? AND source_id=? AND enabled=1',(uid,key[1])).fetchone() if len(key)==3 and key[0]=='website' and key[2]==url else None
    config=json.loads(subscription[0]) if subscription else {}
    host=parsed.hostname or ''
    if (not subscription or parsed.scheme!='https' or host!=urlsplit(config['url']).hostname or
            not (config.get('mode')=='feed' or parsed.path.startswith(config.get('article_path_prefix') or '/')) or
            not host.endswith(('.edu.cn','.edu','.gov.cn'))):
        return record('needs_review','来源尚需本人核实，已保留通知更新。')
    ids=set(json.loads(update['source_ids']))
    index={(s['id'],section['locator']):section['text'] for s in conn.execute(
            "SELECT s.id,s.sections,o.data AS origin FROM sources s LEFT JOIN notice_source_origins o ON o.source_id=s.id WHERE s.notice_id=? AND s.active=1",(nid,))
           if s['id'] in ids and s['origin'] and json.loads(s['origin']).get('url')==url and not json.loads(s['origin']).get('list_only')
           for section in json.loads(s['sections'])}
    draft=json.loads(notice['draft'])
    candidates=[v for v in draft.get('tasks',[]) if isinstance(v,dict)]
    def title(value):return re.sub(r'\s+','',value.get('title','')).casefold()
    counts=Counter(title(v) for v in candidates)
    task_counts=Counter(title(v) for _,v in tasks)
    targets,quotes=[],[]
    manual=False
    ambiguous=False
    for row,old in tasks:
        name=title(old)
        if not name or counts[name]!=1 or task_counts[name]!=1:continue
        item=next(v for v in candidates if title(v)==name)
        if item.get('scope','personal')!='personal' or item.get('uncertainties'):continue
        patch,cited=correction(old,item,index,notice['published_at'])
        if not patch:continue
        manual |= personally_changed(conn,row['id'],patch)
        ambiguous |= bool(re.search(r'原定|原地点|原截止|原要求|不再|无需|取消|暂定|预计|待定|转述|传言|未经核实|另行通知',' '.join(cited)))
        if 'due_date' in patch:
            dates=analyze(quoted(item.get('deadline_evidence'),index),notice['published_at'])
            ambiguous |= len(dates.days)>1 or len(dates.pairs)>1
        targets.append(ChangeTarget(task_id=row['id'],version=row['version'],patch=patch))
        quotes.extend(cited)
    if not targets:return record('needs_review','缺少可唯一对应的事项或最新原文依据，已保留现有日程。')
    excerpt='\n'.join(dict.fromkeys(quotes))
    if len(excerpt)>6000:return record('needs_review','多项依据超过单条变更容量，请分项核对。')
    quality=draft.get('quality') or {}
    try:
        proposal=propose(conn,nid,ChangeProposal(notice_version=notice['version'],kind='correction',text=excerpt,
                         source_label=update['source_label'] or '已订阅的发布方',source_url=url,published_at=notice['published_at'],targets=targets),{'id':uid})
    except (HTTPException,ValueError):
        return record('needs_review','正式变更校验未通过，请核对原文和已有安排。')
    cid=proposal['id']
    if ambiguous or manual or mode=='review' or quality.get('status') in ('needs_review','unavailable') or (mode=='verified_auto' and quality.get('status')!='passed'):
        return record('proposed','已生成变更预览。'+('涉及手动修改的字段，请本人核对。' if manual else '来源含多种时间或未定表述，请核实后决定。' if ambiguous else '等待本人核对确认。'),cid)
    conn.execute('SAVEPOINT calendar_apply')
    try:
        decide(conn,nid,cid,ChangeDecision(version=proposal['version'],decision='apply',verified=True,note='按本人授权与本次正式原文逐项核对'),{'id':uid},automatic=True)
    except (HTTPException,ValueError):
        conn.execute('ROLLBACK TO calendar_apply')
        record('proposed','自动校验未通过，变更已留待本人审核。',cid)
    else:
        record('applied','已更新有原文依据的字段，个人计划、提醒与办理进度保留。',cid)
    finally:
        conn.execute('RELEASE calendar_apply')
