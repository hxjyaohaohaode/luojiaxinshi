"""Add-only, owner-scoped import of the application's portable text export."""
import hashlib
import json
import re
import time
from .usage_limits import check_count, check_storage, limits_for
from fastapi import Depends,HTTPException
from pydantic import Field,ValidationError
from .db import audit,dumps,ident
from .models import Strict,Profile,TaskData,safe_url
from .schedule import Arrangement
from .security import rate_limit
from .workflow import WorkflowData, ChangeProposal, PATCH_FIELDS, validate_dependency_graph


class ImportRequest(Strict):
    data: dict
    confirm: bool = False
    digest: str = Field(default='',max_length=64)
    apply_profile: bool = False


def bounded(value,depth=0,counter=None,max_nodes=150000):
    if counter is None:counter=[0]
    counter[0]+=1
    if depth>24 or counter[0]>max_nodes:raise ValueError('导入结构过深或内容过多')
    if isinstance(value,dict):
        if any(k in {'__proto__','constructor','prototype'} for k in value):raise ValueError('导入数据包含不允许的键')
        for item in value.values():bounded(item,depth+1,counter,max_nodes)
    elif isinstance(value,list):
        for item in value:bounded(item,depth+1,counter,max_nodes)
    elif isinstance(value,str) and len(value)>1048576:raise ValueError('导入单项文字过长')


def text(value,maximum,default=''):
    if value is None:value=default
    if not isinstance(value,str) or len(value)>maximum:raise ValueError('导入文字字段格式或长度不正确')
    return value


def collection(data,name,maximum):
    if not isinstance(data,dict):raise ValueError('导入记录必须为对象：'+name)
    items=data.get(name,[])
    if not isinstance(items,list) or len(items)>maximum or any(not isinstance(x,dict) for x in items):raise ValueError('导入列表格式不正确或条数超限：'+name)
    return items


def key(kind,item):
    identity=item.get('id') or dumps(item)
    return hashlib.sha256((kind+':'+str(identity)).encode()).hexdigest()


def sources(items):
    result=[];total=0
    if not isinstance(items,list) or len(items)>100 or any(not isinstance(s,dict) for s in items):raise ValueError('材料列表格式不正确或单份记录的材料过多')
    for s in items:
        sections=[]
        for section in collection(s,'sections',2000):
            value=text(section.get('text'),10000);total+=len(value)
            if total>100000:raise ValueError('单份记录的材料文字过多')
            sections.append({'locator':text(section.get('locator'),80),'text':value,**({'table':True} if section.get('table') is True else {})})
        origin=s.get('origin') or {}
        if not isinstance(origin,dict):raise ValueError('材料来源记录格式不正确')
        portable_origin={'url':safe_url(text(origin.get('url'),2000)), 'retrieved_at':historical_timestamp(origin.get('retrieved_at')),
                         'attachments':[], 'warnings':['导入的来源记录，未在本次重新读取网页'], 'imported':True} if origin else None
        result.append({'old_id':text(s.get('id'),100),'name':text(s.get('name'),160,'导入材料'),
                       'sections':sections,'warning':'从备份导入的提取文字，原始附件未包含在 JSON 中，请按需要重新补充。','origin':portable_origin})
    return result


def historical_impact(items):
    """Portable, display-only history; none of these values become mutation patches."""
    if not isinstance(items,list) or len(items)>100:raise ValueError('变更历史格式不正确')
    result=[]
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('diff'),dict):raise ValueError('变更历史格式不正确')
        diff={}
        for name,pair in item['diff'].items():
            if name not in PATCH_FIELDS|{'status'} or not isinstance(pair,dict) or set(pair)!={'before','after'}:raise ValueError('变更历史字段不正确')
            values={}
            for side,value in pair.items():
                if name=='materials':
                    if not isinstance(value,list) or len(value)>30:raise ValueError('历史材料清单不正确')
                    values[side]=[text(v,500) for v in value]
                else:values[side]=None if value is None else text(value,3000)
            diff[name]=values
        warnings=item.get('warnings',[])
        if not isinstance(warnings,list) or len(warnings)>30:raise ValueError('变更历史说明不正确')
        result.append({'title':text(item.get('title'),160),'diff':diff,'warnings':[text(v,2000) for v in warnings]})
    return result


