"""A read-only, evidence-backed briefing candidate for narrow task queries.

The tool may end authoring, never independent review or publication fencing.
Complex policy/attachment/calendar questions still need the regular Agent loop.
"""
from datetime import datetime, time, timedelta, timezone
import re
CST=timezone(timedelta(hours=8))


def requested_attention_count(text):
    """Bind an unambiguous requested shortlist size, never infer task intent.

    This is a guard on a read-only tool argument, not an answer truncator.
    Corrections, per-group requests and conflicting counts stay with the model.
    """
    text=re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|`[^`]*`|"[^"]*"','',text)
    if re.search(r'不是|而是|改为|改成|上次|之前|原来|分别|每(?:组|类|人|天|周)',text):return None
    if re.search(r'只(?:要|需|用|给|告诉我|统计).{0,8}(?:数量|总数|项数)',text):return None
    digits={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    def number(value):
        if value.isascii() and value.isdecimal():return int(value)
        if value in digits:return digits[value]
        if value.count('十')==1:
            left,right=value.split('十')
            if (not left or left in digits and digits[left]<10)and(not right or right in digits and digits[right]<10):
                return (digits.get(left,1)*10)+digits.get(right,0)
        return None
    numeral=r'([一二两三四五六七八九十]{1,3}|[1-9][0-9]?)'
    prefix=r'(?:哪|(?:最先|优先|先)(?:应|要|帮我|为我|给我|处理|做|关注|列出|选出|查看|看|展示|的|推荐){0,5}|(?:推荐|列出|选出|给我|告诉我)前?)'
    values=[number(match[1])for match in re.finditer(prefix+numeral+r'\s*(?:件|项|条)',text)]
    values += [int(match[1])for match in re.finditer(r'\b(?:top|first)\s+([1-9][0-9]?)\s+(?:tasks?|items?|things?)\b',text,re.I)]
    values=set(value for value in values if value is not None)
    return next(iter(values))if len(values)==1 and 1<=next(iter(values))<=50 else None


def safe_text(value):
    text=' '.join(str(value).split()).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    text=text.replace('[','&#91;').replace(']','&#93;')
    return re.sub(r'([\\`*_{}|])',r'\\\1',text)


def due_at(record):
    data=record.get('data')or{}
    if not data.get('deadline_confirmed') or not data.get('due_date'):return None
    day=datetime.fromisoformat(data['due_date']).date()
    clock=time.fromisoformat(data['due_time'])if data.get('due_time')else time(23,59,59)
    # Date-only records are ordered at the end of that day. Never display this
    # internal ordering value as an official hour/minute.
    return datetime.combine(day,clock,tzinfo=CST)


def has_changes(record):
    return bool(record.get('pending_changes') or (record.get('change_review')or{}).get('state')=='pending'
                or (record.get('handling_state')or{}).get('kind')=='changes')


def attention_tier(record,now):
    workflow=record.get('workflow')or{}
    due=due_at(record)
    # Use the same 24-hour / 3-day urgency windows as the reminder centre.
    changed=has_changes(record)
    if due and now<=due<=now+timedelta(days=1):group=0
    elif changed:group=1;due=None
    elif due and now-timedelta(days=14)<=due<=now+timedelta(days=3):group=2
    elif record.get('followup_due'):group=3
    elif workflow.get('blocked'):group=5
    elif due and due>now:group=4
    else:group=6
    return group,due or datetime.max.replace(tzinfo=CST)


def attention_key(record,now):
    # An ID only makes the display stable; it is never a priority argument.
    return *attention_tier(record,now),record['id']


