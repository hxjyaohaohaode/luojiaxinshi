"""Version-aware quality checks and bounded, independent session context."""
import json
import re
import time

from fastapi import HTTPException
from .db import dumps

SOURCE_FIELDS=('content','kind','scope','project_id','topic','semantic_key','valid_from','expires_at')


def source_current(conn,parent,version,cache=None):
    parent=dict(parent)
    if parent['version']==version:return True
    key=(parent['id'],version)
    if cache is not None and key in cache:return cache[key]
    row=conn.execute('SELECT snapshot FROM memory_revisions WHERE memory_id=? AND version=?',key).fetchone()
    before=json.loads(row['snapshot']) if row else {}
    if not all(field in parent for field in ('semantic_key','valid_from','expires_at')):
        policy=conn.execute('SELECT semantic_key,valid_from,expires_at FROM memory_policies WHERE memory_id=?',(parent['id'],)).fetchone()
        if policy:parent.update(dict(policy))
    same=bool(row) and all(before.get(field)==parent.get(field) for field in SOURCE_FIELDS)
    if cache is not None:cache[key]=same
    return same


def memory_catalog(conn,uid):
    from .memory_policy import rows_for,catalog
    from .memory_store import decorate,usable_derived
    entries=catalog(decorate(conn,rows_for(conn,uid)))
    now=int(time.time())
    for item in entries:
        if item['state']=='active' and item.get('review_after') and item['review_after']<=now and not item['locked']:
            item['state']='needs_review'
    _,invalid=usable_derived(conn,[item for item in entries if item['state']=='active'])
    for item in entries:
        if item['state']=='active' and item['id'] in invalid:item['state']='source_changed'
    return entries


def candidates(conn,uid,cid,access,scenario=None,ids=None):
    """Discard unavailable overrides before choosing the most specific value."""
    from .memory import context_for
    from .memory_store import decorate,usable_derived
    from .memory_policy import rows_for,effective
    from .memory_lifecycle import recall_gate,source_access
    context=context_for(conn,cid)
    from .memory_autonomy import selected_scopes,resolve_candidates
    contexts=selected_scopes(conn,uid,context,scenario,access)
    raw=rows_for(conn,uid,ids)
    scoped=[item for item in raw if contexts is None or any(item['scope']=='global' or item['scope']=='project' and item['project_id']==scope['project_id'] or item['scope']=='topic' and item['topic'] in scope['topics'] for scope in contexts)]
    entries=decorate(conn,scoped);excluded=[]
    accepted=[item for item in entries if item['review_status']=='accepted']
    excluded.extend({'id':item['id'],'reason':'pending'} for item in entries if item['review_status']!='accepted')
    accepted,blocked=source_access(conn,uid,accepted,{**access,'_memory_conversation_id':cid});excluded.extend(blocked)
    accepted,blocked=recall_gate(conn,uid,cid,accepted);excluded.extend(blocked)
    accepted,invalid=usable_derived(conn,accepted)
    excluded.extend({'id':key,'reason':'source_changed'} for key in invalid)
    if scenario is not None:
        accepted,blocked=scenario_gate(conn,accepted,scenario);excluded.extend(blocked)
    accepted,blocked=resolve_candidates(accepted,contexts);excluded.extend(blocked)
    accepted,invalid=usable_derived(conn,accepted)
    excluded.extend({'id':key,'reason':'source_changed'} for key in invalid)
    return accepted,excluded


def overlay_sessions(conn,entries):
    if not entries:return entries
    edits={row['session_id']:dict(row) for row in conn.execute('SELECT * FROM memory_session_edits WHERE session_id IN (SELECT value FROM json_each(?))',(dumps([entry['id'] for entry in entries]),))}
    return [{**entry,'original_content':entry['content'],'content':edits.get(entry['id'],{}).get('content',entry['content']),
        'edited_by_user':entry['id'] in edits,'edit_version':edits.get(entry['id'],{}).get('version',0)} for entry in entries]


def mutation_lookup(conn,uid,key,operation,payload):
    from .memory_store import digest
    if key is None:return None
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',key):raise HTTPException(422,'操作标识无效，请重新打开编辑器')
    conn.execute('DELETE FROM memory_mutation_receipts WHERE user_id=? AND expires_at<=?',(uid,int(time.time())))
    row=conn.execute('SELECT * FROM memory_mutation_receipts WHERE user_id=? AND request_id=?',(uid,key)).fetchone()
    if row:
        if row['operation']!=operation or row['payload_hash']!=digest(dumps(payload)):
            raise HTTPException(409,'同一个操作标识对应不同内容，请核对后重新提交')
        return json.loads(row['result'])
    if conn.execute('SELECT count(*) FROM memory_mutation_receipts WHERE user_id=?',(uid,)).fetchone()[0]>=10000:
        raise HTTPException(429,'操作回执达到保留上限，请稍后重试')
    return None


def mutation_record(conn,uid,key,operation,payload,result):
    from .memory_store import digest
    if key is None:return
    now=int(time.time())
    conn.execute('INSERT INTO memory_mutation_receipts VALUES(?,?,?,?,?,?,?)',(uid,key,operation,digest(dumps(payload)),dumps(result),now,now+7*86400))


def mutation_item(conn,uid,receipt,reader):
    if not conn.execute('SELECT 1 FROM personal_memories WHERE id=? AND user_id=?',(receipt['id'],uid)).fetchone():
        raise HTTPException(410,'原请求已保存，但条目后来已被遗忘；如需重新保存，请明确创建新的请求')
    return {**reader(conn,receipt['id'],uid),'replayed':True,'applied_version':receipt['version']}


def scenario_gate(conn,items,scenario):
    from .memory_store import usable_derived
    scenario=scenario.casefold()
    selected=[item for item in items if not item.get('applies_to') or any(cue.casefold() in scenario for cue in item['applies_to'])]
    selected,invalid=usable_derived(conn,selected)
    kept={item['id'] for item in selected}
    return selected,[{'id':item['id'],'reason':'source_scenario' if item['id'] in invalid else 'scenario_mismatch'} for item in items if item['id'] not in kept]


def session_payload(state,budget=5000):
    """A human working-note lock never erases current session conditions."""
    from .memory_learning import SECRET
    result={}
    def fits(value):return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))<=budget
    for key in ('goal','current_request'):
        text=SECRET.sub('[凭证已省略]',state.get(key,''))
        text=text.encode('utf-8')[:900].decode('utf-8',errors='ignore')
        if text and fits({**result,key:text}):result[key]=text
    for key in ('facts','decisions','open_questions','completed_steps','next_steps'):
        values=state.get(key,[])
        if key=='facts':values=sorted(values,key=lambda item:item.get('lifetime')=='turn',reverse=True)
        for entry in values:
            if isinstance(entry,dict):
                entry={k:v for k,v in entry.items() if k in ('id','content','kind','source_message_id','lifetime','edited_by_user','edit_version')}
                entry['content']=SECRET.sub('[凭证已省略]',entry['content'])
            else:entry=SECRET.sub('[凭证已省略]',entry)
            proposal={**result,key:[*result.get(key,[]),entry]}
            if fits(proposal):result=proposal
    return result
