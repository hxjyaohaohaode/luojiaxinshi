"""College-scoped roles and notices, independent of personal data ownership.

An organization role is explicitly granted by a manager. Self-edited profiles
never confer permissions. Publishing creates separate, owner-scoped inbox items.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from .db import dumps, ident
from .documents import MAX_CHARS, MAX_FILE, file_source, text_source, total_chars
from .models import Strict
from .campus_policy import PublicationPolicy, policy_changes, publication_policy, save_policy, stored_policy

TABLES = {'campus_colleges', 'campus_members', 'campus_counselor_scopes',
          'campus_publications', 'campus_publication_versions', 'campus_materials',
          'campus_deliveries', 'campus_audit'}
SPRINT_TABLES = {'campus_audience_reviews','campus_dispatch_authority','campus_material_refs',
                'campus_drafts','campus_draft_files','campus_roster_previews',
                'collaboration_retained_receipts','campus_publication_policy','collaboration_followups'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_colleges(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS campus_members(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 college_id TEXT NOT NULL REFERENCES campus_colleges(id),
 role TEXT NOT NULL CHECK(role IN ('college_admin','counselor','student')),
 grade TEXT NOT NULL DEFAULT '', class_name TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS campus_member_scope ON campus_members(college_id,role,grade,class_name);
CREATE TABLE IF NOT EXISTS campus_counselor_scopes(
 user_id TEXT NOT NULL REFERENCES campus_members(user_id) ON DELETE CASCADE,
 grade TEXT NOT NULL DEFAULT '', class_name TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,grade,class_name));
CREATE TABLE IF NOT EXISTS campus_publications(
 id TEXT PRIMARY KEY, college_id TEXT NOT NULL REFERENCES campus_colleges(id),
 publisher_id TEXT REFERENCES users(id) ON DELETE SET NULL,
 publisher_name TEXT NOT NULL, request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
 audience TEXT NOT NULL CHECK(audience IN ('college','grade','class')),
 grade TEXT NOT NULL DEFAULT '', class_name TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL CHECK(state IN ('published','withdrawn')),
 version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 UNIQUE(publisher_id,request_id));
CREATE INDEX IF NOT EXISTS campus_pub_college ON campus_publications(college_id,created_at);
CREATE TABLE IF NOT EXISTS campus_publication_versions(
 publication_id TEXT NOT NULL REFERENCES campus_publications(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 actor_id TEXT REFERENCES users(id) ON DELETE SET NULL, created_at INTEGER NOT NULL,
 PRIMARY KEY(publication_id,version));
CREATE TABLE IF NOT EXISTS campus_materials(
 publication_id TEXT NOT NULL, version INTEGER NOT NULL, position INTEGER NOT NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL,
 sections TEXT NOT NULL, status TEXT NOT NULL, warning TEXT NOT NULL,
 PRIMARY KEY(publication_id,version,position),
 FOREIGN KEY(publication_id,version) REFERENCES campus_publication_versions(publication_id,version) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS campus_deliveries(
 publication_id TEXT NOT NULL REFERENCES campus_publications(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 notice_id TEXT REFERENCES notices(id) ON DELETE SET NULL,
 delivered_version INTEGER NOT NULL DEFAULT 0, attempted_version INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL CHECK(state IN ('pending','delivered','failed','out_of_scope')),
 error TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL,
 PRIMARY KEY(publication_id,user_id));
CREATE TABLE IF NOT EXISTS campus_audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, college_id TEXT NOT NULL,
 actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
 target_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
 action TEXT NOT NULL, details TEXT NOT NULL, created_at INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('campus_schema_version','1');
INSERT OR IGNORE INTO campus_colleges VALUES('sres','武汉大学资源与环境科学学院',0);
"""

EXTENSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_audience_reviews(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS campus_review_expiry ON campus_audience_reviews(expires_at);
CREATE TABLE IF NOT EXISTS campus_dispatch_authority(
 publication_id TEXT PRIMARY KEY REFERENCES campus_publications(id) ON DELETE CASCADE,
 actor_id TEXT REFERENCES users(id) ON DELETE SET NULL, version INTEGER NOT NULL);
"""

REVIEW_SECONDS = 10 * 60
DELIVERY_BATCH_SIZE = 24
MAX_RECIPIENTS = 1000


def initialize(conn):
    version = conn.execute("SELECT value FROM meta WHERE key='campus_schema_version'").fetchone()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0] != '1' or not TABLES.issubset(tables)):
        raise RuntimeError('学院权限数据版本不兼容或必要表缺失，未修改数据')
    conn.executescript(SCHEMA)
    conn.executescript(EXTENSION_SCHEMA)
    from .campus_assets import SCHEMA as ASSET_SCHEMA
    conn.executescript(ASSET_SCHEMA)
    from .campus_drafts import SCHEMA as DRAFT_SCHEMA
    conn.executescript(DRAFT_SCHEMA)
    from .campus_roster import SCHEMA as ROSTER_SCHEMA
    conn.executescript(ROSTER_SCHEMA)
    from .campus_policy import SCHEMA as POLICY_SCHEMA
    conn.executescript(POLICY_SCHEMA)


class Scope(Strict):
    grade: str = Field(default='', max_length=40)
    class_name: str = Field(default='', max_length=80)
    all_college: bool = False

    @model_validator(mode='after')
    def valid_scope(self):
        if (self.all_college and (self.grade or self.class_name)) or (not self.all_college and not self.grade):
            raise ValueError('请明确选择全院，或指定负责的年级及班级')
        return self


class MemberUpdate(Strict):
    college_id: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9_-]+$')
    role: Literal['college_admin', 'counselor', 'student']
    grade: str = Field(default='', max_length=40)
    class_name: str = Field(default='', max_length=80)
    scopes: list[Scope] = Field(default_factory=list, max_length=30)
    version: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def valid_role(self):
        if self.role == 'student':
            if not self.grade or not self.class_name or self.scopes:
                raise ValueError('学生须指定年级和班级，不接受管理范围')
        elif self.role == 'counselor':
            if self.grade or self.class_name or not self.scopes:
                raise ValueError('辅导员须明确指定至少一项负责范围')
            items = [(s.grade, s.class_name) for s in self.scopes]
            if len(set(items)) != len(items) or (('', '') in items and len(items) != 1):
                raise ValueError('负责范围重复，或全院范围与其他范围同时填写')
        elif self.grade or self.class_name or self.scopes:
            raise ValueError('学院管理员默认负责本学院，无需填写年级和班级')
        return self


class Version(Strict):
    version: int = Field(ge=1)


class Audience(Strict):
    audience: Literal['college', 'grade', 'class']
    grade: str = Field(default='', max_length=40)
    class_name: str = Field(default='', max_length=80)

    @model_validator(mode='after')
    def valid_audience(self):
        if ((self.audience == 'college' and (self.grade or self.class_name)) or
            (self.audience == 'grade' and (not self.grade or self.class_name)) or
            (self.audience == 'class' and (not self.grade or not self.class_name))):
            raise ValueError('请选择完整且一致的学院、年级或班级范围')
        return self


class Publication(Audience,PublicationPolicy):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=MAX_CHARS)
    request_id: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    audience_review: str | None = Field(default=None, min_length=64, max_length=64, pattern=r'^[0-9a-f]+$')
    draft_id: str | None = Field(default=None, min_length=1, max_length=80)
    draft_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def valid_draft_reference(self):
        if (self.draft_id is None) != (self.draft_version is None):
            raise ValueError('发布草稿时须同时提供草稿编号与版本')
        if not self.title.strip() or not self.body.strip():
            raise ValueError('请填写实际的通知标题和正文')
        return self


class Correction(PublicationPolicy):
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=MAX_CHARS)
    keep_attachments: bool = True

    @model_validator(mode='after')
    def nonblank(self):
        if not self.title.strip() or not self.body.strip():
            raise ValueError('请填写实际的通知标题和正文')
        return self


class Withdrawal(Version):
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def nonblank_reason(self):
        if not self.reason.strip():raise ValueError('请填写实际的发布变更说明')
        return self


class Restoration(Correction):
    reason: str = Field(min_length=1, max_length=1000)
    keep_attachments: bool = False

    @model_validator(mode='after')
    def nonblank_reason(self):
        if not self.reason.strip():raise ValueError('请填写实际的恢复说明')
        return self


class DeliveryRetry(Strict):
    audience_review: str | None = Field(default=None,min_length=64,max_length=64,pattern=r'^[0-9a-f]+$')


class Rollback(Withdrawal):
    target_version: int = Field(ge=1)


class Backfill(Version):
    audience_review: str = Field(min_length=64,max_length=64,pattern=r'^[0-9a-f]+$')
    reference_confirmed: bool = False


def college(conn, college_id):
    row = conn.execute('SELECT * FROM campus_colleges WHERE id=?', (college_id,)).fetchone()
    if not row:
        raise HTTPException(404, '学院不存在')
    return dict(row)


def membership(conn, uid):
    row = conn.execute('SELECT m.*,c.name AS college_name FROM campus_members m JOIN campus_colleges c ON c.id=m.college_id WHERE m.user_id=?', (uid,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result['scopes'] = [{**dict(r), 'all_college': not r['grade']} for r in conn.execute('SELECT grade,class_name FROM campus_counselor_scopes WHERE user_id=? ORDER BY grade,class_name', (uid,))]
    return result


def affiliation_evidence(conn,uid):
    member=membership(conn,uid)
    if not member:return None
    return {'authority':'本站经管理员授权的学院身份，用于站内范围核对',
            'role':member['role'],'college':member['college_name'],
            'grade':member['grade'],'class_name':member['class_name'],
            'scopes':member['scopes']}


def manager(conn, current, college_id):
    college(conn, college_id)
    if current['role'] == 'admin':
        return 'site_admin'
    own = membership(conn, current['id'])
    if not own or own['college_id'] != college_id or own['role'] != 'college_admin':
        raise HTTPException(403, '仅本学院管理员或系统管理员可管理成员')
    return 'college_admin'


def scope_covers(scopes, audience):
    for scope in scopes:
        if not scope['grade']:
            return True
        if audience.audience == 'grade' and scope['grade'] == audience.grade and not scope['class_name']:
            return True
        if (audience.audience == 'class' and scope['grade'] == audience.grade and
                (not scope['class_name'] or scope['class_name'] == audience.class_name)):
            return True
    return False


def publisher(conn, uid, audience=None):
    own = membership(conn, uid)
    if not own or own['role'] not in {'college_admin', 'counselor'}:
        raise HTTPException(403, '仅已授权的学院管理员或辅导员可发布学院通知')
    if audience and own['role'] == 'counselor' and not scope_covers(own['scopes'], audience):
        raise HTTPException(403, '发布范围超出你被授权负责的年级或班级')
    return own


def eligible(conn, m, audience):
    if m['role'] == 'college_admin':
        return True
    if m['role'] == 'student':
        return (audience.audience == 'college' or
                m['grade'] == audience.grade and (audience.audience == 'grade' or m['class_name'] == audience.class_name))
    if audience.audience == 'college':
        return True
    scopes = [dict(r) for r in conn.execute('SELECT grade,class_name FROM campus_counselor_scopes WHERE user_id=?', (m['user_id'],))]
    if audience.audience == 'grade':
        return any(not s['grade'] or s['grade'] == audience.grade for s in scopes)
    return scope_covers(scopes, audience)


def recipients(conn, college_id, audience):
    members = conn.execute('SELECT * FROM campus_members WHERE college_id=? ORDER BY user_id', (college_id,)).fetchall()
    return [dict(m) for m in members if eligible(conn, m, audience)]


def audience_from(row):
    return Audience(audience=row['audience'], grade=row['grade'], class_name=row['class_name'])


def audit(conn, college_id, actor_id, target_id, action, details):
    conn.execute('INSERT INTO campus_audit(college_id,actor_id,target_user_id,action,details,created_at) VALUES(?,?,?,?,?,?)',
                 (college_id, actor_id, target_id, action, dumps(details), int(time.time())))


def publication_for(conn, pid, uid):
    own = publisher(conn, uid)
    row = conn.execute('SELECT * FROM campus_publications WHERE id=? AND college_id=?', (pid, own['college_id'])).fetchone()
    if not row or (own['role'] == 'counselor' and row['publisher_id'] != uid):
        raise HTTPException(404, '发布记录不存在或无权查看')
    if own['role'] == 'counselor' and not scope_covers(own['scopes'], audience_from(row)):
        raise HTTPException(403, '当前负责范围已变化，无法管理这条通知')
    return dict(row)


def publication_view(conn, row):
    latest = conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?', (row['id'], row['version'])).fetchone()
    counts = dict(conn.execute('SELECT state,count(*) FROM campus_deliveries WHERE publication_id=? GROUP BY state', (row['id'],)).fetchall())
    files = [dict(r) for r in conn.execute('SELECT name,kind,status,warning,sha256,length(content) AS size FROM campus_materials WHERE publication_id=? AND version=? ORDER BY position', (row['id'], row['version']))]
    previous=conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?',
                          (row['id'],row['version']-1)).fetchone()
    prior_files={(r['name'],r['sha256']) for r in conn.execute('SELECT name,sha256 FROM campus_materials WHERE publication_id=? AND version=?',
                                                            (row['id'],row['version']-1))}
    current_files={(r['name'],r['sha256']) for r in files}
    changes={'title_changed':bool(previous and previous['title']!=latest['title']),
             'body_changed':bool(previous and previous['body']!=latest['body']),
             'attachments_added':[name for name,_ in sorted(current_files-prior_files)],
             'attachments_removed':[name for name,_ in sorted(prior_files-current_files)]}
    return {**{k: row[k] for k in ('id','college_id','publisher_name','audience','grade','class_name','state','version','created_at','updated_at')},
            'title': latest['title'], 'body': latest['body'], 'attachments': files,
            'change_summary':changes,
            'publication_policy':publication_policy(conn,row['id'],row['version']),
            'version_context':version_context(conn,row['id'],row['version']),
            'delivery': {'total': sum(counts.values()), 'delivered': counts.get('delivered', 0),
                         'failed': counts.get('failed', 0), 'out_of_scope': counts.get('out_of_scope', 0),
                         'pending': counts.get('pending', 0), 'stage':'in_app',
                         'note':'站内分发不表示渠道接受、本人打开或办理完成'}}


def version_context(conn,pid,version):
    event=conn.execute("""SELECT action,details FROM campus_audit
        WHERE json_extract(details,'$.publication_id')=? AND json_extract(details,'$.version')=?
        ORDER BY id DESC LIMIT 1""",(pid,version)).fetchone()
    details=json.loads(event['details']) if event else {}
    return {'kind':event['action'] if event else 'publish' if version==1 else 'unknown',
            'reason':details.get('reason',''),'target_version':details.get('target_version')}


def version_kind(conn,pid,version):
    return version_context(conn,pid,version)['kind']


async def request_materials(request, model):
    """Read bounded multipart input; JSON without attachments is also supported."""
    content_type = request.headers.get('content-type', '').lower()
    files = []
    if content_type.startswith('application/json'):
        try:
            raw = await request.json()
        except ValueError:
            raise HTTPException(422, '通知内容格式不正确') from None
    else:
        form = await request.form(max_files=3, max_fields=2, max_part_size=120000)
        try:
            if set(form.keys()) - {'data', 'files'}:
                raise HTTPException(422, '通知中包含不支持的字段')
            try:
                raw = json.loads(str(form.get('data', '')))
            except (TypeError, ValueError):
                raise HTTPException(422, '通知内容格式不正确') from None
            for upload in form.getlist('files'):
                if not hasattr(upload, 'read'):
                    raise HTTPException(422, '附件字段不正确')
                data = await upload.read(MAX_FILE + 1)
                try:
                    files.append(await run_in_threadpool(file_source, upload.filename or '', data))
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from None
        finally:
            await form.close()
    try:
        payload = model.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(422, '; '.join(str(e['msg']).removeprefix('Value error, ') for e in exc.errors()[:5])) from None
    return payload, files


def material_sources(conn, pid, version):
    return [{'id': ident(), 'name': r['name'], 'kind': r['kind'], 'content': r['content'],
             'sha256': r['sha256'], 'sections': json.loads(r['sections']),
             'status': r['status'], 'warning': r['warning']}
            for r in conn.execute('SELECT * FROM campus_materials WHERE publication_id=? AND version=? ORDER BY position', (pid, version))]


def save_version(conn, pid, version, title, body, actor_id, files, *, replace_draft=None, policy=None):
    sources = [text_source(title + '\n\n' + body, '学院通知正文'), *files]
    if len(files) > 3 or total_chars(sources) > MAX_CHARS:
        raise HTTPException(422, '正文和附件合计不能超过 10000 字，附件最多 3 份')
    if sum(len(f.get('content') or b'') for f in files) > 8 * 1024 * 1024:
        raise HTTPException(422, '单条通知附件总大小不能超过 8 MB')
    from .campus_assets import check_publication_storage
    check_publication_storage(conn,actor_id,sum(len(f.get('content') or b'') for f in files),replace_draft=replace_draft)
    conn.execute('INSERT INTO campus_publication_versions VALUES(?,?,?,?,?,?)',
                 (pid, version, title, body, actor_id, int(time.time())))
    save_policy(conn,pid,version,policy)
    for position, source in enumerate(files):
        conn.execute('INSERT INTO campus_materials VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (pid, version, position, source['name'], source['kind'], source['content'], source['sha256'],
                      dumps(source['sections']), source['status'], source.get('warning', '')))
    return sources


def _review_fingerprint(conn, actor_id, college_id, audience, selected):
    own = membership(conn, actor_id)
    contents = {'actor': actor_id, 'college': college_id,
                'actor_membership': own,
                'audience': audience.model_dump(include={'audience','grade','class_name'}),
                'members': [(m['user_id'], m['role'], m['version']) for m in selected]}
    return hashlib.sha256(dumps(contents).encode()).hexdigest()


def require_audience_review(conn,actor_id,college_id,audience,selected,token):
    review=conn.execute('SELECT * FROM campus_audience_reviews WHERE token_hash=? AND user_id=?',
        (hashlib.sha256((token or '').encode()).hexdigest(),actor_id)).fetchone()
    expected=_review_fingerprint(conn,actor_id,college_id,audience,selected)
    if (review is None or review['expires_at']<=int(time.time()) or
            not hmac.compare_digest(review['fingerprint'],expected)):
        raise HTTPException(409,'接收范围尚未核对、成员已变化或核对已过期，请重新核对后再发布')


def queue_delivery(conn, row, actor_id, *, retry_only=False):
    condition = " AND state='failed'" if retry_only else ''
    conn.execute("UPDATE campus_deliveries SET state='pending',error='',updated_at=? "
                 "WHERE publication_id=? AND delivered_version<?" + condition,
                 (int(time.time()), row['id'], row['version']))
    conn.execute("""INSERT INTO campus_dispatch_authority VALUES(?,?,?)
        ON CONFLICT(publication_id) DO UPDATE SET actor_id=excluded.actor_id,version=excluded.version""",
                 (row['id'], actor_id, row['version']))


def _delivery_sources(conn, row):
    latest=conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?',
                        (row['id'],row['version'])).fetchone()
    files=material_sources(conn,row['id'],row['version'])
    return latest['title'], [text_source(latest['title']+'\n\n'+latest['body'],'学院通知正文'),*files]


def drain_publications(db, *, publication_id=None, limit=DELIVERY_BATCH_SIZE):
    """Bounded local outbox: one recipient/transaction, recoverable on restart.

    No network or outbound reminder is sent here. A crash rolls back only the
    in-flight recipient. Other requests can change membership between commits.
    """
    from .notice_ingest import ingest_notice
    from .campus_assets import bind_material_refs
    from .usage_limits import check_storage
    processed=0
    source_cache={}
    for _ in range(max(0,min(int(limit),MAX_RECIPIENTS))):
        with db.connect(write=True) as conn:
            condition=' AND d.publication_id=?' if publication_id else ''
            params=(publication_id,) if publication_id else ()
            item=conn.execute("""SELECT d.* FROM campus_deliveries d
                JOIN campus_publications p ON p.id=d.publication_id
                WHERE d.state='pending' AND d.delivered_version<p.version"""+condition+
                ' ORDER BY d.updated_at,d.publication_id,d.user_id LIMIT 1',params).fetchone()
            if item is None:break
            row=dict(conn.execute('SELECT * FROM campus_publications WHERE id=?',(item['publication_id'],)).fetchone())
            authority=conn.execute('SELECT * FROM campus_dispatch_authority WHERE publication_id=?',(row['id'],)).fetchone()
            actor_id=authority['actor_id'] if authority else None
            audience=audience_from(row)
            now=int(time.time())
            try:
                if not authority or authority['version']!=row['version']:
                    raise HTTPException(403,'分发授权需重新核对')
                actor=publisher(conn,actor_id,audience)
                if actor['college_id']!=row['college_id']:
                    raise HTTPException(403,'发布管理范围已变化')
            except HTTPException:
                conn.execute("UPDATE campus_deliveries SET state='failed',error=?,attempted_version=?,updated_at=? WHERE publication_id=? AND user_id=?",
                    ('分发授权无效或发布者已失权，请本院管理员重新核对范围后恢复分发',row['version'],now,row['id'],item['user_id']))
                processed+=1
                continue
            member=membership(conn,item['user_id'])
            if not member or member['college_id']!=row['college_id'] or not eligible(conn,member,audience):
                conn.execute("UPDATE campus_deliveries SET state='out_of_scope',attempted_version=?,error='',updated_at=? WHERE publication_id=? AND user_id=?",
                    (row['version'],now,row['id'],item['user_id']))
                processed+=1
                continue
            cache_key=(row['id'],row['version'])
            if cache_key not in source_cache:source_cache[cache_key]=_delivery_sources(conn,row)
            title,sources=source_cache[cache_key]
            label=college(conn,row['college_id'])['name']+' · 学院工作台发布'
            target='全院' if audience.audience=='college' else audience.grade+(' / '+audience.class_name if audience.audience=='class' else '')
            if len(label+' · '+target)<=100:label+=' · '+target
            conn.execute('SAVEPOINT campus_recipient')
            try:
                # Preserve logical quotas while storing a single immutable blob.
                known=set()
                if item['notice_id']:
                    known={(r['kind'],r['sha256']) for r in conn.execute('SELECT kind,sha256 FROM sources WHERE notice_id=?',(item['notice_id'],))}
                new_bytes=sum(len(s.get('content') or b'') for s in sources if (s['kind'],s['sha256']) not in known)
                check_storage(conn,item['user_id'],new_bytes)
                result=ingest_notice(conn,item['user_id'],sources=[{**s,'content':None} for s in sources],
                    title=title,source_label=label,source_url='',
                    published_at=datetime.fromtimestamp(row['updated_at'],timezone.utc).isoformat(),
                    external_key='campus-publication:'+row['id'],materials_complete=False,
                    allow_duplicate=True,observed_at=time.time(),separate_rounds=False)
                bind_material_refs(conn,result['notice_id'],row['id'],row['version'])
                conn.execute("UPDATE campus_deliveries SET notice_id=?,delivered_version=?,attempted_version=?,state='delivered',error='',updated_at=? WHERE publication_id=? AND user_id=?",
                    (result['notice_id'],row['version'],row['version'],now,row['id'],item['user_id']))
                conn.execute('RELEASE campus_recipient')
            except Exception as exc:
                conn.execute('ROLLBACK TO campus_recipient')
                conn.execute('RELEASE campus_recipient')
                error=str(exc.detail)[:300] if isinstance(exc,HTTPException) else '本次接收未完成，可重试；其他成员的回执已保留'
                if not isinstance(exc,HTTPException):
                    logging.getLogger('campus').error('publication_delivery_failed type=%s',type(exc).__name__)
                conn.execute("UPDATE campus_deliveries SET attempted_version=?,state='failed',error=?,updated_at=? WHERE publication_id=? AND user_id=?",
                    (row['version'],error,now,row['id'],item['user_id']))
            processed+=1
    return {'processed':processed}


def install(app, db, user):
    from .campus_drafts import install as install_drafts
    from .campus_roster import install as install_roster
    # A review page from a previous process must be checked afresh. Committed
    # publication request IDs remain replayable after restart independently.
    with db.connect(write=True) as conn:
        conn.execute('DELETE FROM campus_audience_reviews')
        conn.execute('DELETE FROM campus_roster_previews WHERE result IS NULL')
    install_drafts(app,db,user)
    install_roster(app,db,user)

    @app.get('/api/campus/context')
    def context(current=Depends(user)):
        with db.connect() as conn:
            own = membership(conn, current['id'])
            colleges = [dict(r) for r in conn.execute('SELECT id,name FROM campus_colleges ORDER BY name')]
            return {'site_admin': current['role'] == 'admin', 'membership': own, 'colleges': colleges}

    @app.get('/api/campus/members')
    def member_list(college_id: str, current=Depends(user)):
        with db.connect() as conn:
            college(conn, college_id)
            own = membership(conn, current['id'])
            can_manage = current['role'] == 'admin' or (own and own['college_id'] == college_id and own['role'] == 'college_admin')
            counselor = own and own['college_id'] == college_id and own['role'] == 'counselor'
            if not can_manage and not counselor:
                raise HTTPException(403, '无权查看学院成员')
            rows = conn.execute('SELECT m.*,u.username,u.display_name FROM campus_members m JOIN users u ON u.id=m.user_id WHERE m.college_id=? ORDER BY m.role,m.grade,m.class_name,u.username', (college_id,)).fetchall()
            result = []
            for row in rows:
                if counselor and not can_manage and (row['role'] != 'student' or not scope_covers(own['scopes'], Audience(audience='class', grade=row['grade'], class_name=row['class_name']))):
                    continue
                item = {k: row[k] for k in ('username','display_name','role','grade','class_name','version')}
                item['scopes'] = [{**dict(s), 'all_college': not s['grade']} for s in conn.execute('SELECT grade,class_name FROM campus_counselor_scopes WHERE user_id=? ORDER BY grade,class_name', (row['user_id'],))]
                result.append(item)
            return {'members': result, 'can_manage': bool(can_manage)}

    @app.put('/api/campus/members/{username}')
    def assign_member(username: str, payload: MemberUpdate, current=Depends(user)):
        username = username.lower()
        with db.connect(write=True) as conn:
            actor = manager(conn, current, payload.college_id)
            target = conn.execute('SELECT id,role FROM users WHERE username=?', (username,)).fetchone()
            if not target:
                raise HTTPException(404, '账号不存在，请先让成员注册')
            old = membership(conn, target['id'])
            if actor == 'college_admin' and (target['id'] == current['id'] or target['role'] == 'admin' or
                    payload.role == 'college_admin' or old and (old['role'] == 'college_admin' or old['college_id'] != payload.college_id)):
                raise HTTPException(403, '学院管理员只能管理本学院的辅导员和学生，不能更改管理员权限')
            if payload.version != (old['version'] if old else 0):
                raise HTTPException(409, '成员授权已变化，请刷新后重新操作')
            now = int(time.time())
            conn.execute('''INSERT INTO campus_members(user_id,college_id,role,grade,class_name,version,created_at,updated_at)
                VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(user_id) DO UPDATE SET college_id=excluded.college_id,
                role=excluded.role,grade=excluded.grade,class_name=excluded.class_name,version=campus_members.version+1,updated_at=excluded.updated_at''',
                (target['id'], payload.college_id, payload.role, payload.grade, payload.class_name, now, now))
            conn.execute('DELETE FROM campus_counselor_scopes WHERE user_id=?', (target['id'],))
            for scope in payload.scopes:
                conn.execute('INSERT INTO campus_counselor_scopes VALUES(?,?,?)', (target['id'], scope.grade, scope.class_name))
            audit(conn, payload.college_id, current['id'], target['id'], 'assign_member',
                  {'role': payload.role, 'grade': payload.grade, 'class_name': payload.class_name,
                   'scopes': [s.model_dump() for s in payload.scopes]})
            return {'ok': True, 'membership': membership(conn, target['id'])}

    @app.delete('/api/campus/members/{username}')
    def remove_member(username: str, payload: Version, current=Depends(user)):
        with db.connect(write=True) as conn:
            target = conn.execute('SELECT id,role FROM users WHERE username=?', (username.lower(),)).fetchone()
            old = membership(conn, target['id']) if target else None
            if not old:
                raise HTTPException(404, '成员不存在')
            actor = manager(conn, current, old['college_id'])
            if actor == 'college_admin' and (target['id'] == current['id'] or target['role'] == 'admin' or old['role'] == 'college_admin'):
                raise HTTPException(403, '学院管理员不能移除管理员权限')
            if old['version'] != payload.version:
                raise HTTPException(409, '成员授权已变化，请刷新后重试')
            audit(conn, old['college_id'], current['id'], target['id'], 'remove_member', {'role': old['role']})
            conn.execute('DELETE FROM campus_members WHERE user_id=?', (target['id'],))
            return {'ok': True, 'message': '学院授权已移除，个人已有通知和数据保留'}

    @app.get('/api/campus/audit')
    def audit_list(college_id: str, before_id:int|None=Query(None,ge=1),
                   page_size:int=Query(100,ge=1,le=100),action:str=Query('',max_length=40),current=Depends(user)):
        with db.connect() as conn:
            manager(conn, current, college_id)
            condition='a.college_id=?';params=[college_id]
            if before_id:condition+=' AND a.id<?';params.append(before_id)
            if action:condition+=' AND a.action=?';params.append(action)
            rows=conn.execute("""SELECT a.id,a.action,a.details,a.created_at,
                COALESCE(actor.display_name,'账号已注销') AS actor_name,
                COALESCE(target.display_name,'') AS target_name
                FROM campus_audit a LEFT JOIN users actor ON actor.id=a.actor_id
                LEFT JOIN users target ON target.id=a.target_user_id
                WHERE """+condition+' ORDER BY a.id DESC LIMIT ?',(*params,page_size+1)).fetchall()
            selected=rows[:page_size]
            return {'items':[{**dict(r),'details':json.loads(r['details'])} for r in selected],
                    'has_more':len(rows)>page_size,
                    'next_cursor':selected[-1]['id'] if len(rows)>page_size else None}

    @app.post('/api/campus/audience-preview')
    def preview(payload: Audience, current=Depends(user)):
        with db.connect() as conn:
            own = publisher(conn, current['id'], payload)
            result = recipients(conn, own['college_id'], payload)
            return {'total': len(result), 'students': sum(m['role'] == 'student' for m in result),
                    'staff': sum(m['role'] != 'student' for m in result)}

    @app.post('/api/campus/audience-review')
    def review_audience(payload: Audience, current=Depends(user)):
        with db.connect(write=True) as conn:
            own = publisher(conn, current['id'], payload)
            selected = recipients(conn, own['college_id'], payload)
            token,now=secrets.token_hex(32),int(time.time())
            conn.execute('DELETE FROM campus_audience_reviews WHERE expires_at<?',(now,))
            conn.execute('INSERT INTO campus_audience_reviews VALUES(?,?,?,?,?)',
                (hashlib.sha256(token.encode()).hexdigest(),current['id'],
                 _review_fingerprint(conn,current['id'],own['college_id'],payload,selected),now,now+REVIEW_SECONDS))
            return {'total': len(selected), 'students': sum(m['role'] == 'student' for m in selected),
                    'staff': sum(m['role'] != 'student' for m in selected),
                    'review': token, 'expires_at':now+REVIEW_SECONDS,
                    'limits':{'recipients':MAX_RECIPIENTS,'attachment_bytes':8*1024*1024,
                              'attachments':3,'storage':'shared_original'},
                    'warnings':(['当前范围没有学生，工作人员收件不能代表学生已收到']
                                if not any(m['role']=='student' for m in selected) else [])}

    @app.get('/api/campus/publications')
    def list_publications(page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                          q: str = Query('', max_length=80), current=Depends(user)):
        with db.connect() as conn:
            own = publisher(conn, current['id'])
            sql = '''SELECT p.* FROM campus_publications p JOIN campus_publication_versions v
                ON v.publication_id=p.id AND v.version=p.version WHERE p.college_id=?'''
            params = [own['college_id']]
            if own['role'] == 'counselor':
                sql += ' AND p.publisher_id=?'
                params.append(current['id'])
            if q.strip():
                sql += ''' AND (instr(lower(v.title),lower(?))>0 OR instr(lower(p.publisher_name),lower(?))>0
                    OR instr(lower(p.grade),lower(?))>0 OR instr(lower(p.class_name),lower(?))>0)'''
                params.extend([q.strip()] * 4)
            if own['role']=='counselor' and not any(not scope['grade'] for scope in own['scopes']):
                conditions=[]
                for scope in own['scopes']:
                    if scope['class_name']:
                        conditions.append("(p.audience='class' AND p.grade=? AND p.class_name=?)")
                        params.extend([scope['grade'],scope['class_name']])
                    else:
                        conditions.append("(p.audience IN ('grade','class') AND p.grade=?)")
                        params.append(scope['grade'])
                sql+=' AND ('+(' OR '.join(conditions) or '0')+')'
            total=conn.execute('SELECT count(*) FROM ('+sql+')',params).fetchone()[0]
            pages=max(1,(total+page_size-1)//page_size)
            page=min(page,pages)
            rows=conn.execute(sql+' ORDER BY p.created_at DESC,p.id DESC LIMIT ? OFFSET ?',
                              (*params,page_size,(page-1)*page_size)).fetchall()
            return {'items': [publication_view(conn, r) for r in rows], 'page': page,
                    'page_size': page_size, 'total': total, 'pages': pages}

    @app.get('/api/campus/publications/{pid}')
    def publication_detail(pid:str,current=Depends(user)):
        with db.connect() as conn:
            row=publication_for(conn,pid,current['id'])
            result=publication_view(conn,row)
            result['history']=[]
            for version in conn.execute('''SELECT version,title,body,created_at
                    FROM campus_publication_versions WHERE publication_id=? ORDER BY version DESC''',(pid,)):
                attachments=[{**dict(f),'download_url':f"/api/campus/publications/{pid}/versions/{version['version']}/attachments/{f['position']}"}
                    for f in conn.execute('''SELECT position,name,kind,sha256,length(content) AS size
                        FROM campus_materials WHERE publication_id=? AND version=? ORDER BY position''',(pid,version['version']))]
                result['history'].append({**dict(version),**version_context(conn,pid,version['version']),
                                          'attachments':attachments,
                                          'publication_policy':publication_policy(conn,pid,version['version'])})
            result['delivery']['errors']=[dict(v) for v in conn.execute('''SELECT error,count(*) AS count
                FROM campus_deliveries WHERE publication_id=? AND state='failed' GROUP BY error''',(pid,))]
            from .campus_policy import delivery_evidence
            result['delivery']['evidence']=delivery_evidence(conn,pid)
            return result

    @app.get('/api/campus/publications/{pid}/versions/{version}/attachments/{position}')
    def publication_attachment(pid:str,version:int,position:int,current=Depends(user)):
        with db.connect() as conn:
            publication_for(conn,pid,current['id'])
            original=conn.execute('SELECT name,content,sha256 FROM campus_materials WHERE publication_id=? AND version=? AND position=?',
                                  (pid,version,position)).fetchone()
            if original is None:raise HTTPException(404,'此版本附件不存在')
            if hashlib.sha256(original['content']).hexdigest()!=original['sha256']:
                raise HTTPException(409,'原件校验未通过，请核对该版本材料')
            return Response(original['content'],media_type='application/octet-stream',headers={
                'Content-Disposition':"attachment; filename*=UTF-8''"+quote(original['name'],safe='')})

    @app.post('/api/campus/publications')
    async def publish(request: Request, current=Depends(user)):
        with db.connect() as conn:
            publisher(conn, current['id'])
        payload, files = await request_materials(request, Publication)
        payload_data=payload.model_dump(exclude={'request_id','audience_review'},exclude_none=True)
        if not payload.reference_only:payload_data.pop('reference_only',None)
        digest = hashlib.sha256(dumps({'payload': payload_data,
            'files': [{'name': f['name'], 'sha256': f['sha256']} for f in files]}).encode()).hexdigest()
        with db.connect(write=True) as conn:
            own = publisher(conn, current['id'], payload)
            previous = conn.execute('SELECT * FROM campus_publications WHERE publisher_id=? AND request_id=?', (current['id'], payload.request_id)).fetchone()
            if previous:
                if previous['request_digest'] != digest:
                    raise HTTPException(409, '该提交编号已用于不同内容，请检查已发布记录')
                return publication_view(conn, previous)
            selected = recipients(conn, own['college_id'], payload)
            require_audience_review(conn,current['id'],own['college_id'],payload,selected,payload.audience_review)
            if len(selected)>MAX_RECIPIENTS:
                raise HTTPException(413,'本次接收人数超过1000人，请按年级或班级分批发布')
            if payload.draft_id:
                from .campus_drafts import draft_files
                draft=conn.execute('SELECT * FROM campus_drafts WHERE user_id=? AND id=? AND college_id=?',
                    (current['id'],payload.draft_id,own['college_id'])).fetchone()
                if draft is None or draft['version']!=payload.draft_version:
                    raise HTTPException(409,'发布草稿已变化，请重新核对已保存的内容和附件')
                saved_files=draft_files(conn,current['id'],payload.draft_id)
                known={(f['name'],f['sha256']) for f in saved_files}
                files=saved_files+[f for f in files if (f['name'],f['sha256']) not in known]
            pid, now = ident(), int(time.time())
            conn.execute('INSERT INTO campus_publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (pid, own['college_id'], current['id'], current['display_name'], payload.request_id, digest,
                 payload.audience, payload.grade, payload.class_name, 'published', 1, now, now))
            sources = save_version(conn, pid, 1, payload.title, payload.body, current['id'], files,
                                   replace_draft=payload.draft_id,policy=policy_changes(payload))
            for member in selected:
                conn.execute("INSERT INTO campus_deliveries(publication_id,user_id,state,updated_at) VALUES(?,?,'pending',?)", (pid, member['user_id'], now))
            row = dict(conn.execute('SELECT * FROM campus_publications WHERE id=?', (pid,)).fetchone())
            queue_delivery(conn,row,current['id'])
            if payload.draft_id:
                conn.execute('DELETE FROM campus_drafts WHERE user_id=? AND id=?',(current['id'],payload.draft_id))
            audit(conn, own['college_id'], current['id'], None, 'publish', {'publication_id': pid,'version':1,
                  'audience': payload.audience, 'grade': payload.grade, 'class_name': payload.class_name})
        await run_in_threadpool(drain_publications,db,publication_id=pid)
        with db.connect() as conn:
            result = publication_view(conn, row)
            result['delivery']['students'] = sum(m['role'] == 'student' for m in selected)
            return result

    @app.post('/api/campus/publications/{pid}/correct')
    async def correct(pid: str, request: Request, current=Depends(user)):
        with db.connect() as conn:
            publication_for(conn, pid, current['id'])
        payload, new_files = await request_materials(request, Correction)
        with db.connect(write=True) as conn:
            row = publication_for(conn, pid, current['id'])
            if row['state'] != 'published' or row['version'] != payload.version:
                raise HTTPException(409, '通知已变更或撤回，请刷新后核对')
            files = (material_sources(conn, pid, row['version']) if payload.keep_attachments else []) + new_files
            version = row['version'] + 1
            sources = save_version(conn, pid, version, payload.title, payload.body, current['id'], files,policy=policy_changes(payload))
            conn.execute('UPDATE campus_publications SET version=?,updated_at=? WHERE id=?', (version, int(time.time()), pid))
            row = dict(conn.execute('SELECT * FROM campus_publications WHERE id=?', (pid,)).fetchone())
            queue_delivery(conn,row,current['id'])
            audit(conn, row['college_id'], current['id'], None, 'correct', {'publication_id': pid, 'version': version})
        await run_in_threadpool(drain_publications,db,publication_id=pid)
        with db.connect() as conn:return publication_view(conn,row)

    @app.post('/api/campus/publications/{pid}/withdraw')
    def withdraw(pid: str, payload: Withdrawal, current=Depends(user)):
        with db.connect(write=True) as conn:
            row = publication_for(conn, pid, current['id'])
            if row['state'] != 'published' or row['version'] != payload.version:
                raise HTTPException(409, '通知已变更或撤回，请刷新后核对')
            latest = conn.execute('SELECT title FROM campus_publication_versions WHERE publication_id=? AND version=?', (pid, row['version'])).fetchone()
            version = row['version'] + 1
            title = ('【已撤回】' + latest['title'])[:160]
            sources = save_version(conn, pid, version, title, '发布方撤回说明：' + payload.reason, current['id'], [])
            conn.execute("UPDATE campus_publications SET state='withdrawn',version=?,updated_at=? WHERE id=?", (version, int(time.time()), pid))
            row = dict(conn.execute('SELECT * FROM campus_publications WHERE id=?', (pid,)).fetchone())
            queue_delivery(conn,row,current['id'])
            audit(conn, row['college_id'], current['id'], None, 'withdraw', {'publication_id': pid, 'version': version,'reason':payload.reason})
        drain_publications(db,publication_id=pid)
        with db.connect() as conn:return publication_view(conn,row)

    @app.post('/api/campus/publications/{pid}/retry')
    def retry(pid: str, payload:DeliveryRetry|None=None, current=Depends(user)):
        with db.connect(write=True) as conn:
            row = publication_for(conn, pid, current['id'])
            if not conn.execute('SELECT 1 FROM campus_dispatch_authority WHERE publication_id=?',(pid,)).fetchone():
                audience=audience_from(row)
                require_audience_review(conn,current['id'],row['college_id'],audience,
                    recipients(conn,row['college_id'],audience),payload.audience_review if payload else None)
            latest = conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?', (pid, row['version'])).fetchone()
            sources = [text_source(latest['title'] + '\n\n' + latest['body'], '学院通知正文'), *material_sources(conn, pid, row['version'])]
            queue_delivery(conn,row,current['id'],retry_only=True)
        drain_publications(db,publication_id=pid)
        with db.connect() as conn:return publication_view(conn,row)

    @app.post('/api/campus/publications/{pid}/restore')
    async def restore(pid:str,request:Request,current=Depends(user)):
        with db.connect() as conn:publication_for(conn,pid,current['id'])
        payload,new_files=await request_materials(request,Restoration)
        with db.connect(write=True) as conn:
            row=publication_for(conn,pid,current['id'])
            if row['state']!='withdrawn' or row['version']!=payload.version:
                raise HTTPException(409,'通知不在该撤回版本，请核对当前状态后再恢复')
            files=(material_sources(conn,pid,row['version']-1) if payload.keep_attachments else [])+new_files
            version=row['version']+1
            body=payload.body
            save_version(conn,pid,version,payload.title,body,current['id'],files,policy=policy_changes(payload))
            conn.execute("UPDATE campus_publications SET state='published',version=?,updated_at=? WHERE id=?",
                         (version,int(time.time()),pid))
            row=dict(conn.execute('SELECT * FROM campus_publications WHERE id=?',(pid,)).fetchone())
            queue_delivery(conn,row,current['id'])
            audit(conn,row['college_id'],current['id'],None,'restore',
                  {'publication_id':pid,'version':version,'reason':payload.reason})
        await run_in_threadpool(drain_publications,db,publication_id=pid)
        with db.connect() as conn:return publication_view(conn,row)

    @app.post('/api/campus/publications/{pid}/rollback')
    def rollback(pid:str,payload:Rollback,current=Depends(user)):
        with db.connect(write=True) as conn:
            row=publication_for(conn,pid,current['id'])
            if row['state']!='published' or row['version']!=payload.version:
                raise HTTPException(409,'当前发布状态或版本已变化，请重新核对')
            if payload.target_version>=row['version'] or version_kind(conn,pid,payload.target_version) not in {'publish','correct','restore','rollback'}:
                raise HTTPException(422,'请选择更早的正式内容版本；撤回或恢复须走对应流程')
            old=conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?',
                             (pid,payload.target_version)).fetchone()
            if old is None:raise HTTPException(404,'目标版本不存在')
            version=row['version']+1
            body=old['body']
            save_version(conn,pid,version,old['title'],body,current['id'],material_sources(conn,pid,payload.target_version),
                         policy=stored_policy(conn,pid,payload.target_version))
            conn.execute('UPDATE campus_publications SET version=?,updated_at=? WHERE id=?',(version,int(time.time()),pid))
            row=dict(conn.execute('SELECT * FROM campus_publications WHERE id=?',(pid,)).fetchone())
            queue_delivery(conn,row,current['id'])
            audit(conn,row['college_id'],current['id'],None,'rollback',{'publication_id':pid,'version':version,
                  'target_version':payload.target_version,'reason':payload.reason})
        drain_publications(db,publication_id=pid)
        with db.connect() as conn:return publication_view(conn,row)

    @app.post('/api/campus/publications/{pid}/deliver-new')
    def deliver_new(pid: str, payload:Backfill, current=Depends(user)):
        with db.connect(write=True) as conn:
            row = publication_for(conn, pid, current['id'])
            if row['state'] != 'published':
                raise HTTPException(409, '撤回的通知不能补发')
            if row['version']!=payload.version:
                raise HTTPException(409,'待补发的正式版本已变化，请核对新版本、有效期和接收范围')
            audience=audience_from(row)
            selected = recipients(conn, row['college_id'], audience)
            require_audience_review(conn,current['id'],row['college_id'],audience,selected,payload.audience_review)
            policy=publication_policy(conn,pid,row['version'])
            reference=policy['external_notifications']=='suppressed'
            if reference and not payload.reference_confirmed:
                raise HTTPException(409,'该版本仅供参考或已超过发布方标注有效期；请明确核对为历史参考后补发，系统不会外发催办')
            if len(selected)>MAX_RECIPIENTS:
                raise HTTPException(413,'当前范围超过1000名成员，请先分批核对发布范围')
            now, added = int(time.time()), 0
            for member in selected:
                added += conn.execute("INSERT OR IGNORE INTO campus_deliveries(publication_id,user_id,state,updated_at) VALUES(?,?,'pending',?)",
                                      (pid, member['user_id'], now)).rowcount
            latest = conn.execute('SELECT title,body FROM campus_publication_versions WHERE publication_id=? AND version=?', (pid, row['version'])).fetchone()
            sources = [text_source(latest['title'] + '\n\n' + latest['body'], '学院通知正文'), *material_sources(conn, pid, row['version'])]
            queue_delivery(conn,row,current['id'])
            audit(conn, row['college_id'], current['id'], None, 'deliver_new', {'publication_id': pid, 'added': added,
                  'delivered_version':row['version'],'historical_reference':reference})
        drain_publications(db,publication_id=pid)
        with db.connect() as conn:
            result = publication_view(conn, row)
            result['delivery']['added'] = added
            return result
