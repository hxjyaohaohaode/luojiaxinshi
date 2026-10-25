"""Personal application files and immutable, self-reported submission snapshots.

These files are deliberately not notice sources and are never AI evidence.
Submission writes run inside the existing workflow transaction.
"""
import hashlib
import json
import re
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from .usage_limits import limits_for, check_storage
from .db import audit, dumps, ident
from .documents import MAX_FILE, file_source
from .models import Strict, TaskData, safe_url
from .security import rate_limit

TABLES={'task_materials','task_material_versions','task_material_receipts','task_submission_records'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS task_materials(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 requirement TEXT NOT NULL, version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS task_materials_task ON task_materials(task_id);
CREATE TABLE IF NOT EXISTS task_material_versions(
 material_id TEXT NOT NULL REFERENCES task_materials(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, content BLOB NOT NULL,
 sha256 TEXT NOT NULL, parse_status TEXT NOT NULL, warning TEXT NOT NULL, sections TEXT NOT NULL,
 created_at INTEGER NOT NULL, PRIMARY KEY(material_id,version));
CREATE TABLE IF NOT EXISTS task_material_receipts(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 material_id TEXT NOT NULL REFERENCES task_materials(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(user_id,request_id));
CREATE TABLE IF NOT EXISTS task_submission_records(
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, request_digest TEXT NOT NULL,
 task_version INTEGER NOT NULL, workflow_version INTEGER NOT NULL,
 data TEXT NOT NULL, created_at INTEGER NOT NULL, UNIQUE(user_id,request_id));
CREATE INDEX IF NOT EXISTS task_submission_records_task ON task_submission_records(task_id,created_at);
INSERT OR IGNORE INTO meta VALUES('task_material_schema_version','1');
"""
MAX_MATERIALS=1000000


class SubmittedFile(Strict):
    material_id: str = Field(min_length=1,max_length=40)
    version: int = Field(ge=1)


class PersonalSubmission(Strict):
    request_id: str = Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    channel: str = Field(min_length=2,max_length=200)
    submitted_at: str
    receipt: str = Field(min_length=2,max_length=2000)
    receipt_url: str = Field(default='',max_length=2000)
    note: str = Field(default='',max_length=2000)
    files: list[SubmittedFile] = Field(default_factory=list,max_length=MAX_MATERIALS)
    external_requirements: list[str] = Field(default_factory=list,max_length=30)
    confirmed: bool = Field(default=False,strict=True)

    @field_validator('submitted_at')
    @classmethod
    def valid_time(cls,value):
        value=TaskData.valid_datetime(value)
        if datetime.fromisoformat(value)>datetime.now(timezone.utc):
            raise ValueError('实际提交时间不能在未来')
        return value

    @field_validator('receipt_url')
    @classmethod
    def valid_url(cls,value):return safe_url(value)


def personal_material_bytes(conn,uid):
    return conn.execute('SELECT COALESCE(SUM(length(v.content)),0) FROM task_material_versions v JOIN task_materials m ON m.id=v.material_id WHERE m.user_id=?',(uid,)).fetchone()[0]


def total_stored_bytes(conn,uid):
    return (personal_material_bytes(conn,uid)
        +conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?',(uid,)).fetchone()[0]
        +conn.execute('SELECT COALESCE(SUM(length(s.content)),0) FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?',(uid,)).fetchone()[0])


def version_info(row,tid,include_preview=True):
    item={key:row[key] for key in ('material_id','version','name','kind','sha256','parse_status','warning','created_at')}
    item['size']=row['size']
    item['download_url']=f"/api/tasks/{tid}/materials/{row['material_id']}/versions/{row['version']}/download"
    item['image_preview']=row['kind'] in {'png','jpg','jpeg','webp'} and row['parse_status']!='failed'
    if include_preview:
        sections=json.loads(row['sections'])
        item['preview']='\n'.join(section['text'] for section in sections)[:1200]
    return item


def material_bundle(conn,task,uid):
    requirements=list(dict.fromkeys(json.loads(task['data'])['materials'])) if isinstance(task['data'],str) else list(dict.fromkeys(task['data']['materials']))
    materials=[]
    for row in conn.execute('SELECT * FROM task_materials WHERE task_id=? AND user_id=? ORDER BY created_at,id',(task['id'],uid)):
        item=dict(row);item['matches_requirement']=bool(item['requirement'] and item['requirement'] in requirements)
        item['versions']=[version_info(v,task['id']) for v in conn.execute('SELECT *,length(content) AS size FROM task_material_versions WHERE material_id=? ORDER BY version DESC',(row['id'],))]
        materials.append(item)
    submissions=[]
    for row in conn.execute('SELECT * FROM task_submission_records WHERE task_id=? AND user_id=? ORDER BY created_at DESC,rowid DESC',(task['id'],uid)):
        record=dict(row);record['data']=json.loads(record['data']);record.pop('request_digest');submissions.append(record)
    return {'task_id':task['id'],'task_version':task['version'],'requirements':requirements,'materials':materials,'submissions':submissions,
        'limits':{'file_bytes':MAX_FILE,'material_count':limits_for(conn).materials_per_task,'versions_per_material':limits_for(conn).versions_per_material},
        'authority':'本人材料与提交记录，未向学校发送，未经发布方核验'}


def export_task_materials(conn,uid):
    return {'includes_file_bytes':False,'restore_supported':False,
        'note':'本人材料原件不包含在个人 JSON 中，请另行下载；这些元数据和提交快照供留档，当前 JSON 导入不恢复它们。完整恢复请使用数据库备份。',
        'tasks':[material_bundle(conn,dict(t),uid) for t in conn.execute('SELECT * FROM tasks WHERE user_id=? AND (id IN (SELECT task_id FROM task_materials) OR id IN (SELECT task_id FROM task_submission_records)) ORDER BY created_at',(uid,))]}


def submission_digest(payload):
    return hashlib.sha256(dumps(payload.model_dump()).encode()).hexdigest()


def replay_submission(conn,uid,tid,payload):
    if not payload.submission:return False
    row=conn.execute('SELECT task_id,request_digest FROM task_submission_records WHERE user_id=? AND request_id=?',(uid,payload.submission.request_id)).fetchone()
    if not row:return False
    if row['task_id']!=tid or row['request_digest']!=submission_digest(payload):
        raise HTTPException(409,'本次提交标识已用于其他内容，请刷新后核对')
    return True


def prepare_submission(conn,task,uid,entry,data):
    """Prepare a snapshot; workflow validation still runs before persistence."""
    if len(entry.files)>limits_for(conn).materials_per_task:raise HTTPException(422,'本次提交文件超过每事项材料容量，请核对文件选择')
    if not entry.confirmed:raise HTTPException(422,'请确认这是本人实际提交的记录')
    if data['execution_mode']!='submission':raise HTTPException(422,'仅材料申报事项可记录提交；其他事项请保存实际办理进度')
    if task['data']['scope']!='personal':raise HTTPException(422,'请先核实这是由本人办理的事项')
    if task['status']=='cancelled':raise HTTPException(422,'事项已取消，不能新增提交记录')
    if task['status']=='done':raise HTTPException(422,'事项已标记完成；需要再次提交时，请先恢复为待完成')
    requirements=list(dict.fromkeys(task['data']['materials']))
    external=list(dict.fromkeys(entry.external_requirements))
    if any(value not in requirements for value in external):raise HTTPException(422,'材料要求已变化，请刷新后核对外部提交材料')
    if len({f.material_id for f in entry.files})!=len(entry.files):raise HTTPException(422,'同一份材料只能选择一个提交版本')
    files=[];covered=set(external)
    for chosen in entry.files:
        row=conn.execute('SELECT v.*,length(v.content) AS size,m.requirement FROM task_material_versions v JOIN task_materials m ON m.id=v.material_id WHERE m.id=? AND v.version=? AND m.task_id=? AND m.user_id=?',(chosen.material_id,chosen.version,task['id'],uid)).fetchone()
        if row is None:raise HTTPException(422,'所选材料版本不存在或不属于当前事项')
        item=version_info(row,task['id'],False);item['requirement']=row['requirement'];files.append(item)
        if row['requirement'] in requirements:covered.add(row['requirement'])
    missing=[value for value in requirements if value not in covered]
    if missing:raise HTTPException(422,'请为以下材料选择本次文件，或明确记录已通过外部渠道提交：'+'、'.join(missing))
    if len(conn.execute('SELECT id FROM task_submission_records WHERE task_id=?',(task['id'],)).fetchall())>=limits_for(conn).submissions_per_task:
        raise HTTPException(413,f'每个事项最多保留 {limits_for(conn).submissions_per_task} 次提交记录')
    # Actual submission is distinct from completion or institutional acceptance.
    normalized={**data,'stage':'submitted','prepared_materials':requirements,'receipt':entry.receipt,'receipt_url':entry.receipt_url}
    snapshot={'authority':'self_reported','channel':entry.channel,'submitted_at':entry.submitted_at,'receipt':entry.receipt,
        'receipt_url':entry.receipt_url,'note':entry.note,'files':files,'external_requirements':external,
        'requirements':requirements,'task_title':task['data']['title'],'submission_requirement':task['data'].get('submission','')}
    return normalized,snapshot


def store_submission(conn,task,uid,payload,snapshot,workflow_version):
    sid=ident();now=int(time.time())
    conn.execute('INSERT INTO task_submission_records VALUES(?,?,?,?,?,?,?,?,?)',
        (sid,task['id'],uid,payload.submission.request_id,submission_digest(payload),task['version'],workflow_version,dumps(snapshot),now))
    audit(conn,uid,task['notice_id'],'personal_submission_recorded',after={'submission_id':sid,'workflow_version':workflow_version,'authority':'self_reported','files':snapshot['files'],'channel':snapshot['channel'],'submitted_at':snapshot['submitted_at']},task_id=task['id'])
    return sid


def install_task_materials(app,db,settings,user,own_task,expect_version):
    @app.get('/api/tasks/{tid}/materials')
    def read_materials(tid:str,current=Depends(user)):
        with db.connect() as conn:return material_bundle(conn,own_task(conn,tid,current['id']),current['id'])

    @app.get('/api/tasks/{tid}/materials/package')
    def download_package(tid:str,submission_id:str='',current=Depends(user)):
        rate_limit(db,'personal-package:'+current['id'],20,3600)
        package=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
        try:
            with db.connect() as conn:
                task=own_task(conn,tid,current['id']);bundle=material_bundle(conn,task,current['id'])
                if submission_id:
                    selected=next((r for r in bundle['submissions'] if r['id']==submission_id),None)
                    if not selected:raise HTTPException(404,'本次提交记录不存在')
                    files=selected['data']['files'];heading='本人提交记录：'+selected['data']['channel']
                    details=['实际提交时间：'+selected['data']['submitted_at'],'提交情况：'+selected['data']['receipt'],
                             '另在外部提交：'+'、'.join(selected['data']['external_requirements'])]
                else:
                    files=[{**m['versions'][0],'requirement':m['requirement']} for m in bundle['materials']]
                    heading='办理材料当前版本';details=['正式要求：'+'、'.join(bundle['requirements'])]
                if not files and not submission_id:raise HTTPException(422,'尚未保存本人办理材料')
                with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as archive:
                    manifest=[heading,'此文件包为本人保存的材料与记录，系统未向学校提交，也不代表学校已受理。',*details,'']
                    for index,item in enumerate(files,1):
                        row=conn.execute('''SELECT v.content FROM task_material_versions v JOIN task_materials m ON m.id=v.material_id
                            WHERE m.id=? AND m.task_id=? AND m.user_id=? AND v.version=?''',
                            (item['material_id'],tid,current['id'],item['version'])).fetchone()
                        if row is None:raise HTTPException(409,'材料版本已不可用，文件包未生成')
                        clean=lambda value:re.sub(r'[\\/\x00-\x1f<>:"|?*]','_',value).strip(' .')[:120] or '材料'
                        path=f"{index:02d}-{clean(item.get('requirement') or '补充材料')}/{clean(item['name'])}"
                        archive.writestr(path,row['content'])
                        manifest.append(f"{path} · 版本 {item['version']} · SHA256 {item['sha256']}")
                    archive.writestr('材料说明.txt','\n'.join(manifest).encode('utf-8-sig'))
            package.seek(0)
        except BaseException:
            package.close();raise
        def content():
            try:
                while chunk:=package.read(65536):yield chunk
            finally:package.close()
        return StreamingResponse(content(),media_type='application/zip',headers={
            'Content-Disposition':"attachment; filename*=UTF-8''"+quote('本人提交材料包.zip' if submission_id else '办理材料包.zip',safe='')})

    @app.post('/api/tasks/{tid}/materials')
    async def upload_material(tid:str,request:Request,current=Depends(user)):
        with db.connect() as conn:own_task(conn,tid,current['id'])
        rate_limit(db,'personal-material:'+current['id'],60,3600)
        form=await request.form(max_files=1,max_fields=7,max_part_size=10000)
        try:
            if set(form.keys())-{'file','requirement','task_version','material_id','expected_version','request_id'}:
                raise HTTPException(422,'包含不支持的材料字段')
            try:
                task_version=int(form.get('task_version','0'));expected=int(form.get('expected_version','0'))
            except (ValueError,TypeError):raise HTTPException(422,'请刷新后重试上传') from None
            requirement=str(form.get('requirement','')).strip();mid=str(form.get('material_id','')).strip();rid=str(form.get('request_id','')).strip()
            if len(requirement)>500 or len(mid)>40 or not 16<=len(rid)<=80 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in rid):
                raise HTTPException(422,'材料要求或上传标识无效')
            upload=form.get('file')
            if not hasattr(upload,'read'):raise HTTPException(422,'请选择一份本人准备的材料')
            content=await upload.read(MAX_FILE+1)
            if not content or len(content)>MAX_FILE:raise HTTPException(413,'每份材料须大于 0 字节且不超过 5 MB')
            try:source=await run_in_threadpool(file_source,upload.filename or '',content)
            except ValueError as exc:raise HTTPException(422,str(exc)) from None
        finally:await form.close()
        digest=hashlib.sha256(dumps({'sha256':source['sha256'],'name':source['name'],'requirement':requirement,'material_id':mid,'expected_version':expected,'task_version':task_version}).encode()).hexdigest()
        with db.connect(write=True) as conn:
            task=own_task(conn,tid,current['id'])
            previous=conn.execute('SELECT * FROM task_material_receipts WHERE user_id=? AND request_id=?',(current['id'],rid)).fetchone()
            if previous:
                if previous['task_id']!=tid or previous['digest']!=digest:raise HTTPException(409,'上传标识对应的文件已变化，请重新选择文件')
                return material_bundle(conn,task,current['id'])
            expect_version(task,task_version)
            if task['status']=='cancelled':raise HTTPException(422,'事项已取消，不能上传新材料')
            requirements=json.loads(task['data'])['materials']
            if requirement and requirement not in requirements:raise HTTPException(422,'材料要求已变化，请选择当前要求或其他补充材料')
            now=int(time.time())
            if mid:
                old=conn.execute('SELECT * FROM task_materials WHERE id=? AND task_id=? AND user_id=?',(mid,tid,current['id'])).fetchone()
                if old is None:raise HTTPException(404,'本人材料不存在')
                if old['version']!=expected:raise HTTPException(409,'材料已有更新版本，请刷新后核对')
                if old['requirement']!=requirement:raise HTTPException(422,'新版本必须保留原材料归属；要求变化时请另建材料')
                if old['version']>=limits_for(conn).versions_per_material:raise HTTPException(413,f'每份材料最多保留 {limits_for(conn).versions_per_material} 个版本，请另建一份材料')
                current_file=conn.execute('SELECT sha256 FROM task_material_versions WHERE material_id=? AND version=?',(mid,expected)).fetchone()
                if current_file['sha256']==source['sha256']:raise HTTPException(409,'文件内容与当前版本相同，无需再次上传')
                version=expected+1
            else:
                if expected:raise HTTPException(422,'新材料无需指定旧版本')
                if conn.execute('SELECT COUNT(*) FROM task_materials WHERE task_id=?',(tid,)).fetchone()[0]>=limits_for(conn).materials_per_task:raise HTTPException(413,f'每个事项最多保留 {limits_for(conn).materials_per_task} 份本人材料')
                mid=ident();version=1
            check_storage(conn,current['id'],len(content))
            if version==1:conn.execute('INSERT INTO task_materials VALUES(?,?,?,?,?,?,?)',(mid,tid,current['id'],requirement,version,now,now))
            else:conn.execute('UPDATE task_materials SET version=?,updated_at=? WHERE id=?',(version,now,mid))
            conn.execute('INSERT INTO task_material_versions VALUES(?,?,?,?,?,?,?,?,?,?)',(mid,version,source['name'],source['kind'],content,source['sha256'],source['status'],source['warning'],dumps(source['sections']),now))
            conn.execute('INSERT INTO task_material_receipts VALUES(?,?,?,?,?,?)',(current['id'],rid,tid,mid,version,digest))
            audit(conn,current['id'],task['notice_id'],'personal_material_uploaded',after={'material_id':mid,'version':version,'name':source['name'],'requirement':requirement},task_id=tid)
            return material_bundle(conn,task,current['id'])

    @app.get('/api/tasks/{tid}/materials/{mid}/versions/{version}/download')
    def download_material(tid:str,mid:str,version:int,preview:bool=False,current=Depends(user)):
        with db.connect() as conn:
            own_task(conn,tid,current['id'])
            row=conn.execute('SELECT v.* FROM task_material_versions v JOIN task_materials m ON m.id=v.material_id WHERE m.id=? AND m.task_id=? AND m.user_id=? AND v.version=?',(mid,tid,current['id'],version)).fetchone()
            if row is None:raise HTTPException(404,'材料版本不存在')
            mime={'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp'}
            inline=preview and row['kind'] in mime and row['parse_status']!='failed'
            return Response(row['content'],media_type=mime[row['kind']] if inline else 'application/octet-stream',headers={'Content-Disposition':('inline' if inline else 'attachment')+"; filename*=UTF-8''"+quote(row['name'],safe='')})