def prepare_briefing(result,count,now):
    if count and (result.get('has_more') or result.get('offset')):
        return None
    entries=result.get('evidence_index')or[]
    scope=next((entry['ref']for entry in entries if entry['locator']=='查询范围'),None)
    if not scope:return None
    counts=result['query_task_status_counts'];total=sum(counts.values())
    claims=[]
    def claim(text,ref,kind='fact'):
        claims.append({'kind':kind,'text':text,'evidence_refs':[ref]})
        return text+'['+ref+']'
    header=f"当前匹配到 {total} 条已保存待办：待完成 {counts.get('pending',0)} 条、本人已标记完成 {counts.get('done',0)} 条"
    if counts.get('cancelled'):header+=f"、已取消 {counts['cancelled']} 条"
    lines=[claim(header+'。',scope)]
    if count:
        active=[record for record in result['records']if record.get('kind')=='tasks'
                and (record['status']=='pending' or record['status']=='done' and has_changes(record))
                and not record.get('action_excluded')
                and ((record.get('handling_state')or{}).get('kind')!='closed' or has_changes(record))
                and not ((record.get('workflow')or{}).get('data')or{}).get('participation')=='declined']
        by_id={record['id']:record for record in active}
        def prerequisite(record,seen):
            if record['id']in seen or has_changes(record):return record
            workflow=record.get('workflow')or{}
            if not workflow.get('blocked'):return record
            pending=[by_id[item['id']]for item in workflow.get('dependencies',[])if item.get('id')in by_id]
            return prerequisite(min(pending,key=lambda value:attention_key(value,now)),seen|{record['id']})if pending else record
        selected=[];selected_ids=set()
        for record in sorted(active,key=lambda value:attention_key(value,now)):
            record=prerequisite(record,set())
            if record['id']not in selected_ids:selected.append(record);selected_ids.add(record['id'])
            if len(selected)==count:break
        if not selected and counts.get('pending'):return None
        if selected:lines.extend(['','以下是根据已保存状态和期限给出的处理建议：'])
        for number,record in enumerate(selected,1):
            ref=next((entry['ref']for entry in entries if entry['locator']==f"记录 {record['id']} 状态核对"),None)
            if not ref:return None
            data=record['data'];workflow=record.get('workflow')or{};progress=workflow.get('data')or{}
            title=safe_text(data['title']);state=record.get('handling_state')or{}
            label=('本人已标记完成，仍有变动待核实'if record['status']=='done' and has_changes(record)
                   else state.get('label')or'核对当前办理状态')
            sentence=f'**{title}**：{safe_text(label)}。'
            if not has_changes(record) and due_at(record) and due_at(record)<now:
                sentence+='记录中的期限已过，先核对是否仍可办理。'
            detail=claim(sentence,ref,'advice')
            if workflow.get('blocked'):
                detail+=' '+claim('本站前置记录仍有阻碍。',ref)
            elif workflow.get('dependencies'):
                detail+=' '+claim('本站前置记录当前未形成阻碍。',ref)
            if data.get('deadline_confirmed') and data.get('due_date'):
                deadline=data['due_date']+(' '+data['due_time']if data.get('due_time')else '')
                detail+=' '+claim(('记录中确认过的期限：'+deadline+'。')if has_changes(record)
                                  else '记录中确认的期限：'+deadline+'。',ref)
            else:
                detail+=' '+claim('未记录已确认的期限。',ref)
            if progress.get('followup_at'):
                follow=datetime.fromisoformat(progress['followup_at']).astimezone(CST).strftime('%Y-%m-%d %H:%M')
                detail+=' '+claim('个人跟进安排：'+follow+'，不是截止时间。',ref)
            lines.append(f'{number}. '+detail)
        if selected:
            last=selected[-1]
            peers=[record for record in active if record['id']not in selected_ids
                   and attention_tier(record,now)==attention_tier(last,now)
                   and (record.get('handling_state')or{}).get('kind')==(last.get('handling_state')or{}).get('kind')
                   and not (record.get('workflow')or{}).get('blocked')]
            if peers:
                refs=[next((entry['ref']for entry in entries if entry['locator']==f"记录 {record['id']} 状态核对"),None)for record in [last,*peers]]
                if not all(refs):return None
                # A deterministic shortlist must not turn equal deadlines and
                # states into a fictional official order. Give the user the
                # alternatives and the actual limit of the ranking evidence.
                names='、'.join('「'+safe_text(record['data']['title'])+'」'for record in peers)
                text=f'另有{names}与第 {len(selected)} 项的期限记录和当前办理状态相同；现有记录不足以判定谁更优先，可以从中任选一项开始。'
                claims.append({'kind':'advice','text':text,'evidence_refs':refs})
                lines.extend(['',text+''.join('['+ref+']'for ref in refs)])
    if len(claims)>60:return None
    return {'answer':'\n'.join(lines),'claims':claims}
