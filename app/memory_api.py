"""Authenticated memory management, review, history and portable editing."""
import json
import re
import time

from fastapi import Depends, HTTPException, Query, Response
from pydantic import Field

from .db import dumps
from .models import Strict, Version
from .memory import Memory, Project, context_for, own
from .memory_policy import catalog, effective, rows_for, save_policy, scope_key
from .memory_store import (MAX_MEMORIES, decorate, insert_memory, invalidate_dependents,
                           record_revision, settings_for, usable_derived, export_archive, digest)
from .memory_learning import MemoryAction, apply_actions, drain_jobs, organize


class SettingsUpdate(Strict):
    mode: str = Field(pattern='^(auto|review|manual|off)$')
    auto_organize: bool = True
    learn_tasks: bool = True
    version: int = Field(ge=0)


class ReviewAction(Version):
    accept: bool


class RestoreAction(Version):
    revision: int = Field(ge=1)


class WorkingUpdate(Strict):
    version: int = Field(ge=0)
    content: str = Field(max_length=4000)
    locked: bool = True


class AgentActions(Version):
    source_message_id: str = Field(min_length=1, max_length=40)
    actions: list[MemoryAction] = Field(max_length=8)


class ImportMemory(Strict):
    text: str = Field(min_length=1, max_length=20000000)
    format: str = Field(pattern='^(json|markdown)$')


def item_for(conn, uid, mid):
    own(conn, 'personal_memories', mid, uid)
    items = catalog(decorate(conn,rows_for(conn,uid,[mid])))
    _, invalid = usable_derived(conn, [item for item in items if item['state'] == 'active'])
    item = next(item for item in items if item['id'] == mid)
    if item['id'] in invalid and item['state'] == 'active':
        item['state'] = 'source_changed'
    return item