def historical_timestamp(value):
    if value is not None and (type(value) is not int or not 0<=value<=253402300799):raise ValueError('历史时间不正确')
    return value


def unresolved_dependency(source_id):
    if re.fullmatch(r'missing_[0-9a-f]{32}', source_id):
        return source_id  # Re-exporting an unresolved branch must not hash it again.
    return 'missing_'+hashlib.sha256(source_id.encode()).hexdigest()[:32]


def validate(data, capacity=None):
    from .usage_limits import DEFAULTS
    capacity=capacity or DEFAULTS
    from .workspace import CatalogItem
    bounded(data)
    if data.get('format_version')!=1:raise ValueError('仅支持本系统导出的第 1 版数据文件')
    profile=Profile.model_validate(data.get('profile',{})).model_dump()
    notices=[];chats=[];task_ids=set()
    for n in collection(data,'notices',capacity.notices):
        task_items=[]
        for task in collection(n,'tasks',100):
            details=TaskData.model_validate(task.get('data',{})).model_dump()
            # Imported backup text is not new evidence of a verified official deadline.
            details.update(deadline_confirmed=False,reminder_at=None)
            if details.get('scheduled'):details['scheduled']['confirmed']=False
            if task.get('status') not in {'pending','done','cancelled'}:raise ValueError('待办状态无效')
            old_id=text(task.get('id'),100)
            if old_id and old_id in task_ids:raise ValueError('待办标识重复')
            if old_id:task_ids.add(old_id)
            wrapper=task.get('workflow',{})
            if not isinstance(wrapper,dict):raise ValueError('办理记录格式不正确')
            workflow=WorkflowData.model_validate(wrapper.get('data',{})).model_dump()
            for condition in workflow['conditions']:condition['state']='unknown'
            workflow['prepared_materials']=[m for m in workflow['prepared_materials'] if m in details['materials']]
            review=task.get('change_review');parsed_review=None
            if review is not None:
                from .action_review import Cause
                if not isinstance(review,dict) or review.get('state') not in {'pending','reviewed'} or not isinstance(review.get('data'),dict):raise ValueError('办理复核记录格式不正确')
                causes=review['data'].get('causes',[])
                if not isinstance(causes,list) or len(causes)>1000:raise ValueError('办理复核来源过多或格式不正确')
                parsed_review={'state':review['state'],'causes':[Cause.model_validate(c).model_dump() for c in causes],
                               'note':text(review.get('note'),1500),'reviewed_at':historical_timestamp(review.get('reviewed_at')),
                               'decision':review['data'].get('decision')}
                if not parsed_review['causes']:raise ValueError('办理复核缺少来源')
                if parsed_review['decision'] not in {None,'keep','reopen'}:raise ValueError('办理复核结论无效')
            task_items.append({'old_id':old_id,'data':details,'status':task['status'],'workflow':workflow,'review':parsed_review})
        changes=[]
        for change in collection(n,'changes',100):
            raw=change.get('data',{})
            if not isinstance(raw,dict):raise ValueError('变更记录格式不正确')
            # Imported proposals are historical data, never live authority to mutate new IDs.
            accepted={k:v for k,v in raw.items() if k in ChangeProposal.model_fields}
            proposed=ChangeProposal.model_validate(accepted).model_dump()
            if change.get('state') not in {'pending','applied','dismissed'}:raise ValueError('变更状态无效')
            changes.append({'state':change['state'],'data':proposed,
                            'impact':historical_impact(change.get('impact',[])),
                            'decision_note':text(change.get('decision_note'),1500),
                            'decided_at':historical_timestamp(change.get('decided_at')),
                            'created_at':historical_timestamp(change.get('original_created_at',change.get('created_at')))})
        from .notice_resolution import portable_receipt
        from .notice_intake import DispositionUpdate
        handling=n.get('handling') or {}
        if not isinstance(handling,dict):raise ValueError('通知处理记录格式不正确')
        decision=DispositionUpdate(version=1,disposition=handling.get('disposition','inbox'),note=handling.get('note',''))
        notices.append({'old_id':text(n.get('id'),100),'key':key('notice',n),'title':text(n.get('title'),160),'source_label':text(n.get('source_label'),100),
                        'source_url':safe_url(text(n.get('source_url'),2000)),'sources':sources(n.get('sources',[])),'tasks':task_items,'changes':changes,
                        'quality_receipt':portable_receipt(n.get('quality_receipt')),'handling':decision.model_dump(exclude={'version'})})
    validate_dependency_graph({t['old_id']:t['workflow']['dependencies'] for n in notices for t in n['tasks'] if t['old_id']})
    for c in collection(data,'conversations',capacity.conversations):
        messages=[]
        for m in collection(c,'messages',2000):
            if m.get('role') not in {'user','assistant'}:raise ValueError('对话角色无效')
            timestamp=m.get('created_at')
            if type(timestamp) is not int or not 0<=timestamp<=253402300799:raise ValueError('消息时间无效')
            status=m.get('status','complete')
            if status not in {'complete','failed','cancelled','pending','processing'}:raise ValueError('消息状态无效')
            # An interrupted export is never evidence of a completed model reply.
            if status in {'pending','processing'}:status='cancelled'
            messages.append({'role':m['role'],'content':text(m.get('content'),1048576),'created_at':timestamp,'status':status})
        from .memory import Context
        context=Context.model_validate(c.get('context',{'version':0})).model_dump()
        chats.append({'key':key('chat',c),'title':text(c.get('title'),100),'sources':sources(c.get('sources',[])),'messages':messages,'context':context})
    arrangements=[{'key':key('arrangement',x),'data':Arrangement.model_validate(x.get('data',{})).model_dump()} for x in collection(data,'arrangements',capacity.arrangements)]
    catalog=[{'key':key('catalog',x),'data':CatalogItem.model_validate(x).model_dump()} for x in collection(data,'source_catalog',capacity.sources)]
    from .memory import Memory,Project
    projects=[];memories=[]
    for item in collection(data,'memory_projects',capacity.memory_projects):
        old_id=text(item.get('id'),40)
        if not old_id:raise ValueError('项目缺少原始标识')
        projects.append({'key':key('memory_project',item),'old_id':old_id,'data':Project.model_validate({k:item[k] for k in Project.model_fields if k in item}).model_dump()})
    from .memory_store import MAX_MEMORIES
    for item in collection(data,'memories',MAX_MEMORIES):
        value={k:item[k] for k in Memory.model_fields if k in item}
        value.update(source_conversation_id=None)
        memories.append({'key':key('memory',item),'data':Memory.model_validate(value).model_dump()})
    if len({p['old_id'] for p in projects})!=len(projects):raise ValueError('项目标识重复')
    return {'profile':profile,'notices':notices,'conversations':chats,'arrangements':arrangements,'source_catalog':catalog,'memory_projects':projects,'memories':memories}


