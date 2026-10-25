"""Owner-confirmed grouping of related notifications; facts are never merged."""
import hashlib
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher

from fastapi import Depends, HTTPException
from pydantic import Field

from .db import audit, dumps, ident
from .models import Strict
from .notice_ingest import _distinct_round

TABLES = {'notice_matters', 'notice_matter_members', 'notice_relation_dismissals', 'import_notice_links'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS notice_matters(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS matters_owner ON notice_matters(user_id);
CREATE TABLE IF NOT EXISTS notice_matter_members(
 notice_id TEXT PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
 matter_id TEXT NOT NULL REFERENCES notice_matters(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS matters_members ON notice_matter_members(matter_id);
CREATE TABLE IF NOT EXISTS notice_relation_dismissals(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 left_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 right_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 left_version INTEGER NOT NULL, right_version INTEGER NOT NULL,
 PRIMARY KEY(user_id,left_id,right_id));
CREATE TABLE IF NOT EXISTS import_notice_links(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL, notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,source_id));
INSERT OR IGNORE INTO meta VALUES('notice_matters_schema_version','1');
"""


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='notice_matters_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise ValueError('通知事项归组版本不兼容或缺少必要数据表')
    conn.executescript(SCHEMA)


def own(conn, uid, nid):
    row = conn.execute('SELECT id,title,source_label,published_at,created_at,updated_at,version,status FROM notices WHERE id=? AND user_id=?', (nid,uid)).fetchone()
    if not row:raise HTTPException(404, '通知不存在或无权访问')
    return dict(row)


def group_for(conn, uid, nid):
    row = conn.execute('SELECT g.* FROM notice_matters g JOIN notice_matter_members m ON m.matter_id=g.id WHERE m.notice_id=? AND g.user_id=?', (nid,uid)).fetchone()
    if not row:return None
    group = dict(row)
    group['members'] = [dict(r) for r in conn.execute('SELECT n.id,n.title,n.source_label,n.published_at,n.created_at,n.updated_at,n.version,n.status FROM notices n JOIN notice_matter_members m ON m.notice_id=n.id WHERE m.matter_id=? AND n.user_id=? ORDER BY COALESCE(n.published_at,datetime(n.created_at,\'unixepoch\')),n.created_at,n.id', (group['id'],uid))]
    return group


def compact_title(title):
    value = unicodedata.normalize('NFKC', title).lower()
    value = re.sub(r'关于|开展|举办|组织|做好|有关|事宜|相关|通知|公告|补充|补报|更正|调整|变更|延期|延长|截止|时间|的', '', value)
    return re.sub(r'[^\w\u4e00-\u9fff]', '', value)


def different_round(left, right):
    if _distinct_round(left, right['title'], right['published_at']):return True
    pattern = r'第[一二三四五六七八九十百\d]+(?:届|讲|次|场)'
    a, b = set(re.findall(pattern,left['title'])), set(re.findall(pattern,right['title']))
    return bool(a and b and a != b)


def suggest(conn, uid, notice, current_group):
    ignored = {r['right_id'] if r['left_id']==notice['id'] else r['left_id']:r for r in conn.execute('SELECT * FROM notice_relation_dismissals WHERE user_id=? AND (left_id=? OR right_id=?)', (uid,notice['id'],notice['id']))}
    members = {n['id'] for n in current_group['members']} if current_group else {notice['id']}
    needle = compact_title(notice['title'])
    if len(needle) < 6:return []
    results = []
    for row in conn.execute('SELECT id,title,source_label,published_at,version,created_at,status FROM notices WHERE user_id=? AND id<>?', (uid,notice['id'])):
        other = dict(row)
        if other['id'] in members or different_round(notice,other):continue
        dismissed = ignored.get(other['id'])
        if dismissed:
            versions = {dismissed['left_id']:dismissed['left_version'],dismissed['right_id']:dismissed['right_version']}
            if versions[notice['id']]==notice['version'] and versions[other['id']]==other['version']:continue
        candidate = compact_title(other['title'])
        matcher = SequenceMatcher(None,needle,candidate,autojunk=False)
        score = matcher.ratio()
        if score < .72 or matcher.find_longest_match().size < 6:continue
        reasons = ['标题中的事项相近，需核对是否属于同一批次']
        if re.search('补充|更正|调整|变更|延期|延长',notice['title']+other['title']):reasons.append('其中包含补充或变更通知')
        if notice['source_label'] != other['source_label']:reasons.append('发布来源不同，需分别核对适用范围')
        results.append({**other,'reasons':reasons,'score':score})
    return sorted(results,key=lambda r:(-r['score'],-r['created_at'],r['id']))[:12]


def with_tasks(conn, uid, members):
    ids = {n['id'] for n in members}
    grouped = {nid:[] for nid in ids}
    if not ids:return members
    for row in conn.execute('SELECT t.id,t.notice_id,t.status,t.data,w.data AS workflow FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=? AND t.notice_id IN ('+','.join('?' for _ in ids)+')', (uid,*ids)):
        data=json.loads(row['data']);workflow=json.loads(row['workflow'] or '{}')
        grouped[row['notice_id']].append({'id':row['id'],'title':data['title'],'status':row['status'],
            **{key:data.get(key) for key in ('due_date','due_time','deadline_confirmed','deadline_text','scheduled','planned_at')},
            'submission':data.get('submission',''),
            'materials':data.get('materials',[]),'stage':workflow.get('stage','')})
    return [{**n,'tasks':grouped[n['id']]} for n in members]


def snapshot(conn, uid, nid, other_id=None):
    own(conn,uid,nid)
    ids = [nid] if not other_id else [nid,other_id]
    groups = {}
    members = {}
    for target in ids:
        notice = own(conn,uid,target)
        group = group_for(conn,uid,target)
        if group:
            groups[group['id']] = group
            members.update({n['id']:n for n in group['members']})
        else:members[target] = notice
    ordered = sorted(members.values(),key=lambda n:(n['created_at'],n['id']))
    version_data = {'groups':[(g['id'],g['version'],g['title']) for g in sorted(groups.values(),key=lambda g:g['id'])],
                    'members':[(n['id'],n['version'],n['title']) for n in ordered]}
    # Task/workflow edits also invalidate a preview, even when notice.version is unchanged.
    if members and other_id is not None:
        version_data['tasks'] = [tuple(r) for r in conn.execute('SELECT t.id,t.version,COALESCE(w.version,0) FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=? AND t.notice_id IN ('+','.join('?' for _ in members)+') ORDER BY t.id', (uid,*members))]
    token = hashlib.sha256(dumps(version_data).encode()).hexdigest()
    warnings = ['归入同一事项会保留每则原文、待办及提交记录；期限与要求仍需逐则核对。']
    if any(different_round(ordered[0],n) for n in ordered[1:]):warnings.append('这些通知出现不同年份、批次或场次，请确认确实需要一起跟进。')
    if len({n['source_label'] for n in ordered}) > 1:warnings.append('包含不同发布来源；学院、班级的补充要求不会覆盖原通知。')
    return {'token':token,'members':with_tasks(conn,uid,ordered),'groups':list(groups.values()),'warnings':warnings}


def merge(conn, uid, nid, other_id, token, title=''):
    if nid==other_id:raise HTTPException(422,'请选择另一则通知')
    view=snapshot(conn,uid,nid,other_id)
    if view['token']!=token:raise HTTPException(409,'通知、办理记录或事项归组已变化，请重新预览')
    if len(view['members'])>200:raise HTTPException(422,'单个事项最多归入 200 则通知，请按事项拆分')
    groups=view['groups'];now=int(time.time());gid=groups[0]['id'] if groups else ident()
    name=title.strip() or (groups[0]['title'] if groups else own(conn,uid,nid)['title'])
    if groups:
        conn.execute('UPDATE notice_matters SET title=?,version=version+1,updated_at=? WHERE id=? AND user_id=?',(name,now,gid,uid))
    else:conn.execute('INSERT INTO notice_matters VALUES(?,?,?,1,?,?)',(gid,uid,name,now,now))
    for member in view['members']:
        conn.execute('INSERT INTO notice_matter_members VALUES(?,?) ON CONFLICT(notice_id) DO UPDATE SET matter_id=excluded.matter_id',(member['id'],gid))
    for group in groups:
        if group['id']!=gid:conn.execute('DELETE FROM notice_matters WHERE id=? AND user_id=?',(group['id'],uid))
    audit(conn,uid,nid,'matter_grouped',after={'matter_id':gid,'title':name,'notice_ids':[n['id'] for n in view['members']]})
    return group_for(conn,uid,nid)


def detach(conn,uid,nid):
    group=group_for(conn,uid,nid)
    if not group:return
    conn.execute('DELETE FROM notice_matter_members WHERE notice_id=?',(nid,))
    if len(group['members'])<=2:conn.execute('DELETE FROM notice_matters WHERE id=?',(group['id'],))
    else:conn.execute('UPDATE notice_matters SET version=version+1,updated_at=? WHERE id=?',(int(time.time()),group['id']))
    audit(conn,uid,nid,'matter_ungrouped',before={'matter_id':group['id']})


def annotate(conn,uid,records):
    mapping = {r['notice_id']:dict(r) for r in conn.execute('SELECT m.notice_id,g.id,g.title,g.version,(SELECT COUNT(*) FROM notice_matter_members a WHERE a.matter_id=g.id) AS member_count FROM notice_matter_members m JOIN notice_matters g ON g.id=m.matter_id WHERE g.user_id=?',(uid,))}
    for n in records:n['matter']=mapping.get(n['id'])
    return records


def export_groups(conn,uid):
    return [{'id':r['id'],'title':r['title'],'notice_ids':[m[0] for m in conn.execute('SELECT notice_id FROM notice_matter_members WHERE matter_id=? ORDER BY notice_id',(r['id'],))]} for r in conn.execute('SELECT id,title FROM notice_matters WHERE user_id=? ORDER BY created_at,id',(uid,))]


def validate_import_groups(value, maximum):
    if not isinstance(value,list) or len(value)>maximum:raise ValueError('事项归组目录格式或数量不符合要求')
    seen=set();result=[]
    for entry in value:
        if not isinstance(entry,dict):raise ValueError('事项归组必须为对象')
        title=entry.get('title');members=entry.get('notice_ids')
        if not isinstance(title,str) or not title.strip() or len(title)>160:raise ValueError('事项名称不符合要求')
        if not isinstance(members,list) or not 2<=len(members)<=200 or any(not isinstance(x,str) or not 1<=len(x)<=100 for x in members):raise ValueError('事项归组的通知标识不符合要求')
        if len(set(members))!=len(members) or seen.intersection(members):raise ValueError('同一通知不能同时属于多个事项')
        seen.update(members);result.append({'title':title.strip(),'notice_ids':members})
    return result


def import_groups(conn,uid,groups):
    for entry in groups:
        key='matter:'+hashlib.sha256(dumps({'title':entry['title'],'notice_ids':sorted(entry['notice_ids'])}).encode()).hexdigest()
        if conn.execute('SELECT 1 FROM import_receipts WHERE user_id=? AND item_key=?',(uid,key)).fetchone():continue
        ids=[]
        for old_id in entry['notice_ids']:
            mapped=conn.execute('SELECT l.notice_id FROM import_notice_links l JOIN notices n ON n.id=l.notice_id WHERE l.user_id=? AND l.source_id=? AND n.user_id=?',(uid,old_id,uid)).fetchone()
            if not mapped:raise HTTPException(422,'归组引用的通知尚未导入，请一并导入组内通知；本次导入未保存')
            ids.append(mapped['notice_id'])
        if len(set(ids))!=len(ids):raise HTTPException(422,'归组通知标识重复，请核对导出文件')
        if any(group_for(conn,uid,nid) for nid in ids):raise HTTPException(409,'部分通知已有事项归组，导入未改写现有关系；请核对后移除文件中对应的 notice_matters 项')
        gid=ident();now=int(time.time())
        conn.execute('INSERT INTO notice_matters VALUES(?,?,?,1,?,?)',(gid,uid,entry['title'],now,now))
        conn.executemany('INSERT INTO notice_matter_members VALUES(?,?)',[(nid,gid) for nid in ids])
        conn.execute('INSERT INTO import_receipts VALUES(?,?,?)',(uid,key,now))


class Related(Strict):
    other_id: str = Field(min_length=1,max_length=100)


class GroupRequest(Related):
    token: str = Field(min_length=64,max_length=64)
    title: str = Field(default='',max_length=160)


class Token(Strict):
    token: str = Field(min_length=64,max_length=64)


def install(app,db,user):
    @app.get('/api/notices/{nid}/matter')
    def read(nid:str,current=Depends(user)):
        with db.connect() as conn:
            uid=current['id'];notice=own(conn,uid,nid);group=group_for(conn,uid,nid)
            if group:group['members']=with_tasks(conn,uid,group['members'])
            return {'group':group,'suggestions':suggest(conn,uid,notice,group),'token':snapshot(conn,uid,nid)['token']}

    @app.post('/api/notices/{nid}/matter/preview')
    def preview(nid:str,payload:Related,current=Depends(user)):
        with db.connect() as conn:return snapshot(conn,current['id'],nid,payload.other_id)

    @app.post('/api/notices/{nid}/matter')
    def save(nid:str,payload:GroupRequest,current=Depends(user)):
        with db.connect(write=True) as conn:return merge(conn,current['id'],nid,payload.other_id,payload.token,payload.title)

    @app.delete('/api/notices/{nid}/matter')
    def remove(nid:str,payload:Token,current=Depends(user)):
        with db.connect(write=True) as conn:
            if snapshot(conn,current['id'],nid)['token']!=payload.token:raise HTTPException(409,'事项归组已变化，请刷新后再操作')
            detach(conn,current['id'],nid)
            return {'ok':True}

    @app.post('/api/notices/{nid}/matter/dismiss')
    def dismiss(nid:str,payload:GroupRequest,current=Depends(user)):
        with db.connect(write=True) as conn:
            uid=current['id'];view=snapshot(conn,uid,nid,payload.other_id)
            if view['token']!=payload.token:raise HTTPException(409,'通知已变化，请重新核对')
            left,right=sorted([own(conn,uid,nid),own(conn,uid,payload.other_id)],key=lambda n:n['id'])
            conn.execute('INSERT OR REPLACE INTO notice_relation_dismissals VALUES(?,?,?,?,?)',(uid,left['id'],right['id'],left['version'],right['version']))
            return {'ok':True}
