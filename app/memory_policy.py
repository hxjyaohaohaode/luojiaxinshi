"""Deterministic memory lifecycle, separate from retrieval and HTTP handlers.

An explicit key expresses a mutually exclusive fact. We do not pretend to infer
arbitrary semantic contradictions. Project overrides topic, which overrides a
general default; incompatible values at the same specificity require a choice.
"""
import time
import unicodedata

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_policies(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 semantic_key TEXT NOT NULL DEFAULT '',valid_from INTEGER,expires_at INTEGER);
UPDATE meta SET value='2' WHERE key='memory_schema_version';
"""


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def rows_for(conn, uid):
    return [dict(r) for r in conn.execute('''SELECT m.*,COALESCE(p.semantic_key,'') AS semantic_key,
        p.valid_from,p.expires_at FROM personal_memories m LEFT JOIN memory_policies p ON p.memory_id=m.id
        WHERE m.user_id=? ORDER BY m.pinned DESC,m.updated_at DESC,m.id''', (uid,))]


def save_policy(conn, mid, value):
    conn.execute('''INSERT INTO memory_policies VALUES(?,?,?,?) ON CONFLICT(memory_id)
        DO UPDATE SET semantic_key=excluded.semantic_key,valid_from=excluded.valid_from,expires_at=excluded.expires_at''',
        (mid, normalized(value.get('semantic_key', '')), value.get('valid_from'), value.get('expires_at')))


def temporal_state(item, now=None):
    now = int(time.time()) if now is None else now
    if not item['active']:return 'inactive'
    if item.get('expires_at') is not None and item['expires_at'] <= now:return 'expired'
    if item.get('valid_from') is not None and item['valid_from'] > now:return 'scheduled'
    return 'active'


def scope_key(item):
    return (item['scope'], item['project_id'] or '', item['topic'])


def effective(items, context, now=None):
    available=[];excluded=[];groups={}
    for item in items:
        eligible=(item['scope']=='global' or item['scope']=='project' and item['project_id']==context['project_id']
                  or item['scope']=='topic' and item['topic'] in context['topics'])
        if not eligible:continue
        state=temporal_state(item, now)
        if state!='active':
            excluded.append({'id':item['id'],'reason':state});continue
        key=normalized(item.get('semantic_key',''))
        if key:groups.setdefault(key,[]).append(item)
        else:available.append(item)
    for key, group in groups.items():
        priority={'global':0,'topic':1,'project':2}
        level=max(priority[item['scope']] for item in group)
        current=[item for item in group if priority[item['scope']]==level]
        excluded.extend({'id':item['id'],'reason':'shadowed','semantic_key':key} for item in group if priority[item['scope']]<level)
        if len({normalized(item['content']) for item in current})>1:
            excluded.extend({'id':item['id'],'reason':'conflict','semantic_key':key} for item in current)
        else:
            chosen=sorted(current,key=lambda item:(-item['pinned'],-item['updated_at'],item['id']))[0]
            available.append(chosen)
            excluded.extend({'id':item['id'],'reason':'duplicate','semantic_key':key} for item in current if item['id']!=chosen['id'])
    return available,excluded


def catalog(items):
    # A catalog has no selected conversation. Only flag conflicts within the
    # exact same scope; cross-topic conflicts are visible in the context preview.
    groups={}
    for item in items:
        key=normalized(item.get('semantic_key',''))
        if key and temporal_state(item)=='active':groups.setdefault((*scope_key(item),key),[]).append(item)
    conflicts={}
    for group in groups.values():
        if len({normalized(item['content']) for item in group})>1:
            for item in group:conflicts[item['id']]=[peer['id'] for peer in group if peer['id']!=item['id']]
    return [{**item,'state':'conflict' if item['id'] in conflicts else temporal_state(item),
             'conflicts':conflicts.get(item['id'],[])} for item in items]


def duplicate(items, payload, excluding=None):
    value=payload.model_dump()
    fields=('kind','source_conversation_id','active','pinned','valid_from','expires_at')
    return next((item for item in items if item['id']!=excluding and scope_key(item)==scope_key(value)
        and normalized(item['content'])==normalized(value['content'])
        and normalized(item.get('semantic_key',''))==normalized(value.get('semantic_key',''))
        and all(item.get(key)==value.get(key) for key in fields)),None)
