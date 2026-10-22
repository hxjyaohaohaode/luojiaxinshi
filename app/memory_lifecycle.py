"""Evidence-based admission, session checkpoints, contextual use and retirement.

This module implements lifecycle decisions in the application's transaction, not
in a second memory service. Source ideas and adaptations are documented in
docs/MEMORY_LIFECYCLE_V3.md. No upstream implementation is copied here.
"""
import json
import re
import time

from .db import dumps, ident
from .memory_policy import normalized, scope_key

TABLES = {'memory_semantics', 'memory_session_items', 'memory_checkpoints',
          'memory_lifecycle_settings', 'memory_usage', 'memory_feedback',
          'memory_events', 'memory_forgotten_spans', 'memory_lifecycle_runs', 'memory_working_frames','memory_message_context','memory_forget_boundaries'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_forget_boundaries(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 generation INTEGER NOT NULL DEFAULT 0,last_request_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_message_context(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 context_key TEXT NOT NULL,learning_allowed INTEGER NOT NULL,created_at INTEGER NOT NULL,generation INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO memory_message_context SELECT id,'',0,created_at,0 FROM conversation_messages WHERE role='user';
CREATE TRIGGER IF NOT EXISTS memory_message_context_insert AFTER INSERT ON conversation_messages
 WHEN NEW.role='user' AND NEW.status='complete' BEGIN
 INSERT OR IGNORE INTO memory_message_context
 SELECT NEW.id,memory_context_key(x.project_id,coalesce(x.topics,'[]')),
 CASE WHEN coalesce(s.mode,'auto') IN ('auto','review') AND coalesce(x.memory_enabled,1)=1 THEN 1 ELSE 0 END,NEW.created_at,coalesce(b.generation,0)
 FROM conversations c LEFT JOIN conversation_context x ON x.conversation_id=c.id
 LEFT JOIN memory_settings s ON s.user_id=c.user_id LEFT JOIN memory_forget_boundaries b ON b.user_id=c.user_id WHERE c.id=NEW.conversation_id;
END;
CREATE TABLE IF NOT EXISTS memory_semantics(
 memory_id TEXT PRIMARY KEY REFERENCES personal_memories(id) ON DELETE CASCADE,
 tier TEXT NOT NULL DEFAULT 'long_term' CHECK(tier IN ('long_term','episodic')),
 shared INTEGER NOT NULL DEFAULT 1,facet TEXT NOT NULL DEFAULT '',canonical_value TEXT NOT NULL DEFAULT '',
 confidence REAL NOT NULL DEFAULT 1,importance REAL NOT NULL DEFAULT 0.5,
 admission TEXT NOT NULL DEFAULT 'manual',status TEXT NOT NULL DEFAULT 'active',
 last_confirmed_at INTEGER NOT NULL,review_after INTEGER,positive INTEGER NOT NULL DEFAULT 0,
 negative INTEGER NOT NULL DEFAULT 0,applies_to TEXT NOT NULL DEFAULT '[]',version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS memory_session_items(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 source_message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,content TEXT NOT NULL,slot TEXT NOT NULL DEFAULT '',context_key TEXT NOT NULL DEFAULT '',
 lifetime TEXT NOT NULL DEFAULT 'session',created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
 promoted_id TEXT REFERENCES personal_memories(id) ON DELETE SET NULL,
 UNIQUE(conversation_id,source_message_id,kind,content));
CREATE INDEX IF NOT EXISTS memory_session_owner ON memory_session_items(user_id,conversation_id,expires_at);
CREATE TABLE IF NOT EXISTS memory_checkpoints(
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 version INTEGER NOT NULL,data TEXT NOT NULL,source_message_id TEXT REFERENCES conversation_messages(id) ON DELETE CASCADE,
 created_at INTEGER NOT NULL,PRIMARY KEY(conversation_id,version));
CREATE TABLE IF NOT EXISTS memory_working_frames(
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 context_key TEXT NOT NULL,content TEXT NOT NULL,version INTEGER NOT NULL,
 locked INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL,
 PRIMARY KEY(conversation_id,context_key));
INSERT OR IGNORE INTO memory_working_frames SELECT w.conversation_id,
 memory_context_key(c.project_id,coalesce(c.topics,'[]')),w.content,w.version,w.locked,w.updated_at
 FROM memory_working w LEFT JOIN conversation_context c ON c.conversation_id=w.conversation_id;
CREATE TABLE IF NOT EXISTS memory_lifecycle_settings(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 session_days INTEGER NOT NULL DEFAULT 7,episode_days INTEGER NOT NULL DEFAULT 30,
 auto_promote INTEGER NOT NULL DEFAULT 1,auto_cooldown INTEGER NOT NULL DEFAULT 1,
 cross_session INTEGER NOT NULL DEFAULT 1,semantic_reflection INTEGER NOT NULL DEFAULT 0,
 reflection_budget INTEGER NOT NULL DEFAULT 2,version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS memory_usage(
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 memory_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 memory_version INTEGER NOT NULL,outcome TEXT NOT NULL DEFAULT 'exposed',created_at INTEGER NOT NULL,
 PRIMARY KEY(message_id,memory_id));
CREATE TABLE IF NOT EXISTS memory_feedback(
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 memory_id TEXT NOT NULL REFERENCES personal_memories(id) ON DELETE CASCADE,
 outcome TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(message_id,memory_id));
CREATE TABLE IF NOT EXISTS memory_events(
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 memory_id TEXT REFERENCES personal_memories(id) ON DELETE SET NULL,
 event TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS memory_events_owner ON memory_events(user_id,created_at);
CREATE TABLE IF NOT EXISTS memory_forgotten_spans(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 source_id TEXT NOT NULL,source_hash TEXT NOT NULL,quote_hash TEXT NOT NULL,
 start_offset INTEGER NOT NULL,end_offset INTEGER NOT NULL,created_at INTEGER NOT NULL,
 PRIMARY KEY(user_id,source_id,quote_hash));
CREATE TABLE IF NOT EXISTS memory_lifecycle_runs(
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 ran_at INTEGER NOT NULL,report TEXT NOT NULL);
INSERT OR IGNORE INTO memory_semantics(memory_id,tier,facet,canonical_value,admission,last_confirmed_at,status,review_after)
 SELECT m.id,CASE WHEN d.origin='task' OR m.kind='episode' OR (d.origin IN ('automatic','agent') AND m.kind='intention') THEN 'episodic' ELSE 'long_term' END,
 memory_facet(m.content,coalesce(p.semantic_key,'')),memory_value(m.content,coalesce(p.semantic_key,'')),
 CASE WHEN d.origin='manual' THEN 'manual' ELSE 'legacy' END,m.updated_at,
 CASE WHEN d.origin IN ('automatic','agent') AND d.locked=0 AND memory_admit(m.content,m.kind)<>'long_term' THEN 'needs_review' ELSE 'active' END,
 CASE WHEN d.origin='task' THEN m.updated_at+2592000 WHEN d.origin IN ('automatic','agent') AND d.locked=0 THEN m.updated_at+7776000 ELSE NULL END
 FROM personal_memories m JOIN memory_details d ON d.memory_id=m.id
 LEFT JOIN memory_policies p ON p.memory_id=m.id;
CREATE TRIGGER IF NOT EXISTS memory_semantic_insert AFTER INSERT ON personal_memories BEGIN
 INSERT OR IGNORE INTO memory_semantics(memory_id,tier,facet,canonical_value,last_confirmed_at)
 VALUES(NEW.id,CASE WHEN NEW.kind='episode' THEN 'episodic' ELSE 'long_term' END,
 memory_facet(NEW.content,''),memory_value(NEW.content,''),NEW.updated_at);
END;
CREATE TRIGGER IF NOT EXISTS memory_semantic_update AFTER UPDATE OF content ON personal_memories
 WHEN OLD.content<>NEW.content BEGIN
 UPDATE memory_semantics SET facet=memory_facet(NEW.content,coalesce((SELECT semantic_key FROM memory_policies WHERE memory_id=NEW.id),'')),
 canonical_value=memory_value(NEW.content,coalesce((SELECT semantic_key FROM memory_policies WHERE memory_id=NEW.id),'')),
 last_confirmed_at=NEW.updated_at,status='active',version=version+1 WHERE memory_id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS memory_session_source_delete BEFORE DELETE ON conversation_messages WHEN OLD.role='user' BEGIN
 DELETE FROM memory_checkpoints WHERE conversation_id=OLD.conversation_id;
 DELETE FROM memory_working_frames WHERE conversation_id=OLD.conversation_id AND locked=0;
 UPDATE memory_working SET content='',version=version+1 WHERE conversation_id=OLD.conversation_id AND locked=0;
END;
UPDATE meta SET value='3' WHERE key='memory_engine_schema_version';
"""

FACETS = (
    ('identity.name', r'个人称呼|称呼|我的名字|叫我|我叫|name is|call me'),
    ('style.language', r'写作语言|用中文|用英文|使用中文|使用英文|中文回答|英文回答|reply in (?:english|chinese)'),
    ('style.length', r'简洁|简短|精炼|详细|精简|字数|concise|brief|detailed'),
    ('style.structure', r'(?:回答|回复|写作|表达|排版|措辞|输出|结构).{0,24}(?:先|分点|分步)|先(?:给|说|听|列|看|讲).{0,6}(?:结论|依据|要点|下一步)|回答.{0,6}下一步|分点|分步骤|结论在前|bullet|step.by.step'),
    ('identity.location', r'常用地点|我的校区|我住在|我在.{0,10}校区'),
    ('identity.study', r'我的专业|我就读|我是.{0,15}(?:学生|研究生)|我的年级'),
    ('work.tool', r'采用|使用.{0,12}(?:框架|工具|软件)|工具偏好'),
)
STABLE = re.compile(r'记住|记一下|以后|平时|通常|一直|始终|长期|每次|我的(?:名字|称呼|专业|校区|年级)|我叫|叫我|remember|always|usually', re.I)
TEMPORARY = re.compile(r'仅本次|只在本次|只(?:用|在|限|针对)这(?:次|轮)|这(?:次|篇|封|份|段)|本次(?!项目)|本轮|临时|暂时|今天|明天|今晚|稍后|一会儿|today|tomorrow|this (?:turn|time)', re.I)
PERSONAL_CONTEXT = re.compile(r'(?:我的|我目前|我现在|我正在|我计划|我打算|我希望|我需要|我们|本项目|这个项目|本次项目)')


def facet(text, key=''):
    value = key + ' ' + text
    for name,pattern in FACETS:
        if not re.search(pattern,value,re.I):continue
        if name in ('style.language','style.length') and not re.search(r'回答|回复|写作|输出|表达|措辞|篇幅|字数|风格|摘要|语言|reply|response|writing|concise|brief|detailed',value,re.I):
            if not re.search(r'(?:我(?:希望|喜欢|偏好|习惯)|以后|每次|始终).{0,12}(?:用(?:中|英)文|使用(?:中|英)文|简短|简洁|详细)\s*[。.!！]?$',text):continue
        return name
    return key if key.startswith('task:') else ''


def canonical(text, key=''):
    name = facet(text, key)
    value = normalized(text).strip('。！.! ')
    if name == 'style.language':
        if re.search(r'中英对照|双语|bilingual',value) and not re.search(r'(?:不要|不用|禁止|避免).{0,5}(?:中英对照|双语|bilingual)',value):return 'bilingual'
        positive=set();negative=set()
        for match in re.finditer(r'英文|英语|english|中文|汉语|chinese',value,re.I):
            language='en' if re.search(r'英文|英语|english',match[0],re.I) else 'zh'
            prefix=re.split(r'[，,。.;；]',value[:match.start()])[-1][-12:]
            if re.search(r'(?:不要|不用|不再|不使用|别|禁止|避免|勿|not).{0,5}$',prefix):negative.add(language)
            else:positive.add(language)
        if len(positive)==1:return next(iter(positive))
        if not positive and negative:return 'avoid_'+'_'.join(sorted(negative))
        return value
    if name == 'style.length':
        return 'detailed' if re.search(r'详细|detailed|不要简短|不再简短', value) else 'concise'
    if name == 'style.structure':
        return 'conclusion_first' if re.search(r'先.{0,5}结论|结论在前', value) else value
    if name == 'identity.name':
        value = re.sub(r'^.*?(?:叫我|我叫|我的名字(?:是|叫|改为|改成)|我的称呼(?:是|改为|改成)|call me|name is)\s*', '', value)
        value = re.sub(r'[，,；;].*$', '', value)
    return value


def config(conn, uid):
    row = conn.execute('SELECT * FROM memory_lifecycle_settings WHERE user_id=?', (uid,)).fetchone()
    return {key: value for key, value in dict(row).items() if key != 'user_id'} if row else {
        'session_days': 7, 'episode_days': 30, 'auto_promote': 1, 'auto_cooldown': 1, 'cross_session': 1,
        'semantic_reflection':0,'reflection_budget':2,'version': 0}


def context_key(project_id, topics):
    return dumps([project_id or '', sorted(json.loads(topics) if isinstance(topics,str) else topics or [])])


def current_key(conn,cid):
    from .memory import context_for
    context=context_for(conn,cid)
    return context_key(context['project_id'],context['topics'])


def message_scope(conn,mid):
    row=conn.execute('SELECT context_key,learning_allowed,generation FROM memory_message_context WHERE message_id=?',(mid,)).fetchone()
    if not row or not row['context_key']:
        return {'known':False,'key':'','project_id':None,'topics':[],'learning_allowed':False,'generation':row['generation'] if row else 0}
    value=json.loads(row['context_key'])
    return {'known':True,'key':row['context_key'],'project_id':value[0] or None,'topics':value[1],'learning_allowed':bool(row['learning_allowed']),'generation':row['generation']}


def generation(conn,uid):
    row=conn.execute('SELECT generation FROM memory_forget_boundaries WHERE user_id=?',(uid,)).fetchone()
    return row['generation'] if row else 0


def working_for(conn,cid):
    row=conn.execute('SELECT * FROM memory_working_frames WHERE conversation_id=? AND context_key=?',(cid,current_key(conn,cid))).fetchone()
    return dict(row) if row else {'content':'','version':0,'locked':False,'updated_at':0}


def put_working(conn,cid,content,locked=False):
    old=conn.execute('SELECT version FROM memory_working WHERE conversation_id=?',(cid,)).fetchone()
    version=(old['version'] if old else 0)+1
    now=int(time.time())
    conn.execute('''INSERT INTO memory_working VALUES(?,?,?,?,?) ON CONFLICT(conversation_id)
        DO UPDATE SET content=excluded.content,version=excluded.version,locked=excluded.locked,updated_at=excluded.updated_at''',
        (cid,content,version,int(locked),now))
    conn.execute('''INSERT INTO memory_working_frames VALUES(?,?,?,?,?,?) ON CONFLICT(conversation_id,context_key)
        DO UPDATE SET content=excluded.content,version=excluded.version,locked=excluded.locked,updated_at=excluded.updated_at''',
        (cid,current_key(conn,cid),content,version,int(locked),now))
    return version


def event(conn, uid, mid, action, reason):
    conn.execute('INSERT INTO memory_events VALUES(?,?,?,?,?,?)', (ident(), uid, mid, action, reason, int(time.time())))
    # Audit metadata contains no remembered text; keep a bounded local ledger.
    if conn.execute('SELECT count(*) FROM memory_events WHERE user_id=?',(uid,)).fetchone()[0]>2100:
        conn.execute('DELETE FROM memory_events WHERE user_id=? AND id NOT IN (SELECT id FROM memory_events WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 2000)', (uid, uid))


def semantics(conn, items):
    if not items:
        return []
    ids = json.dumps([item['id'] for item in items])
    meta = {r['memory_id']: dict(r) for r in conn.execute(
        'SELECT * FROM memory_semantics WHERE memory_id IN (SELECT value FROM json_each(?))', (ids,))}
    return [{**item, **{key: value for key, value in meta.get(item['id'], {}).items() if key not in ('memory_id', 'version')},
             'lifecycle_version': meta.get(item['id'], {}).get('version', 1),
             'applies_to': json.loads(meta.get(item['id'], {}).get('applies_to', '[]'))} for item in items]


def admit(text, kind, requested='auto'):
    """A passing instruction is useful now without becoming a global preference."""
    if requested in ('turn', 'session'):
        return requested
    if TEMPORARY.search(text):
        if re.search(r'从(?:今天|明天)(?:起|开始)',text) and not TEMPORARY.search(re.sub(r'从(?:今天|明天)(?:起|开始)','',text)):return 'long_term'
        return 'turn' if re.search(r'本轮|只.*这轮|this turn|仅本次|只在本次', text, re.I) else 'session'
    if requested=='long_term':return 'long_term'
    if re.search(r'本项目|这个项目|本次项目', text) or STABLE.search(text):
        return 'long_term'
    if kind in ('preference', 'constraint', 'decision') and re.search(r'我(?:偏好|习惯|喜欢)|我们(?:决定|采用)', text):
        return 'long_term'
    return 'session'


def set_semantics(conn, mid, *, admission='explicit', tier=None, shared=None, applies_to=None):
    row = conn.execute('''SELECT m.*,d.origin,coalesce(p.semantic_key,'') semantic_key FROM personal_memories m
        JOIN memory_details d ON d.memory_id=m.id LEFT JOIN memory_policies p ON p.memory_id=m.id WHERE m.id=?''', (mid,)).fetchone()
    if not row:
        return
    now = int(time.time())
    c = config(conn, row['user_id'])
    tier = tier or ('episodic' if row['origin'] == 'task' or row['kind'] == 'episode' else 'long_term')
    days = c['episode_days'] if tier == 'episodic' else (180 if row['kind'] in ('preference', 'constraint', 'skill') else 90)
    review_after = None if admission in ('manual', 'explicit') and tier == 'long_term' else now + days * 86400
    conn.execute('''UPDATE memory_semantics SET tier=?,admission=?,shared=coalesce(?,shared),
        applies_to=coalesce(?,applies_to),last_confirmed_at=?,review_after=?,status='active',facet=?,canonical_value=?,version=version+1
        WHERE memory_id=?''', (tier, admission, int(shared) if shared is not None else None,
        dumps(applies_to) if applies_to is not None else None, now, review_after,
        '' if row['origin'] in ('resource','source_claim') else facet(row['content'],row['semantic_key']),
        '' if row['origin'] in ('resource','source_claim') else canonical(row['content'],row['semantic_key']), mid))


def session_item(conn, uid, cid, mid, text, kind='fact', lifetime='session', slot=''):
    from .memory_learning import SECRET, REJECT_INSTRUCTION
    if not text.strip() or SECRET.search(text) or REJECT_INSTRUCTION.search(text):
        return None
    source = conn.execute('''SELECT m.content,m.created_at FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE m.id=? AND m.conversation_id=? AND c.user_id=? AND m.role='user' AND m.status='complete' ''', (mid, cid, uid)).fetchone()
    if not source or text not in source['content']:
        raise ValueError('短期记忆需要当前账号可核对的用户原话')
    if blocked_fragment(conn, uid, mid, text):
        return None
    now = int(time.time())
    key = ident()
    expires = source['created_at'] + config(conn, uid)['session_days'] * 86400
    if expires <= now:
        return None
    changed=conn.execute('''INSERT OR IGNORE INTO memory_session_items
        (id,user_id,conversation_id,source_message_id,kind,content,slot,lifetime,created_at,expires_at,context_key)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (key, uid, cid, mid, kind, text[:2000], slot, lifetime, source['created_at'], expires,message_scope(conn,mid)['key'])).rowcount
    if changed:conn.execute('DELETE FROM memory_lifecycle_runs WHERE user_id=?',(uid,))
    saved = conn.execute('SELECT id FROM memory_session_items WHERE conversation_id=? AND source_message_id=? AND kind=? AND content=?', (cid, mid, kind, text[:2000])).fetchone()
    conn.execute('''DELETE FROM memory_session_items WHERE conversation_id=? AND id NOT IN
        (SELECT id FROM memory_session_items WHERE conversation_id=? ORDER BY kind='goal' DESC,created_at DESC,rowid DESC LIMIT 80)''', (cid, cid))
    return saved['id'] if saved else None


def blocked_fragment(conn, uid, mid, quote):
    from .memory_store import digest
    if message_scope(conn,mid)['generation']<generation(conn,uid):return True
    rules=list(conn.execute('SELECT * FROM memory_forgotten_spans WHERE user_id=? AND source_id=?',(uid,mid)))
    if any(row['quote_hash']==digest(quote) for row in rules):return True
    source=conn.execute('SELECT content FROM conversation_messages WHERE id=?',(mid,)).fetchone() if rules else None
    if source:
        start=source['content'].find(quote)
        return start>=0 and any(start<row['end_offset'] and start+len(quote)>row['start_offset'] for row in rules)
    return False


def capture_session(conn, uid, cid, mid):
    """Keep the durable goal and successive requests instead of the last query only."""
    from .memory_learning import SECRET, REJECT_INSTRUCTION
    row = conn.execute('SELECT content,created_at FROM conversation_messages WHERE id=? AND conversation_id=?', (mid, cid)).fetchone()
    if not row:
        return
    source_key=message_scope(conn,mid)['key']
    cleaned = re.sub(r'```[\s\S]*?```', '[代码片段保留在原对话]', row['content'])
    cleaned = SECRET.sub('[凭证已省略]', cleaned)
    if REJECT_INSTRUCTION.search(cleaned) or re.match(r'\s*(?:忘记|忘掉|删除|清空)', cleaned):
        return
    if row['created_at'] + config(conn, uid)['session_days'] * 86400 <= int(time.time()):
        return
    latest=conn.execute("SELECT id FROM conversation_messages WHERE conversation_id=? AND role='user' ORDER BY rowid DESC LIMIT 1",(cid,)).fetchone()
    if latest and latest['id']==mid:
        now=int(time.time())
        conn.execute('UPDATE memory_session_items SET expires_at=? WHERE conversation_id=? AND context_key=? AND expires_at>?',
            (now+config(conn,uid)['session_days']*86400,cid,source_key,now))
    if re.search(r'换个话题|另一个问题|重新开始|暂不讨论前面|先不做前面',cleaned):
        conn.execute('DELETE FROM memory_session_items WHERE conversation_id=? AND context_key=?',(cid,source_key))
        conn.execute('DELETE FROM memory_checkpoints WHERE conversation_id=?',(cid,))
    if re.fullmatch(r'\s*(?:你好|谢谢|好的|收到|hi|hello|thanks)[。！!\s]*',cleaned,re.I):return
    # Requests are explicitly labelled as requests; they are not promoted facts.
    if cleaned == row['content'] and not blocked_fragment(conn, uid, mid, cleaned):
        session_item(conn, uid, cid, mid, cleaned[:1200], 'request', 'session')
        if not conn.execute("SELECT 1 FROM memory_session_items WHERE conversation_id=? AND context_key=? AND kind='goal'",(cid,source_key)).fetchone() and re.search(r'帮我|需要|我要|我想|请|希望|目标|计划|准备',cleaned):
            session_item(conn,uid,cid,mid,cleaned[:1200],'goal','session')


def session_state(conn, uid, cid, now=None):
    now = int(time.time()) if now is None else now
    latest = conn.execute("SELECT id FROM conversation_messages WHERE conversation_id=? AND role='user' ORDER BY rowid DESC LIMIT 1", (cid,)).fetchone()
    last_id = latest['id'] if latest else None
    entries = [dict(r) for r in conn.execute('''SELECT s.* FROM memory_session_items s JOIN conversations c ON c.id=s.conversation_id
        WHERE s.user_id=? AND s.conversation_id=? AND c.user_id=? AND s.expires_at>? AND s.context_key=? ORDER BY s.created_at,s.rowid''', (uid, cid, uid, now,current_key(conn,cid)))
        if r['lifetime'] != 'turn' or r['source_message_id'] == last_id]
    from .memory_reliability import overlay_sessions
    entries=overlay_sessions(conn,entries)
    # Newer values for a session slot supersede older ones, without deleting history.
    slots = {e['slot']: e['id'] for e in entries if e['slot']}
    entries = [e for e in entries if not e['slot'] or slots[e['slot']] == e['id']]
    requests = [e for e in entries if e['kind'] == 'request']
    goals=[e for e in entries if e['kind']=='goal']
    goal = goals[0]['content'] if goals else requests[0]['content'] if requests else ''
    latest_request = requests[-1]['content'] if requests else ''
    facts = [e for e in entries if e['kind'] not in ('request','goal')][-12:]
    checkpoint = conn.execute("SELECT data FROM memory_checkpoints WHERE conversation_id=? AND json_extract(data,'$._context_key')=? ORDER BY version DESC LIMIT 1", (cid,current_key(conn,cid))).fetchone()
    data = json.loads(checkpoint['data']) if checkpoint else {}
    if not entries:
        data = {}
    sources={'goal':(goals or requests)[0]['id'] if goals or requests else None,
             'current_request':requests[-1]['id'] if requests else None}
    inherited=data.get('_sources',{})
    checkpoint_ids=list(dict.fromkeys([*data.get('_checkpoint_sources',[]),*inherited.values(),*[e.get('id') for e in data.get('facts',[])]]))
    return {'goal': goal, 'current_request': latest_request,'_sources':sources,'_checkpoint_sources':[key for key in checkpoint_ids if isinstance(key,str)],
            'recent_requests': [{'text':e['content'], 'source_message_id':e['source_message_id']} for e in requests[-4:]],
            'facts': [{'id':e['id'],'kind':e['kind'],'content':e['content'],'source_message_id':e['source_message_id'],
                       'lifetime':e['lifetime'],'expires_at':e['expires_at'],'edited_by_user':e['edited_by_user'],'edit_version':e['edit_version']} for e in facts],
            'decisions':data.get('decisions', []), 'open_questions':data.get('open_questions', []),
            'completed_steps':data.get('completed_steps', []), 'next_steps':data.get('next_steps', [])}


def render_working(state, status=''):
    parts = []
    for key, label in (('goal', '会话目标'), ('current_request', '当前请求'), ('facts', '当前会话条件'),
                       ('decisions', '已确认决定'), ('open_questions', '待澄清'), ('completed_steps', '已报告的进展'), ('next_steps', '下一步')):
        value = state.get(key)
        if not value:
            continue
        if isinstance(value, list):
            value = '\n'.join('• ' + (item.get('content') or item.get('text') or '') if isinstance(item, dict) else '• ' + item for item in value)
        parts.append(label + '：\n' + value)
    if status:
        parts.append('回复状态：' + status)
    return '\n\n'.join(parts)[:4000]


def checkpoint(conn, uid, cid, mid, data, expected_version=None):
    old = working_for(conn,cid)
    if old and old['locked']:
        raise ValueError('本人已锁定工作记忆')
    if expected_version is not None and expected_version != (old['version'] if old else 0):
        raise ValueError('工作记忆版本已变化')
    state = session_state(conn, uid, cid)
    # Partial section merge: omitted sections retain the previous checkpoint.
    for key in ('decisions', 'open_questions', 'completed_steps', 'next_steps'):
        if key in data and data[key] is not None:
            state[key] = data[key]
    state['_context_key']=current_key(conn,cid)
    version = put_working(conn,cid,render_working(state))
    now = int(time.time())
    conn.execute('INSERT INTO memory_checkpoints VALUES(?,?,?,?,?)', (cid, version, dumps(state), mid, now))
    conn.execute('DELETE FROM memory_checkpoints WHERE conversation_id=? AND version NOT IN (SELECT version FROM memory_checkpoints WHERE conversation_id=? ORDER BY version DESC LIMIT 30)', (cid, cid))
    return version


def recall_gate(conn, uid, cid, items, now=None):
    now = int(time.time()) if now is None else now
    settings = config(conn, uid)
    allowed, excluded = [], []
    enriched=items if all('lifecycle_version' in item for item in items) else semantics(conn,items)
    for item in enriched:
        same = item.get('source_conversation_id') == cid
        reason = item.get('status') if item.get('status') in ('cooling', 'needs_review', 'archived') else None
        if not reason and not same and (not settings['cross_session'] or not item['shared']):
            reason = 'cross_session_disabled'
        if not reason and item.get('review_after') and item['review_after'] <= now and not item.get('locked'):
            reason = 'needs_review'
        if reason:
            excluded.append({'id': item['id'], 'reason': reason})
        else:
            allowed.append(item)
    return allowed, excluded


def task_memory_ids(conn,uid):
    """Follow provenance, including summaries that no longer have a task origin label."""
    return {r['id'] for r in conn.execute('''WITH RECURSIVE blocked(id) AS (
        SELECT m.id FROM personal_memories m JOIN memory_details d ON d.memory_id=m.id
        WHERE m.user_id=? AND (d.origin='task' OR EXISTS(SELECT 1 FROM memory_evidence e WHERE e.memory_id=m.id AND e.source_kind='task'))
        UNION SELECT l.child_id FROM memory_links l JOIN blocked b ON b.id=l.parent_id WHERE l.relation='derived_from'
        ) SELECT id FROM blocked''',(uid,))}


def source_access(conn,uid,items,access):
    """Derived indexes inherit every source permission, across all generations."""
    blocked={key:'schedule_disabled' for key in task_memory_ids(conn,uid)} if not access.get('schedule',True) else {}
    if not access.get('library',True):
        for row in conn.execute('''SELECT r.memory_id,r.source_kind,s.conversation_id FROM memory_resource_sources r
            JOIN personal_memories m ON m.id=r.memory_id LEFT JOIN conversation_sources s ON r.source_kind='resource_material' AND s.id=r.source_id
            WHERE m.user_id=? AND r.source_kind IN ('resource_notice','resource_material')''',(uid,)):
            if row['source_kind']=='resource_notice' or not (access.get('attachments',True) and row['conversation_id']==access.get('_memory_conversation_id')):
                blocked[row['memory_id']]='source_disabled'
    if blocked:
        for row in conn.execute('''WITH RECURSIVE denied(id) AS (SELECT value FROM json_each(?)
            UNION SELECT child_id FROM memory_links JOIN denied ON parent_id=denied.id WHERE relation='derived_from') SELECT id FROM denied''',(dumps(list(blocked)),)):
            blocked.setdefault(row['id'],'source_disabled')
    return [e for e in items if e['id'] not in blocked],[{'id':e['id'],'reason':blocked[e['id']]} for e in items if e['id'] in blocked]


def remember_exposure(conn, uid, assistant_id, report, used_ids=None):
    used = set(used_ids or [])
    for source in report:
        if source.get('evidence_kind') != 'memory':
            continue
        mid = source.get('memory_id') or source['id'].removeprefix('memory-')
        row = conn.execute('SELECT version FROM personal_memories WHERE id=? AND user_id=?', (mid, uid)).fetchone()
        if row:
            conn.execute('''INSERT INTO memory_usage VALUES(?,?,?,?,?) ON CONFLICT(message_id,memory_id)
                DO UPDATE SET outcome=excluded.outcome''',
                (assistant_id, mid, source.get('memory_version',row['version']), 'used' if mid in used else 'exposed', int(time.time())))


def feedback(conn, uid, assistant_id, mid, outcome, version):
    row = conn.execute('''SELECT m.version,u.memory_version FROM memory_usage u JOIN personal_memories m ON m.id=u.memory_id
        JOIN conversation_messages a ON a.id=u.message_id JOIN conversations c ON c.id=a.conversation_id
        WHERE u.message_id=? AND u.memory_id=? AND c.user_id=? AND m.user_id=?''', (assistant_id, mid, uid, uid)).fetchone()
    if not row or row['version'] != version or row['memory_version']!=version:
        raise ValueError('该记忆不在这次回答的实际召回中，或内容版本已变化')
    conn.execute('INSERT INTO memory_feedback VALUES(?,?,?,?) ON CONFLICT(message_id,memory_id) DO UPDATE SET outcome=excluded.outcome,created_at=excluded.created_at', (assistant_id, mid, outcome, int(time.time())))
    conn.execute('INSERT OR REPLACE INTO memory_feedback_versions VALUES(?,?,?)',(assistant_id,mid,version))
    positive = conn.execute("SELECT count(*) FROM memory_feedback f JOIN memory_feedback_versions v USING(message_id,memory_id) WHERE f.memory_id=? AND v.memory_version=? AND f.outcome='helpful'", (mid,version)).fetchone()[0]
    negative = conn.execute("SELECT count(*) FROM memory_feedback f JOIN memory_feedback_versions v USING(message_id,memory_id) WHERE f.memory_id=? AND v.memory_version=? AND f.outcome IN ('irrelevant','outdated')", (mid,version)).fetchone()[0]
    conn.execute('''UPDATE memory_semantics SET positive=?,negative=?,
        status=CASE WHEN ?='outdated' THEN 'needs_review' ELSE status END,version=version+1 WHERE memory_id=?''', (positive, negative, outcome, mid))
    event(conn, uid, mid, 'feedback', outcome)
    conn.execute('DELETE FROM memory_lifecycle_runs WHERE user_id=?',(uid,))
    return {'positive': positive, 'negative': negative, 'status': 'needs_review' if outcome == 'outdated' else 'recorded'}


def before_forget(conn, uid, item):
    """Remember only source positions/hashes, so old history cannot relearn a fact."""
    from .memory_store import digest
    mids = set()
    for evidence in conn.execute("SELECT * FROM memory_evidence WHERE memory_id=? AND source_kind='message'", (item['id'],)):
        source = conn.execute('SELECT content,conversation_id FROM conversation_messages WHERE id=?', (evidence['source_id'],)).fetchone()
        if not source or not evidence['quote']:
            continue
        start = source['content'].find(evidence['quote'])
        if start < 0:
            continue
        conn.execute('INSERT OR IGNORE INTO memory_forgotten_spans VALUES(?,?,?,?,?,?,?)',
            (uid, evidence['source_id'], digest(source['content']), digest(evidence['quote']), start, start+len(evidence['quote']), int(time.time())))
        mids.add(source['conversation_id'])
        conn.execute('DELETE FROM memory_session_items WHERE source_message_id=? AND instr(content,?)>0', (evidence['source_id'], evidence['quote']))
    for cid in mids:
        conn.execute('DELETE FROM memory_checkpoints WHERE conversation_id=?', (cid,))
        working = conn.execute('SELECT content,locked FROM memory_working WHERE conversation_id=?', (cid,)).fetchone()
        if working and item['content'] in working['content']:
            conn.execute('UPDATE memory_working SET content=?,version=version+1 WHERE conversation_id=?',
                (working['content'].replace(item['content'], '[已按本人要求遗忘]'), cid))
        conn.execute("UPDATE memory_working_frames SET content=replace(content,?,'[已按本人要求遗忘]'),version=version+1 WHERE conversation_id=? AND instr(content,?)>0",(item['content'],cid,item['content']))
    event(conn, uid, item['id'], 'forgotten', '本人撤销；删除来源片段的记忆用途')


def filter_history(conn, uid, messages):
    from .memory_store import digest
    ids = dumps([m.get('id') for m in messages if m.get('id')])
    rules = {}
    boundary=conn.execute('SELECT * FROM memory_forget_boundaries WHERE user_id=?',(uid,)).fetchone()
    before_boundary=set()
    if boundary:
        before_boundary={r['id'] for r in conn.execute('''SELECT m.id FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id
            LEFT JOIN memory_message_context s ON s.message_id=CASE WHEN m.role='user' THEN m.id ELSE m.parent_id END
            WHERE c.user_id=? AND m.id IN (SELECT value FROM json_each(?)) AND m.id<>?
            AND coalesce(s.generation,-1)<?''',(uid,ids,boundary['last_request_id'],boundary['generation']))}
    for row in conn.execute('SELECT * FROM memory_forgotten_spans WHERE user_id=? AND source_id IN (SELECT value FROM json_each(?))', (uid, ids)):
        rules.setdefault(row['source_id'], []).append(dict(row))
    withdrawn_answers={r['id'] for r in conn.execute('''SELECT m.id FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE c.user_id=? AND m.role='assistant' AND m.id IN (SELECT value FROM json_each(?))
        AND EXISTS(SELECT 1 FROM memory_forgotten_spans f WHERE f.user_id=? AND f.source_id=m.parent_id)''',(uid,ids,uid))}
    withdrawn_answers.update(r['message_id'] for r in conn.execute('SELECT message_id FROM memory_withdrawn_answers WHERE user_id=? AND message_id IN (SELECT value FROM json_each(?))',(uid,ids)))
    withdrawn_answers.update(r['message_id'] for r in conn.execute('''SELECT u.message_id FROM memory_usage u JOIN personal_memories m ON m.id=u.memory_id
        WHERE m.user_id=? AND u.message_id IN (SELECT value FROM json_each(?)) AND u.memory_version<>m.version''',(uid,ids)))
    result = []
    for item in messages:
        value = dict(item)
        if item.get('id') in before_boundary or item.get('id') in withdrawn_answers:
            value['content']='[此历史内容的记忆用途已由本人撤销，本轮不用于推断或记忆]'
            result.append(value)
            continue
        matches = rules.get(item.get('id'), [])
        if matches:
            content = value['content']
            if any(row['source_hash'] != digest(content) for row in matches):
                value['content'] = '[此历史消息包含已撤销的记忆来源，当前不用于推断或学习]'
            else:
                intervals=[]
                for rule in sorted(matches,key=lambda r:r['start_offset']):
                    if intervals and rule['start_offset']<=intervals[-1][1]:intervals[-1][1]=max(intervals[-1][1],rule['end_offset'])
                    else:intervals.append([rule['start_offset'],rule['end_offset']])
                for start,end in reversed(intervals):
                    content = content[:start] + '[此片段已按本人要求遗忘]' + content[end:]
                value['content'] = content
        result.append(value)
    return result


def natural_forget(conn, uid, cid, mid, text):
    from .memory_learning import UNCERTAIN
    from .memory_store import forget_memory
    match = re.match(r'^\s*(?:请|帮我|麻烦|现在|我想让你|我希望你|，|,|\s)*(?:忘记|忘掉|删除|清空|不再使用|别再使用)\s*(.{2,160}?)\s*[。！.!]*$', text)
    if not match or UNCERTAIN.search(text) or re.search(r'[“「『>]|```', text):
        return []
    target = match.group(1).strip('。！.! ')
    all_items = re.fullmatch(r'(?:我的|所有|全部|之前的|以前的|个人|长期|\s)*(?:记忆|偏好)(?:全部|所有)?', target)
    from .memory_policy import rows_for, effective
    from .memory import context_for
    entries = rows_for(conn, uid)
    if not all_items and not re.search(r'全部|所有|跨项目', target):
        context=context_for(conn,cid)
        entries=[e for e in entries if e['scope']=='global' or e['scope']=='project' and e['project_id']==context['project_id'] or e['scope']=='topic' and e['topic'] in context['topics']]
    def statement(value):
        value=re.sub(r'^(?:请|帮我|麻烦|\s)*(?:记住|记一下|记下来|remember)\s*[，,:：]?\s*','',value,flags=re.I)
        return re.sub(r'\s+','',normalized(value)).strip('。！.!，,;； ')
    selected = entries if all_items else [e for e in entries if statement(e['content'])==statement(target)
        or e.get('semantic_key') and e['semantic_key'] in target
        or facet(target) and facet(target) == facet(e['content'], e.get('semantic_key', ''))]
    if not all_items and len(selected) > 6:
        return [{'status':'rejected','reason':'匹配多条记忆，请在记忆工作台确认删除范围'}]
    if not all_items and not selected:
        return [{'status':'rejected','reason':'没有找到明确对应的记忆，请在工作台按条目选择，或说明要忘记的原内容。'}]
    results = []
    for entry in selected:
        forget_memory(conn, uid, entry)
        results.append({'id': entry['id'], 'status': 'forgotten'})
    if all_items:
        # Include existing sources whose durable jobs have not run yet. Clearing
        # memory must not be undone ten seconds later by an old queued event.
        for kind,sql in (
            ('task','SELECT id FROM tasks WHERE user_id=?'),
            ('resource_project','SELECT id FROM memory_projects WHERE user_id=?'),
            ('resource_notice','SELECT s.id FROM sources s JOIN notices n ON n.id=s.notice_id WHERE n.user_id=?'),
            ('resource_material','SELECT s.id FROM conversation_sources s JOIN conversations c ON c.id=s.conversation_id WHERE c.user_id=?')):
            conn.execute('INSERT OR IGNORE INTO memory_blocked_sources SELECT ?,?,id,? FROM ('+sql+')', (uid,kind,int(time.time()),uid))
        # A generation boundary also covers old messages that were never selected
        # as memories. Future messages get the new generation even if rowids or
        # timestamps are reused, so deleting chats cannot poison future learning.
        conn.execute('''INSERT INTO memory_forget_boundaries VALUES(?,1,?) ON CONFLICT(user_id)
            DO UPDATE SET generation=generation+1,last_request_id=excluded.last_request_id''',(uid,mid))
        conn.execute('DELETE FROM memory_session_items WHERE user_id=?',(uid,))
        conn.execute('DELETE FROM memory_checkpoints WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)',(uid,))
        conn.execute('DELETE FROM memory_working_frames WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)',(uid,))
        conn.execute("UPDATE memory_working SET content='',locked=0,version=version+1 WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)",(uid,))
        event(conn,uid,None,'forgotten_all','本人清空长期、短期与工作记忆，并阻止从旧历史重新学习')
        results.append({'status':'all_forgotten'})
    return results


def maintain(conn, uid, now=None):
    """Bounded, model-free ageing and repeated-evidence promotion; never self-prove."""
    from .memory_store import settings_for, insert_memory, decorate,MAX_MEMORIES
    from .memory_learning import classify, semantic_key, scope_value, direct_quote
    from .memory import context_for
    now = int(time.time()) if now is None else now
    if conn.execute('SELECT 1 FROM conversations WHERE user_id=? AND processing_token IS NOT NULL', (uid,)).fetchone():
        return {'deferred': True, 'promoted': 0, 'cooled': 0, 'expired_session': 0}
    settings, options = settings_for(conn, uid), config(conn, uid)
    conn.execute("UPDATE memory_reflection_jobs SET snapshot='{}' WHERE user_id=? AND state IN ('done','failed','cancelled') AND finished_at<? AND snapshot<>'{}'",(uid,now-30*86400))
    expired = conn.execute('DELETE FROM memory_session_items WHERE user_id=? AND expires_at<=?', (uid, now)).rowcount
    cooled = 0
    if options['auto_cooldown'] and settings['mode'] in ('auto', 'review'):
        rows = conn.execute('''SELECT s.memory_id FROM memory_semantics s JOIN personal_memories m ON m.id=s.memory_id
            JOIN memory_details d ON d.memory_id=m.id WHERE m.user_id=? AND s.review_after<=?
            AND s.status='active' AND d.locked=0 AND d.origin<>'manual' LIMIT 100''', (uid, now)).fetchall()
        for row in rows:
            conn.execute("UPDATE memory_semantics SET status='cooling',version=version+1 WHERE memory_id=?", (row['memory_id'],))
            event(conn, uid, row['memory_id'], 'cooling', '长期未确认，保留记录，暂停自动调用')
            cooled += 1
    promoted = 0
    if settings['mode'] == 'auto' and options['auto_promote']:
        # Two distinct conversations are independent corroboration; repetition
        # within one conversation and exposure counters are deliberately excluded.
        candidates = [dict(r) for r in conn.execute('''SELECT s.* FROM memory_session_items s
            WHERE s.user_id=? AND s.expires_at>? AND s.promoted_id IS NULL AND s.lifetime='session'
            AND NOT EXISTS(SELECT 1 FROM memory_session_edits e WHERE e.session_id=s.id)
            AND s.kind IN ('preference','constraint','fact') ORDER BY s.created_at,s.id LIMIT 800''', (uid, now))]
        groups = {}
        for entry in candidates:
            name = facet(entry['content'])
            if not name or not direct_quote(entry['content'], entry['content']) or not entry['context_key']:
                continue
            source_context=json.loads(entry['context_key'])
            context={'project_id':source_context[0] or None,'topics':source_context[1]}
            value = scope_value(context, entry['content'], 'current')
            groups.setdefault((*scope_key(value), name, canonical(entry['content'])), []).append(entry)
        for group in groups.values():
            if promoted >= 8 or len({e['conversation_id'] for e in group}) < 2:
                continue
            if conn.execute('SELECT count(*) FROM personal_memories WHERE user_id=?',(uid,)).fetchone()[0]>=MAX_MEMORIES:break
            first = group[-1]
            source_context=json.loads(first['context_key'])
            context={'project_id':source_context[0] or None,'topics':source_context[1]}
            if not context['project_id'] and len(context['topics'])>1:continue
            value = {**scope_value(context, first['content']), 'content':first['content'],
                'kind':classify(first['content']), 'semantic_key':semantic_key(first['content']),
                'source_conversation_id':first['conversation_id']}
            existing = conn.execute('''SELECT m.id,m.active,s.status,d.review_status FROM memory_semantics s JOIN personal_memories m ON m.id=s.memory_id
                JOIN memory_details d ON d.memory_id=m.id
                WHERE m.user_id=? AND s.facet=? AND s.canonical_value=? AND m.scope=? AND m.project_id IS ? AND m.topic=?''',
                (uid, facet(first['content']), canonical(first['content']), value['scope'], value['project_id'], value['topic'])).fetchone()
            if existing and (not existing['active'] or existing['status']!='active' or existing['review_status']!='accepted'):continue
            peer=conn.execute('''SELECT 1 FROM memory_semantics s JOIN personal_memories m ON m.id=s.memory_id
                WHERE m.user_id=? AND s.facet=? AND s.canonical_value<>? AND m.scope=? AND m.project_id IS ? AND m.topic=? AND m.active=1''',
                (uid,facet(first['content']),canonical(first['content']),value['scope'],value['project_id'],value['topic'])).fetchone()
            key = existing['id'] if existing else insert_memory(conn, uid, value, origin='automatic', locked=False,review='pending' if peer else 'accepted',
                evidence=[{'source_kind':'message','source_id':e['source_message_id'],'quote':e['content']} for e in group])
            if key:
                if not existing:set_semantics(conn, key, admission='repeated')
                for e in group:
                    conn.execute('UPDATE memory_session_items SET promoted_id=? WHERE id=?', (key,e['id']))
                event(conn, uid, key, 'promoted', '来自不同会话的同一稳定陈述')
                promoted += 1
    report = {'promoted':promoted,'cooled':cooled,'expired_session':expired,'deferred':False}
    conn.execute('INSERT INTO memory_lifecycle_runs VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET ran_at=excluded.ran_at,report=excluded.report', (uid, now, dumps(report)))
    from .memory_reflection import enqueue
    report['reflection_queued']=enqueue(conn,uid,now)
    return report