def install(app, db, user):
    from .memory_lifecycle_api import install as install_lifecycle
    install_lifecycle(app,db,user)
    from .memory_reliability_api import install as install_reliability
    install_reliability(app,db,user)
    from .memory_assist import install as install_assist
    install_assist(app,db,user)
    @app.get('/api/memory/settings')
    def get_settings(current=Depends(user)):
        with db.connect() as conn:
            return settings_for(conn, current['id'])

    @app.put('/api/memory/settings')
    def set_settings(payload: SettingsUpdate, current=Depends(user)):
        with db.connect(write=True) as conn:
            old = settings_for(conn, current['id'])
            if old['version'] != payload.version:
                raise HTTPException(409, '记忆设置已变化，请刷新后重试')
            conn.execute('''INSERT INTO memory_settings VALUES(?,?,?,?,?,?) ON CONFLICT(user_id)
                DO UPDATE SET mode=excluded.mode,auto_organize=excluded.auto_organize,
                learn_tasks=excluded.learn_tasks,version=excluded.version,updated_at=excluded.updated_at''',
                (current['id'], payload.mode, int(payload.auto_organize), int(payload.learn_tasks), old['version']+1, int(time.time())))
            if payload.mode in ('auto','review') and old['mode']!=payload.mode:
                from .memory_resources import queue_existing
                queue_existing(conn,current['id'])
            return settings_for(conn, current['id'])

    @app.get('/api/memory/items/{mid}')
    def detail(mid: str, current=Depends(user)):
        with db.connect() as conn:
            item = item_for(conn, current['id'], mid)
            item['evidence'] = [dict(r) for r in conn.execute('''SELECT e.*,
                CASE WHEN c.user_id=? THEN msg.conversation_id END AS conversation_id,
                CASE WHEN e.source_kind='message' THEN CASE WHEN c.user_id=? THEN 'available' ELSE 'missing' END
                     WHEN task.id IS NULL THEN 'missing' WHEN task.version<>e.source_version THEN 'changed' ELSE 'available' END source_status
                FROM memory_evidence e LEFT JOIN conversation_messages msg ON e.source_kind='message' AND msg.id=e.source_id
                LEFT JOIN conversations c ON c.id=msg.conversation_id
                LEFT JOIN tasks task ON e.source_kind='task' AND task.id=e.source_id AND task.user_id=?
                WHERE e.memory_id=? ORDER BY e.created_at,e.source_kind,e.source_id''',(current['id'],current['id'],current['id'],mid))]
            from .memory_resources import source_for
            binding=conn.execute('SELECT * FROM memory_resource_sources WHERE memory_id=?',(mid,)).fetchone()
            for entry in item['evidence']:
                if not entry['source_kind'].startswith('resource_'):continue
                source=source_for(conn,current['id'],entry['source_kind'],entry['source_id'])
                entry['source_status']='missing' if not source or not source['available'] else 'available' if binding and binding['fingerprint']==source['fingerprint'] else 'changed'
                entry['source_title']=source['title'] if source else ''
                entry['conversation_id']=source.get('conversation_id') if source else None
                entry['notice_id']=source.get('notice_id') if source else None
            item['revisions'] = [{**dict(r), 'snapshot': json.loads(r['snapshot'])} for r in conn.execute(
                'SELECT version,snapshot,actor,created_at FROM memory_revisions WHERE memory_id=? ORDER BY version DESC', (mid,))]
            item['links'] = [dict(r) for r in conn.execute('''SELECT l.*,m.content,m.kind FROM memory_links l
                JOIN personal_memories m ON m.id=l.parent_id WHERE l.child_id=? AND m.user_id=?''', (mid, current['id']))]
            from .memory_reliability import source_current
            parents={row['id']:row for row in rows_for(conn,current['id'],[link['parent_id'] for link in item['links']])}
            for link in item['links']:
                parent=parents[link['parent_id']]
                link['current_version']=parent['version'];link['source_current']=source_current(conn,parent,link['parent_version'])
                revision=conn.execute('SELECT snapshot FROM memory_revisions WHERE memory_id=? AND version=?',(link['parent_id'],link['parent_version'])).fetchone()
                if revision:link['content']=json.loads(revision['snapshot'])['content']
                elif parent['version']!=link['parent_version']:link['content']='[当时的来源版本已不可用]'
            imported = conn.execute('SELECT payload FROM memory_import_provenance WHERE memory_id=?', (mid,)).fetchone()
            item['imported_provenance'] = json.loads(imported['payload']) if imported else None
            return item

    @app.post('/api/memory/items/{mid}/source-sync')
    def sync_source(mid:str,payload:Version,current=Depends(user)):
        from .memory_resources import source_for,excerpt
        from .memory_autonomy import replace_content
        with db.connect(write=True) as conn:
            item=item_for(conn,current['id'],mid)
            if item['version']!=payload.version:raise HTTPException(409,'记忆已变化，请重新载入后同步')
            binding=conn.execute('SELECT * FROM memory_resource_sources WHERE memory_id=?',(mid,)).fetchone()
            if not binding or binding['source_kind']=='resource_task':raise HTTPException(422,'这条记忆不是资料索引')
            source=source_for(conn,current['id'],binding['source_kind'],binding['source_id'])
            if not source or not source['available']:raise HTTPException(409,'原资料当前不可用，请先核对来源')
            content=excerpt(source,binding['source_kind'])
            conn.execute('UPDATE memory_details SET locked=0 WHERE memory_id=?',(mid,))
            replace_content(conn,current['id'],item,content,'summary',None,'','source-sync')
            conn.execute('UPDATE memory_resource_sources SET fingerprint=? WHERE memory_id=?',(source['fingerprint'],mid))
            conn.execute('UPDATE memory_evidence SET quote=?,created_at=? WHERE memory_id=? AND source_kind=? AND source_id=?',(content,int(time.time()),mid,binding['source_kind'],binding['source_id']))
            return item_for(conn,current['id'],mid)

    @app.post('/api/memory/items/{mid}/review')
    def review(mid: str, payload: ReviewAction, current=Depends(user)):
        with db.connect(write=True) as conn:
            item = item_for(conn, current['id'], mid)
            if item['version'] != payload.version or item['review_status'] != 'pending':
                raise HTTPException(409, '这条记忆已处理或发生变化，请刷新后核对')
            if not payload.accept:
                from .memory_store import forget_memory
                forget_memory(conn,current['id'],item)
                return {'rejected': True}
            active_items = [row for row in catalog(rows_for(conn, current['id'])) if row['state'] == 'active']
            active_items, _ = usable_derived(conn, active_items)
            active_ids = {row['id'] for row in active_items}
            for link in conn.execute('SELECT * FROM memory_links WHERE child_id=?', (mid,)).fetchall():
                parent = own(conn, 'personal_memories', link['parent_id'], current['id'])
                from .memory_reliability import source_current
                if (not source_current(conn,parent,link['parent_version']) or not parent['active']
                        or link['relation'] == 'derived_from' and parent['id'] not in active_ids):
                    raise HTTPException(409, '提议依据已变化，请重新整理后核对')
                if link['relation'] == 'supersedes':
                    conn.execute('UPDATE personal_memories SET active=0,version=version+1,updated_at=? WHERE id=?',
                                 (int(time.time()), parent['id']))
                    record_revision(conn, parent['id'], 'user-replaced')
            _, stale_proposal = usable_derived(conn, [item])
            # A proposed replacement may refer to an outdated original through
            # supersedes; only its own task evidence or derived_from sources constrain it.
            if mid in stale_proposal and not conn.execute("SELECT 1 FROM memory_links WHERE child_id=? AND relation='derived_from'", (mid,)).fetchone():
                raise HTTPException(409, '提议的办理来源又发生变化，请先重新整理')
            conn.execute("UPDATE memory_details SET review_status='accepted',locked=1 WHERE memory_id=?", (mid,))
            conn.execute('UPDATE personal_memories SET active=1,version=version+1,updated_at=? WHERE id=?',
                         (int(time.time()), mid))
            from .memory_lifecycle import set_semantics
            set_semantics(conn,mid,admission='manual')
            record_revision(conn, mid, 'user-approved')
            return item_for(conn, current['id'], mid)

    @app.post('/api/memory/items/{mid}/restore')
    def restore(mid: str, payload: RestoreAction, current=Depends(user)):
        with db.connect(write=True) as conn:
            item = item_for(conn, current['id'], mid)
            if item['version'] != payload.version:
                raise HTTPException(409, '记忆已变化，请刷新后再恢复')
            revision = conn.execute('SELECT snapshot FROM memory_revisions WHERE memory_id=? AND version=?', (mid, payload.revision)).fetchone()
            if not revision:
                raise HTTPException(404, '历史版本不存在')
            old = json.loads(revision['snapshot'])
            if isinstance(old.get('labels'), str):
                old['labels'] = json.loads(old['labels'])
            if old.get('project_id'):
                own(conn, 'memory_projects', old['project_id'], current['id'])
            value = Memory.model_validate({key: old[key] for key in Memory.model_fields if key in old})
            from .memory_reliability import SOURCE_FIELDS
            if any(item.get(field)!=value.model_dump().get(field) for field in SOURCE_FIELDS):invalidate_dependents(conn,mid)
            conn.execute('''UPDATE personal_memories SET scope=?,project_id=?,topic=?,kind=?,content=?,active=?,
                pinned=?,version=version+1,updated_at=? WHERE id=?''',
                (value.scope, value.project_id, value.topic, value.kind, value.content, int(item['active']),
                 int(value.pinned), int(time.time()), mid))
            conn.execute("UPDATE memory_details SET locked=1,review_status='accepted',labels=? WHERE memory_id=?", (dumps(value.labels), mid))
            save_policy(conn, mid, value.model_dump())
            if 'evidence' in old:
                conn.execute('DELETE FROM memory_evidence WHERE memory_id=?',(mid,))
                for entry in old['evidence']:
                    conn.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?)',
                        (mid,entry['source_kind'],entry['source_id'],entry['source_version'],entry['quote'],entry['created_at']))
            if 'links' in old:
                conn.execute('DELETE FROM memory_links WHERE child_id=?',(mid,))
                for link in old['links']:
                    own(conn,'personal_memories',link['parent_id'],current['id'])
                    conn.execute('INSERT INTO memory_links VALUES(?,?,?,?)',
                        (mid,link['parent_id'],link['relation'],link['parent_version']))
            from .memory_lifecycle import set_semantics
            life=old.get('lifecycle') or {}
            cues=life.get('applies_to')
            if isinstance(cues,str):cues=json.loads(cues)
            set_semantics(conn,mid,admission='manual',tier=life.get('tier'),shared=life.get('shared'),applies_to=cues)
            conn.execute('UPDATE memory_semantics SET status=? WHERE memory_id=?',(item['status'],mid))
            record_revision(conn, mid, 'user-restored')
            return item_for(conn, current['id'], mid)

    @app.get('/api/memory/search')
    def search(q: str = Query(min_length=1, max_length=1000), conversation_id: str | None = None,
               current=Depends(user)):
        from .memory import recall
        if conversation_id:
            items, report = recall(db, current['id'], conversation_id, q, {'profile': True, 'memory': True})
            return {'items': items, 'report': report}
        with db.connect() as conn:
            from .memory_search import ranked
            items = [item for item in decorate(conn, catalog(rows_for(conn, current['id']))) if item['state'] == 'active']
            items, invalid = usable_derived(conn, items)
            selected, report = ranked(conn, current['id'], items, q, limit=40, byte_budget=64000)
            return {'items': selected, 'report': {**report, 'invalidated': len(invalid)}}

    @app.post('/api/memory/organize')
    def organize_now(current=Depends(user)):
        jobs = drain_jobs(db, uid=current['id'], limit=100)
        with db.connect(write=True) as conn:
            return {**organize(conn, current['id']), **jobs}

    @app.post('/api/memory/backfill')
    def backfill(current=Depends(user)):
        with db.connect(write=True) as conn:
            if settings_for(conn, current['id'])['mode'] in ('manual', 'off'):
                raise HTTPException(409, '请先选择自动记忆或先核对再保存')
            before = conn.total_changes
            conn.execute('''INSERT INTO memory_jobs(id,user_id,source_kind,source_id,created_at)
                SELECT 'message:'||m.id,c.user_id,'message',m.id,m.created_at
                FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id
                WHERE c.user_id=? AND m.role='user' AND m.status='complete' ORDER BY m.rowid LIMIT 10000
                ON CONFLICT(id) DO UPDATE SET state='queued',error_code='',finished_at=NULL,source_version=0
                WHERE memory_jobs.state<>'queued' ''', (current['id'],))
            conn.execute("UPDATE memory_jobs SET source_version=0 WHERE user_id=? AND source_kind='message' AND state='queued'",(current['id'],))
            queued=conn.execute("SELECT count(*) FROM memory_jobs WHERE user_id=? AND source_kind='message' AND state='queued'",(current['id'],)).fetchone()[0]
            return {'queued': queued, 'note': '按消息形成时的范围整理；缺少原范围的旧片段先暂存，明确范围后再晋升。不会从旧助手回答生成事实。'}

    @app.get('/api/memory/jobs')
    def jobs(current=Depends(user)):
        with db.connect() as conn:
            return {'counts': {r['state']: r['n'] for r in conn.execute(
                'SELECT state,count(*) n FROM memory_jobs WHERE user_id=? GROUP BY state', (current['id'],))},
                'recent': [dict(r) for r in conn.execute('''SELECT source_kind,state,error_code,created_at,finished_at
                    FROM memory_jobs WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 12''', (current['id'],))]}

    @app.post('/api/memory/jobs/retry')
    def retry_jobs(current=Depends(user)):
        with db.connect(write=True) as conn:
            changed = conn.execute("""UPDATE memory_jobs SET state='queued',error_code='',finished_at=NULL
                WHERE user_id=? AND state='failed'""", (current['id'],)).rowcount
            return {'queued': changed}

    @app.get('/api/conversations/{cid}/working-memory')
    def get_working(cid: str, current=Depends(user)):
        with db.connect() as conn:
            own(conn, 'conversations', cid, current['id'])
            from .memory_lifecycle import working_for
            return working_for(conn,cid)

    @app.put('/api/conversations/{cid}/working-memory')
    def set_working(cid: str, payload: WorkingUpdate, current=Depends(user)):
        with db.connect(write=True) as conn:
            chat = own(conn, 'conversations', cid, current['id'])
            if chat['processing_token']:
                raise HTTPException(409, '请等待当前回复结束再修改工作记忆')
            from .memory_lifecycle import working_for,put_working
            old = working_for(conn,cid)
            if old['version'] != payload.version:
                raise HTTPException(409, '工作记忆已变化，请刷新后核对')
            version=put_working(conn,cid,payload.content,payload.locked)
            return {'saved': True, 'version': version}

    @app.get('/api/conversations/{cid}/memory-tools')
    def tools_contract(cid: str, current=Depends(user)):
        with db.connect() as conn:
            own(conn, 'conversations', cid, current['id'])
            return {'schema': MemoryAction.model_json_schema(), 'settings': settings_for(conn, current['id']),
                    'context': context_for(conn, cid), 'owner_source': 'authenticated_session',
                    'operations': ['remember', 'update', 'archive', 'derive', 'checkpoint', 'use', 'forget'],
                    'read': '/api/memory/search', 'detail': '/api/memory/items/{id}',
                    'note': '权限由服务器绑定；修改需要来源原句和当前版本，本人锁定内容进入待核对。'}

    @app.post('/api/conversations/{cid}/memory-actions')
    def agent_actions(cid: str, payload: AgentActions, current=Depends(user)):
        with db.connect(write=True) as conn:
            chat = own(conn, 'conversations', cid, current['id'])
            if chat['version'] != payload.version or chat['processing_token']:
                raise HTTPException(409, '对话正在处理或已变化，请刷新后重试')
            last = conn.execute("SELECT id FROM conversation_messages WHERE conversation_id=? AND role='user' ORDER BY rowid DESC LIMIT 1", (cid,)).fetchone()
            if not last or last['id'] != payload.source_message_id:
                raise HTTPException(409, '记忆操作必须引用最新用户消息')
            return {'results': apply_actions(conn, current['id'], cid, last['id'], [action.model_dump() for action in payload.actions])}

    @app.get('/api/memory/export')
    def export(current=Depends(user)):
        with db.connect() as conn:
            return export_archive(conn, current['id'])

    @app.get('/api/memory/items/{mid}/markdown')
    def markdown(mid: str, current=Depends(user)):
        with db.connect() as conn:
            item = item_for(conn, current['id'], mid)
            header = {key: item[key] for key in ('id', 'version', 'scope', 'project_id', 'topic', 'kind', 'semantic_key', 'valid_from', 'expires_at', 'labels')}
            text = '---\n' + dumps({'format': 'campus-memory-v1', **header}) + '\n---\n' + item['content']
            return Response(text, media_type='text/markdown; charset=utf-8',
                            headers={'Content-Disposition': f'attachment; filename="memory-{mid}.md"'})

    @app.post('/api/memory/import')
    def import_memory(payload: ImportMemory, current=Depends(user)):
        try:
            if payload.format == 'markdown':
                match = re.fullmatch(r'---\r?\n([^\r\n]+)\r?\n---\r?\n([\s\S]*)', payload.text)
                if not match:
                    raise ValueError()
                header = json.loads(match[1])
                if not isinstance(header, dict) or header.get('format') != 'campus-memory-v1' or not header.get('id'):
                    raise ValueError()
                entries = [{**header, 'content': match[2]}]
            else:
                data = json.loads(payload.text)
                from .data_transfer import bounded
                bounded(data,max_nodes=1000000)
                if (not isinstance(data, dict) or data.get('format') != 'campus-memory-v1'
                        or not isinstance(data.get('memories'), list) or len(data['memories']) > MAX_MEMORIES
                        or not isinstance(data.get('projects', []), list) or len(data.get('projects', [])) > 100):
                    raise ValueError()
                entries = data['memories']
            with db.connect(write=True) as conn:
                saved = []
                project_map = {}
                if payload.format == 'json':
                    for raw in data.get('projects', []):
                        if not isinstance(raw, dict) or not isinstance(raw.get('id'), str):
                            raise ValueError()
                        project = Project.model_validate({key: raw[key] for key in Project.model_fields if key in raw})
                        project_id = raw['id'] if conn.execute('SELECT 1 FROM memory_projects WHERE id=? AND user_id=?',
                            (raw['id'], current['id'])).fetchone() else digest(current['id'] + ':' + raw['id'])[:32]
                        if not conn.execute('SELECT 1 FROM memory_projects WHERE id=? AND user_id=?', (project_id, current['id'])).fetchone():
                            if conn.execute('SELECT count(*) FROM memory_projects WHERE user_id=?', (current['id'],)).fetchone()[0] >= 100:
                                raise ValueError()
                            now = int(time.time())
                            conn.execute('INSERT INTO memory_projects VALUES(?,?,?,?,1,?,?)',
                                (project_id, current['id'], project.name, project.description, now, now))
                        project_map[raw['id']] = project_id
                existing = {(scope_key(item), digest(item['content'])): item['id'] for item in rows_for(conn, current['id'])}
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError()
                    fields = {key: entry[key] for key in Memory.model_fields if key in entry}
                    fields['source_conversation_id'] = None
                    fields['active'] = False
                    if payload.format == 'json' and fields.get('project_id'):
                        fields['project_id'] = project_map.get(fields['project_id'], fields['project_id'])
                    value = Memory.model_validate(fields)
                    if value.project_id:
                        own(conn, 'memory_projects', value.project_id, current['id'])
                    if payload.format == 'markdown' and entry.get('id'):
                        old = own(conn, 'personal_memories', entry['id'], current['id'])
                        if old['version'] != entry.get('version'):
                            raise HTTPException(409, '导出后记忆已被修改，请下载最新版本再编辑')
                        from .memory_reliability import SOURCE_FIELDS
                        previous=item_for(conn,current['id'],old['id'])
                        if any(previous.get(field)!=value.model_dump().get(field) for field in SOURCE_FIELDS):invalidate_dependents(conn,old['id'])
                        conn.execute('''UPDATE personal_memories SET content=?,kind=?,scope=?,project_id=?,topic=?,
                            version=version+1,updated_at=? WHERE id=?''', (value.content, value.kind, value.scope,
                            value.project_id, value.topic, int(time.time()), old['id']))
                        # Editing a pending proposal does not silently approve it.
                        conn.execute("UPDATE memory_details SET locked=1,labels=? WHERE memory_id=?", (dumps(value.labels), old['id']))
                        save_policy(conn, old['id'], value.model_dump())
                        from .memory_lifecycle import set_semantics
                        set_semantics(conn,old['id'],admission='manual',tier=previous['tier'] if previous['kind']==value.kind else None)
                        conn.execute('UPDATE memory_semantics SET status=? WHERE memory_id=?',(previous['status'],old['id']))
                        record_revision(conn, old['id'], 'markdown-edit')
                        saved.append(old['id'])
                    else:
                        signature = (scope_key(value.model_dump()), digest(value.content))
                        if signature in existing:
                            continue
                        key = insert_memory(conn, current['id'], value.model_dump(), origin='import', review='pending', locked=True, labels=value.labels)
                        if key:
                            saved.append(key)
                            existing[signature] = key
                            archive = {field: entry[field] for field in ('evidence', 'revisions', 'links', 'imported_provenance') if field in entry}
                            if archive:
                                conn.execute('INSERT INTO memory_import_provenance VALUES(?,?)', (key, dumps(archive)))
                return {'saved': saved, 'count': len(saved), 'note': 'Markdown 更新保留原启用状态；JSON 新导入内容先核对再启用。'}
        except (ValueError, TypeError, KeyError, RecursionError):
            raise HTTPException(422, '记忆文件格式、字段或数量不符合要求') from None
