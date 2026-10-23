"""The model selects bounded references; the server restores exact source quotes."""
from copy import deepcopy

MAX_QUOTE=1400
PRIVATE_TASK_FIELDS={'planned_at','reminder_at','deadline_confirmed','resolution_note','notes','origin'}


def build(sources):
    references={};prepared=[]
    for source in sources:
        sections=[]
        for section in source['sections']:
            text=section['text']
            # Every character is retained. References keep the original locator;
            # each resulting quote is an exact contiguous slice of that section.
            for start in range(0,len(text),MAX_QUOTE):
                quote=text[start:start+MAX_QUOTE]
                if not quote.strip():continue
                ref=f'R{len(references)+1:06}'
                references[ref]={'source_id':source['id'],'locator':section['locator'],'quote':quote}
                sections.append({'ref':ref,'locator':section['locator'],'text':quote})
        prepared.append({'id':source['id'],'name':source.get('name','通知材料'),'status':source.get('status','ok'),
                         'warning':source.get('warning',''),'sections':sections})
    return prepared,references


def output_schema(schema):
    schema=deepcopy(schema)
    schema['$defs']['Evidence']={'type':'string','pattern':'^R[0-9]{6}$','description':'选择输入中实际存在的原文 ref 编号，程序会还原原句与位置。'}
    for key in PRIVATE_TASK_FIELDS:schema['$defs']['TaskData']['properties'].pop(key,None)
    schema['$defs']['ScheduledTime']['properties'].pop('confirmed',None)
    # Keep each proposal beside its task in model output; public task records
    # and workflow records remain separate after deterministic normalization.
    schema['$defs']['TaskData']['properties'].update(schema['$defs'].pop('DraftPlan')['properties'])
    task=schema['$defs']['TaskData']
    task['required']=['title','scope','evidence','action_kind','execution_mode','dependency_mode','condition_mode','depends_on','conditions','due_date','due_time','deadline_text','deadline_evidence']
    task['properties']['evidence']['minItems']=1
    fact=schema['$defs']['Fact']
    fact['required']=['value','evidence']
    schema['properties']['facts']={'type':'object','additionalProperties':False,
        'properties':{key:{'$ref':'#/$defs/Fact'} for key in
            ['theme','audience','dates','actions','materials','submission','location','contact']},
        'required':['theme','audience','dates','actions','materials','submission','location','contact']}
    schema['properties'].pop('plans',None)
    return schema


def expand(raw,references):
    if not isinstance(raw,dict):return raw
    result=deepcopy(raw)
    def resolve(items):
        if not isinstance(items,list):return items
        restored=[];seen=set()
        for item in items:
            if isinstance(item,str):
                if item not in references:raise ValueError('原文引用编号不存在，未接受模型草稿')
                if item in seen:continue
                seen.add(item);restored.append(dict(references[item]))
            else:restored.append(item)  # Existing exact-quote adapters still receive strict validation.
        return restored
    facts=result.get('facts')
    if isinstance(facts,dict):
        for fact in facts.values():
            if isinstance(fact,dict) and 'evidence' in fact:fact['evidence']=resolve(fact['evidence'])
    tasks=result.get('tasks')
    if isinstance(tasks,list):
        for task in tasks:
            if isinstance(task,dict):
                for key in ['evidence','deadline_evidence']:
                    if key in task:task[key]=resolve(task[key])
                if isinstance(task.get('scheduled'),dict) and 'evidence' in task['scheduled']:
                    task['scheduled']['evidence']=resolve(task['scheduled']['evidence'])
    return result
