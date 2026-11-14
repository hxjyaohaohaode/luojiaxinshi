"""Reviewed, bounded member imports; display identity is never authority."""
import hashlib
import json
import re
import secrets
import time
import unicodedata

from fastapi import Depends, HTTPException
from pydantic import Field, ValidationError

from .db import dumps
from .models import Strict

SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_roster_previews(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 college_id TEXT NOT NULL, payload TEXT NOT NULL, snapshot TEXT NOT NULL,
 result TEXT, expires_at INTEGER NOT NULL);
"""


class Preview(Strict):
    college_id: str = Field(min_length=1,max_length=80)
    rows: list[dict] = Field(min_length=1,max_length=500)


class Normalize(Strict):
    college_id: str = Field(min_length=1,max_length=80)


class Commit(Strict):
    review: str = Field(min_length=64,max_length=64,pattern=r'^[0-9a-f]+$')
    indices: list[int] = Field(min_length=1,max_length=500)
    reviewed: bool


def clean_label(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value or ''))).strip()


def normalized_grade(value):
    value=clean_label(value)
    return value+'级' if re.fullmatch(r'(?:19|20)\d{2}',value) else value


def normalize_row(raw):
    value=dict(raw)
    value['username']=clean_label(value.get('username')).lower()
    value['grade']=normalized_grade(value.get('grade',''))
    value['class_name']=clean_label(value.get('class_name',''))
    if isinstance(value.get('scopes'),list):
        scopes=[]
        for scope in value['scopes']:
            if not isinstance(scope,dict):
                scopes.append(scope)
                continue
            scopes.append({**scope,'grade':normalized_grade(scope.get('grade','')),
                           'class_name':clean_label(scope.get('class_name',''))})
        value['scopes']=scopes
    return value


def snapshot(conn,current,raw,college_id):
    from .campus import membership,manager
    authority=manager(conn,current,college_id)
    target=conn.execute('SELECT id,role FROM users WHERE username=?',(raw['username'],)).fetchone()
    old=membership(conn,target['id']) if target else None
    return {'authority':authority,'actor':membership(conn,current['id']),
            'target':dict(target) if target else None,'membership':old}


def inspect_rows(conn,current,college_id,rows):
    from .campus import MemberUpdate
    items=[]
    seen=set()
    for index,raw in enumerate(rows):
        errors,warnings=[],[]
        value=normalize_row(raw)
        username=value.pop('username','')
        value.pop('version',None)
        if set(value)-{'role','grade','class_name','scopes'}:
            errors.append('包含不支持的字段')
        record=snapshot(conn,current,{'username':username},college_id)
        target,old=record['target'],record['membership']
        try:
            normalized=MemberUpdate.model_validate({'college_id':college_id,**value,
                'version':old['version'] if old else 0}).model_dump()
        except ValidationError as exc:
            normalized=None
            errors.extend(str(e['msg']).removeprefix('Value error, ') for e in exc.errors()[:3])
        if username in seen:errors.append('此账号在本批重复出现，不会重复授权')
        seen.add(username)
        if target is None:errors.append('账号尚未注册，请先注册后重新预检')
        if target and record['authority']=='college_admin' and (
                target['id']==current['id'] or target['role']=='admin' or
                value.get('role')=='college_admin' or old and (old['role']=='college_admin' or old['college_id']!=college_id)):
            errors.append('超出学院管理员可修改的账号或学院范围')
        forbidden=bool(target and record['authority']=='college_admin' and (
            target['id']==current['id'] or target['role']=='admin' or value.get('role')=='college_admin'
            or old and (old['role']=='college_admin' or old['college_id']!=college_id)))
        grade=value.get('grade','')
        if grade and not re.fullmatch(r'(?:19|20)\d{2}级',grade):
            warnings.append('年级不是明确的入学年份，保留原名；不会把一年级猜成某届')
        if old and normalized:
            if (old['college_id'],old['role'],old['grade'],old['class_name'])!=(college_id,normalized['role'],normalized['grade'],normalized['class_name']):
                warnings.append('将变更原学院身份或班级；新范围即时生效，本人旧记录保留')
        items.append({'index':index,'username':username,'before':None if forbidden else old,'normalized':normalized,
                      'errors':errors,'warnings':warnings,'snapshot':record})
    return items


def audience_impacts(conn,college_id,items):
    """Compare exact existing publication scopes before any roster mutation."""
    from .campus import membership,scope_covers,Audience
    people={r['user_id']:{**membership(conn,r['user_id']),'username':r['username']} for r in conn.execute(
        'SELECT m.user_id,u.username FROM campus_members m JOIN users u ON u.id=m.user_id WHERE m.college_id=?',(college_id,))}
    proposed={key:dict(value) for key,value in people.items()}
    for item in items:
        if item['errors']:continue
        proposed[item['snapshot']['target']['id']]={**item['normalized'],'username':item['username']}
    def matches(person,audience):
        if person['role']=='college_admin':return True
        if person['role']=='student':return audience.audience=='college' or (
            person['grade']==audience.grade and (audience.audience=='grade' or person['class_name']==audience.class_name))
        if audience.audience=='college':return True
        if audience.audience=='grade':return any(not scope['grade'] or scope['grade']==audience.grade for scope in person['scopes'])
        return scope_covers(person['scopes'],audience)
    changes=[]
    for row in conn.execute('''SELECT DISTINCT audience,grade,class_name FROM campus_publications
        WHERE college_id=? ORDER BY audience,grade,class_name''',(college_id,)):
        audience=Audience(**dict(row))
        before={uid for uid,person in people.items() if matches(person,audience)}
        after={uid for uid,person in proposed.items() if matches(person,audience)}
        if before==after:continue
        changes.append({**dict(row),'before_count':len(before),'after_count':len(after),
            'added':[proposed[uid]['username'] for uid in sorted(after-before)],
            'removed':[people[uid]['username'] for uid in sorted(before-after)]})
    return changes


def create_preview(conn,current,college_id,rows):
    if len(dumps(rows).encode())>256*1024:raise HTTPException(413,'成员预检内容过大，请分批导入')
    items=inspect_rows(conn,current,college_id,rows)
    token,now=secrets.token_hex(32),int(time.time())
    conn.execute('DELETE FROM campus_roster_previews WHERE expires_at<? AND result IS NULL',(now,))
    conn.execute('DELETE FROM campus_roster_previews WHERE expires_at<?',(now-7*86400,))
    conn.execute('INSERT INTO campus_roster_previews VALUES(?,?,?,?,?,?,?)',
        (hashlib.sha256(token.encode()).hexdigest(),current['id'],college_id,dumps(items),
         dumps({'actor':items[0]['snapshot']['actor'] if items else None}),None,now+600))
    return {'review':token,'expires_at':now+600,'items':[{k:v for k,v in item.items() if k!='snapshot'} for item in items],
            'valid':sum(not item['errors'] for item in items),'invalid':sum(bool(item['errors']) for item in items),
            'audience_impacts':audience_impacts(conn,college_id,items),
            'impact_note':'范围比较按全部可提交行计算；变更不会自动补发公告，也不会重写已发布通知的原范围名称。',
            'note':'仅预检，尚未修改任何成员。请选择无错误的行，核对变更后提交。'}


def forget_deleted_member(conn,uid):
    """Preview snapshots are temporary, not a second personnel database."""
    for row in conn.execute('SELECT token_hash,payload,result FROM campus_roster_previews').fetchall():
        items=json.loads(row['payload'])
        affected={item['username'] for item in items if (item.get('snapshot',{}).get('target') or {}).get('id')==uid}
        if not affected:continue
        if row['result'] is None:
            conn.execute('DELETE FROM campus_roster_previews WHERE token_hash=?',(row['token_hash'],))
        else:
            result=json.loads(row['result'])
            for item in result['items']:
                if item['username'] in affected:item['username']='已注销账号'
            for impact in result.get('audience_impacts',[]):
                for key in ('added','removed'):
                    impact[key]=['已注销账号' if name in affected else name for name in impact[key]]
            remaining=[{'username':item['username'],'snapshot':{'target':{'id':item['snapshot']['target']['id']}}}
                       for item in items if item.get('snapshot',{}).get('target')
                       and item['snapshot']['target']['id']!=uid]
            conn.execute("UPDATE campus_roster_previews SET payload=?,snapshot='{}',result=? WHERE token_hash=?",
                         (dumps(remaining),dumps(result),row['token_hash']))


def install(app,db,user):
    from .campus import manager,membership,audit

    @app.post('/api/campus/roster/preview')
    def preview(payload:Preview,current=Depends(user)):
        with db.connect(write=True) as conn:
            manager(conn,current,payload.college_id)
            return create_preview(conn,current,payload.college_id,payload.rows)

    @app.post('/api/campus/roster/normalization-preview')
    def normalize(payload:Normalize,current=Depends(user)):
        with db.connect(write=True) as conn:
            manager(conn,current,payload.college_id)
            members=conn.execute('''SELECT u.username,m.* FROM campus_members m JOIN users u ON u.id=m.user_id
                WHERE m.college_id=? ORDER BY u.username LIMIT 501''',(payload.college_id,)).fetchall()
            if len(members)>500:raise HTTPException(413,'该学院超过500名成员，请导出后按班级分批预检')
            rows=[]
            for member in members:
                if current['role']!='admin' and member['role']=='college_admin':continue
                details=membership(conn,member['user_id'])
                raw={'username':member['username'],**{k:details[k] for k in ('role','grade','class_name','scopes')}}
                normalized=normalize_row(raw)
                if normalized!=raw:rows.append(raw)
            if not rows:return {'items':[],'valid':0,'invalid':0,'note':'没有可安全自动规范化的名称；一年级或同名班不会按当前日期猜测改名。'}
            return create_preview(conn,current,payload.college_id,rows)

    @app.post('/api/campus/roster/commit')
    def commit(payload:Commit,current=Depends(user)):
        if not payload.reviewed:raise HTTPException(422,'请先核对所选成员与变更范围')
        indices=sorted(set(payload.indices))
        if len(indices)!=len(payload.indices):raise HTTPException(422,'选择行重复')
        with db.connect(write=True) as conn:
            record=conn.execute('SELECT * FROM campus_roster_previews WHERE token_hash=? AND user_id=?',
                (hashlib.sha256(payload.review.encode()).hexdigest(),current['id'])).fetchone()
            if record is None:raise HTTPException(409,'预检不存在，请重新核对成员')
            manager(conn,current,record['college_id'])
            if record['result']:
                previous=json.loads(record['result'])
                if previous['indices']!=indices:raise HTTPException(409,'该预检已经提交其他行，请查看回执或重新预检')
                return previous
            if record['expires_at']<=int(time.time()):raise HTTPException(409,'预检已过期，请重新核对成员')
            items=json.loads(record['payload'])
            if any(index<0 or index>=len(items) for index in indices):raise HTTPException(422,'选择行不存在')
            selected=[items[index] for index in indices]
            for item in selected:
                if item['errors']:raise HTTPException(422,'所选行仍有错误：'+item['username'])
                latest=snapshot(conn,current,item,record['college_id'])
                if latest!=item['snapshot']:raise HTTPException(409,'成员或管理范围在预检后变化：'+item['username']+'；请重新预检')
            impacts=audience_impacts(conn,record['college_id'],selected)
            now=int(time.time())
            changes=[]
            for item in selected:
                target=item['snapshot']['target']['id'];value=item['normalized']
                old=item['before']
                comparable={k:old[k] for k in ('college_id','role','grade','class_name','scopes')} if old else None
                wanted={k:value[k] for k in ('college_id','role','grade','class_name','scopes')}
                if comparable==wanted:
                    changes.append({'username':item['username'],'state':'unchanged','version':old['version']})
                    continue
                conn.execute('''INSERT INTO campus_members VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(user_id)
                    DO UPDATE SET college_id=excluded.college_id,role=excluded.role,grade=excluded.grade,
                    class_name=excluded.class_name,version=campus_members.version+1,updated_at=excluded.updated_at''',
                    (target,value['college_id'],value['role'],value['grade'],value['class_name'],now,now))
                conn.execute('DELETE FROM campus_counselor_scopes WHERE user_id=?',(target,))
                for scope in value['scopes']:
                    conn.execute('INSERT INTO campus_counselor_scopes VALUES(?,?,?)',(target,scope['grade'],scope['class_name']))
                audit(conn,record['college_id'],current['id'],target,'import_member',{'before':comparable,'after':wanted})
                changes.append({'username':item['username'],'state':'saved','version':membership(conn,target)['version']})
            result={'ok':True,'indices':indices,'items':changes,'changed':sum(x['state']=='saved' for x in changes),
                    'audience_impacts':impacts,
                    'note':'所选成员已更新，本人旧通知和办理历史保留；尚未向新成员补发历史公告。'}
            conn.execute('UPDATE campus_roster_previews SET result=? WHERE token_hash=?',(dumps(result),record['token_hash']))
            return result
