"""Owner-scoped chat inputs, immutable quote snapshots and idempotent feedback.

Quotes are conversational context, never independent evidence. Client labels,
roles and arbitrary replacement text are not trusted.
"""
import hashlib
import json
import time
from fastapi import Depends,HTTPException
from pydantic import Field
from .db import dumps
from .models import Strict
from .genui_state import Interaction

EMOJIS=('👍','❤️','😂','🎉','🤔','😮','😢','🙏','✅','👀','🔥','😊')
TABLES={'message_quotes','message_emojis','message_input_receipts'}
SCHEMA="""
CREATE TABLE IF NOT EXISTS message_quotes(
 message_id TEXT PRIMARY KEY REFERENCES conversation_messages(id) ON DELETE CASCADE,
 reference_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), excerpt TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS message_emojis(
 message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
 emoji TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(message_id,emoji));
CREATE TABLE IF NOT EXISTS message_input_receipts(
 conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
 client_request_id TEXT NOT NULL,user_message_id TEXT NOT NULL UNIQUE REFERENCES conversation_messages(id) ON DELETE CASCADE,
 content_sha256 TEXT NOT NULL,PRIMARY KEY(conversation_id,client_request_id));
INSERT OR IGNORE INTO meta VALUES('message_interaction_schema_version','1');
"""

def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='message_interaction_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not TABLES.issubset(tables)):
        raise ValueError('聊天引用/输入回执版本不兼容或数据不完整')
    conn.executescript(SCHEMA)

class QuoteInput(Strict):
    message_id:str=Field(min_length=1,max_length=40)
    excerpt:str=Field(default='',max_length=2400)

