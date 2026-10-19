"""Confirmed planning constraints never stand for actual external approval."""
import json
from copy import deepcopy

from fastapi import HTTPException

from .db import audit,dumps,ident


def normalize_proposals(raw):
    """Separate task requirements from provider proposals without losing conflicts."""
    if not isinstance(raw,dict) or not isinstance(raw.get('tasks'),list):return raw
    result=deepcopy(raw);plans=result.get('plans',{})
    if not isinstance(plans,dict):return result  # The strict extraction schema reports this.
    for index,task in enumerate(result['tasks']):
        if not isinstance(task,dict):continue
        fields={k:task.pop(k) for k in ('action_kind','depends_on','conditions') if k in task}
        if not fields:continue
        key=str(index) if str(index) in plans else index
        current=plans.get(key,{})
        if not isinstance(current,dict):raise ValueError('办理计划格式无效')
        if any(k in current and current[k]!=v for k,v in fields.items()):raise ValueError('同一步骤的办理计划互相冲突，请重新核对')
        plans[key]={**current,**fields}
    result['plans']=plans
    return result


def gate_issues(data):
    result=[]
    if data.get('action_kind')=='optional' and data.get('participation')!='joined':
        result.append({'code':'participation','label':'本人尚未决定参加' if data.get('participation')!='declined' else '本人已决定不参加'})
    for condition in data.get('conditions',[]):
        if condition['state']!='met':result.append({'code':'condition','label':('条件待核实：' if condition['state']=='unknown' else '条件尚未满足：')+condition['text']})
    return result


def require_gates(data):
    issues=gate_issues(data)
    if issues:raise HTTPException(422,'请先处理办理条件或参加意愿：'+issues[0]['label'])


def require_task_gates(conn,tid):
    row=conn.execute('SELECT data FROM task_workflows WHERE task_id=?',(tid,)).fetchone()
    if row:require_gates(json.loads(row['data']))


def constraint_key(data):
    return (data.get('action_kind','unclassified'),data.get('participation','undecided'),
            tuple(sorted((c['id'],c['text'],c['state']) for c in data.get('conditions',[]))))


def validate_plans(plans,count):
    from .workflow import validate_dependency_graph
    graph={i:[] for i in range(count)}
    for index,plan in plans.items():
        if index not in graph or any(i not in graph for i in plan.depends_on):
            raise ValueError('办理计划引用了未选中或不存在的步骤')
        graph[index]=plan.depends_on
    validate_dependency_graph(graph)


def apply_confirmed_plans(conn,uid,nid,ids,plans,replacements,now):
    """Called inside the same confirmation transaction after every ID is allocated."""
    from .workflow import WorkflowData,validate_dependency_graph
    from .action_review import record_workflow_change
    try:validate_plans(plans,len(ids))
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    graph={r['id']:json.loads(r['workflow'])['dependencies'] if r['workflow'] else [] for r in conn.execute(
        'SELECT t.id,w.data AS workflow FROM tasks t LEFT JOIN task_workflows w ON w.task_id=t.id WHERE t.user_id=?',(uid,))}
    updates=[]
    for index,plan in plans.items():
        tid=ids[index];row=conn.execute('SELECT * FROM task_workflows WHERE task_id=?',(tid,)).fetchone()
        old=WorkflowData.model_validate(json.loads(row['data']) if row else {}).model_dump();version=row['version'] if row else 0
        if index in replacements and plan.workflow_version!=version:
            raise HTTPException(409,'原办理安排已变化，请重新核对后选择是否更新')
        if index not in replacements and plan.workflow_version not in (None,0):raise HTTPException(422,'新事项不能指定已有办理版本')
        if plan.participation=='declined' and plan.action_kind!='optional':raise HTTPException(422,'只有可选事项才能决定不参加')
        existing={c['text']:c for c in old['conditions']}
        conditions=[existing.get(text) or {'id':ident(),'text':text,'state':'unknown','note':''} for text in plan.conditions]
        participation=plan.participation if 'participation' in plan.model_fields_set or index not in replacements else old['participation']
        new={**old,'action_kind':plan.action_kind,'participation':participation if plan.action_kind=='optional' else 'undecided',
             'conditions':conditions,'dependencies':[ids[i] for i in plan.depends_on]}
        graph[tid]=new['dependencies'];updates.append((tid,old,new,version))
    try:validate_dependency_graph(graph)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    for tid,old,new,version in updates:
        if old==new:continue
        conn.execute('INSERT INTO task_workflows VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at',
                     (tid,dumps(new),version+1,now))
        task=dict(conn.execute('SELECT * FROM tasks WHERE id=? AND user_id=?',(tid,uid)).fetchone());task['data']=json.loads(task['data'])
        record_workflow_change(conn,uid,task,old,new)
        audit(conn,uid,nid,'action_plan_confirmed',before=old,after=new,task_id=tid)
