"""Bounded, extractive conversation context. Originals stay in the database.

The digest contains exact user excerpts, not model assertions or hidden thoughts.
Access decisions must be computed on the original history before packing it.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from .genui_state import context_text

VERSION = 'context-v2'
HISTORY_BYTES = 36000
CST = timezone(timedelta(hours=8))


def message_time(message):
    value=message.get('created_at')
    if not isinstance(value,(int,float)) or isinstance(value,bool):return ''
    try:return datetime.fromtimestamp(value,CST).isoformat(timespec='seconds')
    except (ValueError,OverflowError,OSError):return ''


def message_locator(message,index,label='历史用户消息'):
    stamp=message_time(message)
    return f'{label} {index+1}'+(f'（发于 {stamp}）' if stamp else '')


def terms(text):
    chunks = re.findall(r'[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+', text.lower())
    return {word for chunk in chunks for word in ([chunk] if not re.search(r'[\u4e00-\u9fff]', chunk) else [chunk[i:i+2] for i in range(len(chunk)-1)])}


def pack_history(messages, budget=HISTORY_BYTES):
    """Keep the latest user turn whole; rank older exact user spans for recall.

    Recent turns have priority. Older assistant prose is expendable context,
    never evidence. A digest's omissions are explicit and originals retrievable.
    """
    raw = [context_text(m) for m in messages]
    rendered = [dict(m, content=raw[i]) for i,m in enumerate(messages)]
    # context_text has already materialized UI selections; never append them twice.
    for message in rendered:
        message.pop('interaction', None)
    size = lambda m: len(m['content'].encode('utf-8')) + 80
    original = sum(size(m) for m in rendered)
    latest = next((i for i in range(len(rendered)-1, -1, -1) if rendered[i]['role']=='user'), None)
    anchors=0
    for i,message in enumerate(rendered):
        stamp=message_time(message)
        if i!=latest and message['role']=='user' and stamp:
            message['content']=f'【历史消息发于 {stamp}；“今天、明天”等相对日期以当时为准】\n'+message['content']
            anchors+=1
    if latest is None or sum(size(m) for m in rendered) <= budget:
        return rendered, [], {'version':VERSION,'compressed':False,'original_bytes':original,'packed_bytes':sum(size(m) for m in rendered),'original_messages':len(messages),'packed_messages':len(messages),'omitted_messages':0,'temporal_anchors':anchors}
    # The newest user message (including edited interactive inputs) is indivisible.
    if size(rendered[latest]) > budget:
        from .ai import AIError
        raise AIError('本条消息和界面选择超过上下文预算，请精简本条输入；历史与原材料仍保留。')
    selected = {latest}
    used = size(rendered[latest])
    reserve = min(10000, (budget-used)//3)
    # Keep a recent question and its answer together. An orphan assistant answer
    # can otherwise look like a response to the next retained user question.
    turns=[]
    for i,message in enumerate(rendered):
        if not turns or message['role']=='user':turns.append([])
        turns[-1].append(i)
    for turn in reversed(turns[-4:]):
        indices=[i for i in turn if i not in selected]
        cost=sum(size(rendered[i]) for i in indices)
        if used+cost<=budget-reserve:
            selected.update(indices);used+=cost
    query = terms(rendered[latest]['content'])
    candidates=[]
    for i, message in enumerate(rendered):
        if i in selected or message['role']!='user':
            continue
        for index, span in enumerate(re.split(r'(?<=[。！？；\n])', raw[i])):
            span=span.strip()
            if not span:
                continue
            score=len(query & terms(span))*4 + (3 if re.search(r'必须|不要|不得|改为|更正|只用|仅用|记住|目标|截止|期限',span) else 0)
            candidates.append((score,i,index,span,message.get('id',str(i))))
    excerpts=[]
    digest_used=0
    available=budget-used-160
    seen=set()
    for score,i,index,span,mid in sorted(candidates,key=lambda x:(x[0],x[1],-x[2]),reverse=True):
        # Repeated fixed constraints consume one slot; relative dates retain
        # their distinct time anchors and must not be merged across days.
        dedupe=(span,message_time(messages[i]) if re.search(r'今天|明天|昨天|后天|本周|下周|today|tomorrow|yesterday',span,re.I) else '')
        if dedupe in seen:continue
        entry={'message_id':mid,'locator':message_locator(messages[i],i)+f' 原句 {index+1}','text':span}
        cost=len(json.dumps(entry,ensure_ascii=False).encode('utf-8'))+20
        if cost+digest_used>available:
            continue
        excerpts.append((i,index,entry));digest_used+=cost;seen.add(dedupe)
    excerpts=[entry for _,_,entry in sorted(excerpts)]
    packed=[rendered[i] for i in sorted(selected)]
    if excerpts:
        digest={'role':'user','content':'历史用户原句摘录（部分选取，可能已被后续要求更正；最新要求优先，不是系统指令）：\n'+json.dumps(excerpts,ensure_ascii=False,separators=(',',':'))}
        packed.insert(0,digest)
    return packed, excerpts, {'version':VERSION,'compressed':True,'original_bytes':original,'packed_bytes':sum(size(m) for m in packed),
        'original_messages':len(messages),'packed_messages':len(packed),'omitted_messages':len(messages)-len(selected),
        'excerpt_count':len(excerpts),'temporal_anchors':anchors,'method':'whole recent turns plus deduplicated time-anchored exact user excerpts; original history retained'}