class MessageInput(Strict):
    content:str=Field(min_length=1,max_length=6000)
    request_id:str=Field(min_length=16,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    source_ids:list[str]=Field(default_factory=list,max_length=100)
    reply_to:QuoteInput|None=None
    # UI selections are defined by the existing validated contract.
    ui_context:Interaction|None=None

class EmojiInput(Strict):
    emoji:str=Field(min_length=1,max_length=12)
    active:bool

def fragments(payload):
    extra=payload.additional_messages
    if payload.retry_message_id or payload.regenerate_message_id:
        if extra or payload.reply_to:raise HTTPException(422,'重新生成不能同时提交新消息或引用')
        return []
    if not payload.content.strip():raise HTTPException(422,'请写下希望助手处理的内容')
    items=[MessageInput(content=payload.content,request_id=payload.request_id,source_ids=payload.source_ids,
                        reply_to=payload.reply_to,ui_context=payload.ui_context),*extra]
    if any(not item.content.strip() for item in items):raise HTTPException(422,'不能发送空白消息')
    if len({item.request_id for item in items})!=len(items):raise HTTPException(422,'同批消息的请求编号不能重复')
    return items

def digest(item):
    return hashlib.sha256(dumps(item.model_dump()).encode()).hexdigest()

def check_replay(conn,cid,payload):
    items=fragments(payload)
    for item in items:
        row=conn.execute('SELECT content_sha256 FROM message_input_receipts WHERE conversation_id=? AND client_request_id=?',(cid,item.request_id)).fetchone()
        if not row and len(items)>1:raise HTTPException(409,'既有请求没有完整的这批消息回执，请先核对已收到的内容')
        if row and row[0]!=digest(item):raise HTTPException(409,'该消息编号已有不同内容，原消息已保留，请作为新消息发送修改')

def quote_snapshot(conn,cid,quote):
    if not quote:return None
    row=conn.execute('SELECT id,role,status,content FROM conversation_messages WHERE id=? AND conversation_id=?',(quote.message_id,cid)).fetchone()
    if not row:raise HTTPException(404,'引用消息不属于当前对话或已移除')
    if row['role'] not in {'user','assistant'} or row['status']!='complete':
        raise HTTPException(409,'请等这条消息完整结束后再引用；当前问题仍保留')
    text=' '.join(row['content'].split())
    excerpt=' '.join(quote.excerpt.split())
    if excerpt and excerpt not in text:raise HTTPException(422,'引用片段与原消息不一致，请重新选择原句')
    excerpt=excerpt or text[:2400]
    if not excerpt:raise HTTPException(422,'这条消息没有可引用的文字，可以直接选择它的界面继续提问')
    return {'message_id':row['id'],'role':row['role'],'excerpt':excerpt}

def validate_inputs(conn,cid,payload):
    items=fragments(payload)
    for item in items:
        receipt=conn.execute('SELECT content_sha256 FROM message_input_receipts WHERE conversation_id=? AND client_request_id=?',(cid,item.request_id)).fetchone()
        if receipt:
            if receipt[0]!=digest(item):raise HTTPException(409,'该消息编号已有不同内容，原消息已保留，请作为新消息发送修改')
            raise HTTPException(409,'部分消息已经收下，请先刷新核对回执，避免重复发送')
        quote_snapshot(conn,cid,item.reply_to)
        if item.ui_context:
            from .genui_state import submission_context
            try:submission_context(conn,cid,item.ui_context)
            except (ValueError,TypeError,KeyError):raise HTTPException(422,'当前界面选择未通过检查，原回复没有中断') from None
        for sid in set(item.source_ids):
            if not conn.execute('SELECT 1 FROM conversation_sources WHERE id=? AND conversation_id=?',(sid,cid)).fetchone():
                raise HTTPException(422,'附件不属于当前对话或已移除，原回复没有中断')
    return items

def persist_input(conn,cid,mid,item):
    conn.execute('INSERT INTO message_input_receipts VALUES(?,?,?,?)',(cid,item.request_id,mid,digest(item)))
    quote=quote_snapshot(conn,cid,item.reply_to)
    if quote:conn.execute('INSERT INTO message_quotes VALUES(?,?,?,?,?)',(mid,quote['message_id'],quote['role'],quote['excerpt'],int(time.time())))

def load_index(conn,cid):
    quotes={r['message_id']:{'message_id':r['reference_id'],'role':r['role'],'excerpt':r['excerpt']} for r in conn.execute(
        'SELECT q.* FROM message_quotes q JOIN conversation_messages m ON m.id=q.message_id WHERE m.conversation_id=?',(cid,))}
    receipts={r['user_message_id']:r['client_request_id'] for r in conn.execute('SELECT user_message_id,client_request_id FROM message_input_receipts WHERE conversation_id=?',(cid,))}
    emojis={}
    for row in conn.execute('SELECT e.message_id,e.emoji FROM message_emojis e JOIN conversation_messages m ON m.id=e.message_id WHERE m.conversation_id=? ORDER BY e.created_at,e.emoji',(cid,)):
        emojis.setdefault(row['message_id'],[]).append(row['emoji'])
    reactions={r['message_id']:r['value'] for r in conn.execute('SELECT r.message_id,r.value FROM reply_reactions r JOIN conversation_messages m ON m.id=r.message_id WHERE m.conversation_id=?',(cid,))}
    return quotes,receipts,emojis,reactions

def decorate(conn,item,index=None):
    if index is not None:
        quotes,receipts,emojis,reactions=index
        if item['id'] in quotes:item['reply_to']=quotes[item['id']]
        if item['id'] in receipts:item['client_request_id']=receipts[item['id']]
        item['emojis']=emojis.get(item['id'],[])
        item['reaction']=reactions.get(item['id'],0)
        return item
    quote=conn.execute('SELECT reference_id,role,excerpt FROM message_quotes WHERE message_id=?',(item['id'],)).fetchone()
    if quote:item['reply_to']={'message_id':quote['reference_id'],'role':quote['role'],'excerpt':quote['excerpt']}
    receipt=conn.execute('SELECT client_request_id FROM message_input_receipts WHERE user_message_id=?',(item['id'],)).fetchone()
    if receipt:item['client_request_id']=receipt[0]
    item['emojis']=[r[0] for r in conn.execute('SELECT emoji FROM message_emojis WHERE message_id=? ORDER BY created_at,emoji',(item['id'],))]
    return item

def install(app,db,user,own):
    @app.get('/api/conversations/{cid}/message-feedback')
    def feedback(cid:str,current=Depends(user)):
        with db.connect() as conn:
            own(conn,cid,current['id'])
            emojis={}
            for row in conn.execute('SELECT e.message_id,e.emoji FROM message_emojis e JOIN conversation_messages m ON m.id=e.message_id WHERE m.conversation_id=? ORDER BY e.message_id,e.created_at,e.emoji',(cid,)):
                emojis.setdefault(row['message_id'],[]).append(row['emoji'])
            reactions={row['message_id']:row['value'] for row in conn.execute('SELECT r.message_id,r.value FROM reply_reactions r JOIN conversation_messages m ON m.id=r.message_id WHERE m.conversation_id=? AND r.value<>0 ORDER BY r.message_id',(cid,))}
            return {'emojis':emojis,'reactions':reactions,'signature':hashlib.sha256(dumps([emojis,reactions]).encode()).hexdigest()[:24]}

    @app.put('/api/conversations/{cid}/messages/{mid}/emoji')
    def emoji(cid:str,mid:str,payload:EmojiInput,current=Depends(user)):
        if payload.emoji not in EMOJIS:raise HTTPException(422,'暂不支持这个表情')
        with db.connect(write=True) as conn:
            own(conn,cid,current['id'])
            row=conn.execute('SELECT status FROM conversation_messages WHERE id=? AND conversation_id=?',(mid,cid)).fetchone()
            if not row:raise HTTPException(404,'消息不存在或无权访问')
            if row['status']!='complete':raise HTTPException(409,'消息完整结束后才能附加表情')
            if payload.active:conn.execute('INSERT OR IGNORE INTO message_emojis VALUES(?,?,?)',(mid,payload.emoji,int(time.time())))
            else:conn.execute('DELETE FROM message_emojis WHERE message_id=? AND emoji=?',(mid,payload.emoji))
            return {'emojis':[r[0] for r in conn.execute('SELECT emoji FROM message_emojis WHERE message_id=? ORDER BY created_at,emoji',(mid,))]}