def install_data_transfer(app,db,user):
    with db.connect(write=True) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS import_receipts(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,item_key TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(user_id,item_key))')
        conn.execute('CREATE TABLE IF NOT EXISTS import_task_links(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,source_id TEXT NOT NULL,task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,PRIMARY KEY(user_id,source_id))')
        conn.execute('CREATE INDEX IF NOT EXISTS import_task_links_task ON import_task_links(task_id)')

    @app.post('/api/import')
    def import_data(payload:ImportRequest,current=Depends(user)):
        rate_limit(db,'data-import:'+current['id'],30,3600)
        raw=dumps(payload.data)
        if len(raw.encode())>10*1024*1024:raise HTTPException(413,'导入文件超过 10 MB，请拆分')
        digest=hashlib.sha256(raw.encode()).hexdigest()
        try:data=validate(payload.data,db.usage_limits)
        except (ValueError,ValidationError,TypeError,KeyError,OverflowError):raise HTTPException(422,'备份格式、字段或上限不符合要求，请使用本系统导出的 JSON 文件')
        from .notice_matters import validate_import_groups
        try:imported_matters=validate_import_groups(payload.data.get('notice_matters',[]),db.usage_limits.notices)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        counts={k:len(data[k]) for k in ['memory_projects','memories','notices','conversations','arrangements','source_catalog'] if data[k] or k in ['notices','conversations','arrangements','source_catalog']}
        warnings=['只新增记录，不覆盖现有记录；重复导入相同记录会跳过。','附件原件不在 JSON 备份内，恢复提取文字；对话恢复为可读文字，互动状态和引用编号不恢复。','导入待办的正式期限需重新核对，提醒时间清空；不会自动向外部日历写入。']
        warnings.append('办理记录、回执及变更前后值按历史保留；原待确认变更转为待核实线索，设备提醒验证需要重新进行。')
        if payload.data.get('task_material_archive'):
            warnings.append('此文件中的本人办理材料版本目录和提交快照仅供查阅，本次 JSON 导入不恢复这些记录或文件原件。完整恢复请使用管理员数据库备份；原件可在各待办中单独下载。')
        if any(n['quality_receipt'] for n in data['notices']):warnings.append('逐条核对记录作为导入历史保留，不视为当前版本已重新核实；缺失来源保留引句但不能跳转。')
        warnings.append('前置关系按同一账号的原始标识连接；分批导入可补齐先前缺失的关系，找不到的前置事项仍待核实；循环关系会拒绝导入。')
        if data['memories'] or data['memory_projects']:
            warnings.append('项目与记忆按导出文件中的启用状态恢复；原对话来源关联不迁移，历史声明不恢复其他账号权限；项目缺失时拒绝该次导入。')
        if imported_matters:warnings.append('事项归组按原通知标识恢复；请一并导入组内通知，已有归组不会被导入操作改写。')
        if not payload.confirm:return {'digest':digest,'counts':counts,'warnings':warnings,'matter_count':len(imported_matters)}
        if payload.digest!=digest:raise HTTPException(409,'文件在预览后发生变化，请重新预览')
        now=int(time.time());added=0;skipped=0
        with db.connect(write=True) as conn:
            def mapped_project(old):
                if not old:return None
                return hashlib.sha256(('memory-project:'+current['id']+':'+old).encode()).hexdigest()[:32]
            def require_project(old):
                target=mapped_project(old)
                if target and not conn.execute('SELECT 1 FROM memory_projects WHERE id=? AND user_id=?',(target,current['id'])).fetchone():
                    raise HTTPException(422,'记忆引用的项目尚未导入，请一并导入对应项目')
                return target
            task_mapping={r['source_id']:r['task_id'] for r in conn.execute('SELECT l.* FROM import_task_links l JOIN tasks t ON t.id=l.task_id WHERE l.user_id=? AND t.user_id=?',(current['id'],current['id']))}
            imported_workflows=[];imported_reviews=[]
            for kind in counts:
                for item in data[kind]:
                    if conn.execute('SELECT 1 FROM import_receipts WHERE user_id=? AND item_key=?',(current['id'],item['key'])).fetchone():
                        if kind=='notices' and item['old_id']:
                            previous=conn.execute('SELECT id FROM notices WHERE user_id=? AND fingerprint=?',(current['id'],item['key'])).fetchone()
                            if previous:conn.execute('INSERT OR IGNORE INTO import_notice_links VALUES(?,?,?)',(current['id'],item['old_id'],previous['id']))
                        skipped+=1;continue
                    if kind in {'notices','conversations','arrangements','source_catalog'}:
                        check_count(conn,current['id'],kind,'sources' if kind=='source_catalog' else kind,'导入记录')
                    if kind=='notices':check_count(conn,current['id'],'tasks','tasks','待办',len(item['tasks']))
                    rid=ident()
                    if kind=='memory_projects':
                        rid=mapped_project(item['old_id']);value=item['data']
                        if conn.execute('SELECT 1 FROM memory_projects WHERE id=? AND user_id=?',(rid,current['id'])).fetchone():
                            conn.execute('INSERT INTO import_receipts VALUES(?,?,?)',(current['id'],item['key'],now));skipped+=1;continue
                        check_count(conn,current['id'],'memory_projects','memory_projects','项目')
                        conn.execute('INSERT INTO memory_projects VALUES(?,?,?,?,1,?,?)',(rid,current['id'],value['name'],value['description'],now,now))
                    elif kind=='memories':
                        from .memory_store import MAX_MEMORIES,record_revision
                        if conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(current['id'],)).fetchone()[0]>=MAX_MEMORIES:
                            raise HTTPException(422,f'导入后记忆将超过 {MAX_MEMORIES} 条，请先整理已有记忆')
                        value=item['data'];pid=require_project(value['project_id'])
                        conn.execute('INSERT INTO personal_memories VALUES(?,?,?,?,?,?,?,NULL,?,?,1,?,?)',
                            (rid,current['id'],value['scope'],pid,value['topic'],value['kind'],value['content'],int(value['active']),int(value['pinned']),now,now))
                        from .memory_policy import save_policy
                        save_policy(conn,rid,value)
                        conn.execute("UPDATE memory_details SET origin='import',labels=? WHERE memory_id=?",(dumps(value['labels']),rid))
                        record_revision(conn,rid,'import')
                    elif kind=='notices':
                        conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,materials_complete,fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?,?,?)',
                                     (rid,current['id'],item['title'],item['source_label'],item['source_url'],item['key'],'confirmed' if item['tasks'] else 'received',now,now))
                        if item['old_id']:conn.execute('INSERT OR REPLACE INTO import_notice_links VALUES(?,?,?)',(current['id'],item['old_id'],rid))
                        if not item['tasks'] and item['handling']['disposition']!='inbox':
                            conn.execute('INSERT INTO notice_dispositions VALUES(?,?,?,?)',(rid,item['handling']['disposition'],item['handling']['note'],now))
                        mapping={}
                        for source in item['sources']:
                            sid=ident();mapping[source['old_id']]=sid
                            conn.execute("INSERT INTO sources(id,notice_id,name,kind,sha256,status,sections,warning,created_at) VALUES(?,?,?,'text',?,'review',?,?,?)",(sid,rid,source['name'],hashlib.sha256(dumps(source['sections']).encode()).hexdigest(),dumps(source['sections']),source['warning'],now))
                            from .notice_intake import save_origin
                            save_origin(conn,sid,source)
                        for task in item['tasks']:
                            tid=ident()
                            if task['old_id']:
                                if task['old_id'] in task_mapping:raise HTTPException(409,'同源待办已经导入，请保留原通知标识，或核实后手工另建新批次')
                                task_mapping[task['old_id']]=tid
                            details=task['data']
                            for field in ['evidence','deadline_evidence']:
                                details[field]=[{**e,'source_id':mapping[e['source_id']]} for e in details[field] if e['source_id'] in mapping]
                            if details.get('scheduled'):
                                details['scheduled']['evidence']=[{**e,'source_id':mapping[e['source_id']]} for e in details['scheduled']['evidence'] if e['source_id'] in mapping]
                            conn.execute('INSERT INTO tasks(id,user_id,notice_id,data,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(tid,current['id'],rid,dumps(details),task['status'],now,now))
                            if task['old_id']:conn.execute('INSERT INTO import_task_links VALUES(?,?,?)',(current['id'],task['old_id'],tid))
                            imported_workflows.append((tid,rid,task['workflow']))
                            if task['review']:imported_reviews.append((tid,rid,task['review']))
                        from .notice_resolution import import_receipt
                        import_receipt(conn,current['id'],rid,item['quality_receipt'],mapping)
                        for change in item['changes']:
                            audit(conn,current['id'],rid,'import_change_history',after=change)
                            archived={k:change[k] for k in ['impact','decision_note','decided_at','created_at']}
                            if archived['created_at'] is None:archived['created_at']=now
                            change_data={**change['data'],'notice_id':rid,'notice_version':1,'targets':[], 'imported_history':archived}
                            if change['state']=='pending':change_data['kind']='unverified'
                            conn.execute('INSERT INTO notice_changes VALUES(?,?,?,?,?,?,?,?)',(ident(),rid,current['id'],dumps(change_data),change['state'],1,now,now))
                    elif kind=='conversations':
                        conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(rid,current['id'],item['title'],now,now))
                        context=item['context'];pid=require_project(context['project_id'])
                        conn.execute('INSERT INTO conversation_context VALUES(?,?,?,?,1)',(rid,pid,dumps(context['topics']),int(context['memory_enabled'])))
                        conn.execute('INSERT INTO memory_selection_modes VALUES(?,?)',(rid,context.get('selection_mode') or 'manual'))
                        for source in item['sources']:
                            conn.execute("INSERT INTO conversation_sources(id,conversation_id,name,kind,sha256,status,sections,warning,created_at) VALUES(?,?,?,'text',?,'review',?,?,?)",(ident(),rid,source['name'],hashlib.sha256(dumps(source['sections']).encode()).hexdigest(),dumps(source['sections']),source['warning'],now))
                        parent=None
                        for message in item['messages']:
                            mid=ident()
                            conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at,error) VALUES(?,?,?,?,?,?,?,?)",(mid,rid,message['role'],message['content'],message['status'],parent if message['role']=='assistant' else None,message['created_at'],'从备份恢复的未完成回复，已收到的内容保留。' if message['status']!='complete' else ''))
                            if message['role']=='user':parent=mid
                    elif kind=='arrangements':conn.execute('INSERT INTO arrangements(id,user_id,request_id,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',(rid,current['id'],'import_'+item['key'],dumps(item['data']),now,now))
                    else:conn.execute('INSERT INTO source_catalog(id,user_id,data,created_at,updated_at) VALUES(?,?,?,?,?)',(rid,current['id'],dumps(item['data']),now,now))
                    conn.execute('INSERT INTO import_receipts VALUES(?,?,?)',(current['id'],item['key'],now));added+=1
            for tid,nid,workflow in imported_workflows:
                workflow['dependencies']=[task_mapping.get(dep,unresolved_dependency(dep)) for dep in workflow['dependencies']]
                conn.execute('INSERT INTO task_workflows VALUES(?,?,1,?)',(tid,dumps(workflow),now))
                audit(conn,current['id'],nid,'workflow_imported',after=workflow,task_id=tid)
            resolved={unresolved_dependency(source_id):tid for source_id,tid in task_mapping.items()}
            for tid,nid,review in imported_reviews:
                causes=[{**cause,'source_id':task_mapping.get(cause['source_id'],unresolved_dependency(cause['source_id'])),
                         'change_id':'','kind':'imported'} for cause in review['causes']]
                conn.execute('INSERT INTO task_reviews VALUES(?,1,?,?,?,?,?)',
                             (tid,review['state'],dumps({'causes':causes,**({'decision':review['decision']} if review['decision'] else {})}),review['note'],now,review['reviewed_at']))
                audit(conn,current['id'],nid,'change_review_imported',after=review,task_id=tid)
            for row in conn.execute('SELECT r.* FROM task_reviews r JOIN tasks t ON t.id=r.task_id WHERE t.user_id=?',(current['id'],)).fetchall():
                value=json.loads(row['data']);changed=False
                for cause in value['causes']:
                    linked=resolved.get(cause['source_id'])
                    if linked:cause['source_id']=linked;changed=True
                if changed:conn.execute('UPDATE task_reviews SET data=?,version=version+1,updated_at=? WHERE task_id=?',(dumps(value),now,row['task_id']))
            graph={}
            for row in conn.execute('SELECT w.*,t.notice_id FROM task_workflows w JOIN tasks t ON t.id=w.task_id WHERE t.user_id=?',(current['id'],)).fetchall():
                value=json.loads(row['data']);before=value['dependencies']
                value['dependencies']=[resolved.get(dep,dep) for dep in before]
                graph[row['task_id']]=value['dependencies']
                if value['dependencies']!=before:
                    conn.execute('UPDATE task_workflows SET data=?,version=version+1,updated_at=? WHERE task_id=?',(dumps(value),now,row['task_id']))
                    audit(conn,current['id'],row['notice_id'],'import_dependencies_resolved',before={'dependencies':before},after={'dependencies':value['dependencies']},task_id=row['task_id'])
            try:validate_dependency_graph(graph)
            except ValueError as exc:raise HTTPException(422,str(exc)) from None
            from .notice_matters import import_groups
            import_groups(conn,current['id'],imported_matters)
            if payload.apply_profile:conn.execute('UPDATE users SET profile=? WHERE id=?',(dumps(data['profile']),current['id']))
        return {'added':added,'skipped':skipped,'warnings':warnings}
