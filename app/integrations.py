"""Opt-in platform adapters. Credentials remain server-side; no outgoing messages."""
import hashlib
from .usage_limits import check_count, check_storage, limits_for
from datetime import datetime
from html.parser import HTMLParser
import json
import re
import secrets
import threading
import time
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends,HTTPException,Query,Request
import httpx
from pydantic import Field

from .db import dumps,ident
from .documents import text_source
from .models import Strict
from .security import rate_limit,token_hash


class BindingConsent(Strict):
    receive_my_submissions: Literal[True]


class GroupConsent(Strict):
    receive_group_notices: Literal[True]


GROUP_TABLES = {'qq_group_codes','qq_authorized_groups','qq_group_subscriptions'}
GROUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS qq_group_codes(
 code_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 app_id TEXT NOT NULL,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS qq_authorized_groups(
 app_id TEXT NOT NULL,group_id TEXT NOT NULL,authorized_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 authorized_member TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(app_id,group_id));
CREATE TABLE IF NOT EXISTS qq_group_subscriptions(
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,app_id TEXT NOT NULL,group_id TEXT NOT NULL,
 member_id TEXT NOT NULL,created_at INTEGER NOT NULL,last_received_at INTEGER,
 PRIMARY KEY(user_id,app_id,group_id),UNIQUE(app_id,group_id,member_id),
 FOREIGN KEY(app_id,group_id) REFERENCES qq_authorized_groups(app_id,group_id) ON DELETE CASCADE);
INSERT OR IGNORE INTO meta VALUES('qq_group_schema_version','1');
"""


def initialize(conn):
    version=conn.execute("SELECT value FROM meta WHERE key='qq_group_schema_version'").fetchone()
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if version and (version[0]!='1' or not GROUP_TABLES.issubset(tables)):
        raise ValueError('QQ 群授权记录版本不兼容或缺少必要数据表')
    conn.executescript(GROUP_SCHEMA)
    from .group_delivery import initialize as initialize_group_delivery
    initialize_group_delivery(conn)
    from .publisher_sync import initialize as initialize_publisher
    initialize_publisher(conn)


def message_source(data, name):
    """Preserve bounded nested text and mark unavailable media explicitly."""
    parts = []
    incomplete = False
    budget = [0]
    def visit(node, depth=0):
        nonlocal incomplete
        budget[0] += 1
        if depth > 5 or budget[0] > 80:
            raise HTTPException(413, '消息嵌套过多，请转入原始通知')
        content = node.get('content', '')
        if isinstance(content, str) and content.strip():
            parts.append(content.strip())
        if node.get('attachments') or node.get('ark_data'):
            incomplete = True
        elements = node.get('msg_elements') or []
        if not isinstance(elements, list):
            incomplete = True
            return
        for child in elements:
            if isinstance(child, dict):
                visit(child, depth + 1)
    visit(data)
    text = '\n\n'.join(parts)
    if len(text) > 10000:
        raise HTTPException(413, '消息正文超过 10000 字，未截断保存')
    source = text_source(text, name)
    if incomplete:
        source.update(status='review', warning='已保存消息文字；图片、文件或卡片原件未取得，请补充关键附件。')
    if not source['sections']:
        source.update(status='failed', warning='此消息没有可读正文，附件尚未取得，请主动上传原文件。')
    return source


class ImportArticle(Strict):
    article_id: str = Field(min_length=1,max_length=256)
    index: int = Field(ge=0,le=20)


def qq_key(secret):
    seed=secret.encode()
    if not seed:
        raise ValueError('QQ 凭证未配置')
    while len(seed)<32:
        seed+=seed
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def verify_qq(secret,timestamp,signature,body):
    try:
        if not re.fullmatch(r'[0-9]{10,12}',timestamp) or abs(time.time()-int(timestamp))>300:
            return False
        qq_key(secret).public_key().verify(bytes.fromhex(signature),timestamp.encode()+body)
        return True
    except (ValueError,TypeError,InvalidSignature):
        return False


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.skip=0;self.has_media=False

    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','iframe'}:
            self.skip+=1
        if tag in {'img','video','audio','iframe'}:
            self.has_media=True
        if not self.skip and tag in {'p','div','li','br','tr','h1','h2','h3'}:
            self.parts.append('\n')

    def handle_endtag(self,tag):
        if tag in {'script','style','iframe'}:
            self.skip=max(0,self.skip-1)
        if not self.skip and tag in {'p','div','li','tr'}:
            self.parts.append('\n')

    def handle_data(self,data):
        if not self.skip:
            self.parts.append(data)


class PublisherClient:
    def __init__(self,settings):
        self.settings=settings;self.token='';self.expires=0;self.lock=threading.Lock()

    def request(self,path,payload,token=None):
        try:
            with httpx.Client(timeout=httpx.Timeout(20,connect=8),follow_redirects=False,trust_env=False) as client:
                with client.stream('POST','https://api.weixin.qq.com'+path,params={'access_token':token} if token else None,json=payload) as response:
                    if response.status_code!=200:
                        raise HTTPException(502,'微信接口暂时不可用，请稍后重试')
                    content=[];size=0
                    for part in response.iter_bytes():
                        size+=len(part)
                        if size>2000000:
                            raise HTTPException(502,'微信返回内容过大，请缩小文章批次')
                        content.append(part)
            data=json.loads(b''.join(content))
            if not isinstance(data,dict):
                raise ValueError('invalid response')
            code=data.get('errcode',0)
            if code not in (0,None):
                if code in {40014,42001}:
                    self.expires=0
                labels={48001:'发布账号没有文章读取权限',40164:'服务端 IP 未加入微信白名单',40125:'公众号密钥无效',40013:'公众号 AppID 无效',89503:'需要发布账号管理员确认本次接入',45009:'今日接口额度已用完',40014:'接口凭证已失效',42001:'接口凭证已过期'}
                raise HTTPException(502,labels.get(code,'微信接口返回业务错误')+f'（{code}），没有导入任何文章')
            return data
        except (httpx.HTTPError,ValueError,TypeError):
            raise HTTPException(502,'微信接口连接失败或返回异常，没有导入任何文章') from None

    def access_token(self):
        if not self.settings.wechat_publisher_app_id or not self.settings.wechat_publisher_secret:
            raise HTTPException(503,'尚未配置获授权发布账号的公众号接口凭证')
        with self.lock:
            if time.time()<self.expires:
                return self.token
            data=self.request('/cgi-bin/stable_token',{'grant_type':'client_credential','appid':self.settings.wechat_publisher_app_id,'secret':self.settings.wechat_publisher_secret,'force_refresh':False})
            if not isinstance(data.get('access_token'),str) or not data['access_token'] or not isinstance(data.get('expires_in'),int):
                raise HTTPException(502,'微信未返回有效的服务端凭证')
            self.token=data['access_token'];self.expires=time.time()+max(1,min(data['expires_in'],7200)-60)
            return self.token

    def articles(self,offset):
        data=self.request('/cgi-bin/freepublish/batchget',{'offset':offset,'count':10,'no_content':1},self.access_token())
        if not isinstance(data.get('item'),list):
            if data.get('total_count')==0:
                return {'items':[],'total':0,'next_offset':None}
            raise HTTPException(502,'微信文章列表格式异常')
        if not isinstance(data.get('total_count'),int) or data['total_count']<0:
            raise HTTPException(502,'微信文章数量字段异常')
        items=[]
        try:
            for group in data['item']:
                for index,article in enumerate(group['content']['news_item']):
                    if not article.get('is_deleted'):
                        items.append({'article_id':group['article_id'],'index':index,'title':article['title'],'updated_at':group.get('update_time')})
        except (KeyError,TypeError):
            raise HTTPException(502,'微信文章列表字段缺失') from None
        next_offset=offset+len(data['item'])
        return {'items':items,'total':data.get('total_count',0),'next_offset':next_offset if data['item'] and next_offset<data.get('total_count',0) else None}

    def article(self,article_id,index):
        data=self.request('/cgi-bin/freepublish/getarticle',{'article_id':article_id},self.access_token())
        try:
            article=data['news_item'][index]
            if article.get('is_deleted'):
                raise HTTPException(410,'文章已被发布方删除，未导入')
            html=article['content'];title=article['title']
            if not isinstance(html,str) or not isinstance(title,str) or len(html)>1000000:
                raise ValueError('invalid article')
            parser=ArticleText();parser.feed(html)
            body='\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
            if not body or len(body)>10000:
                raise HTTPException(422,'文章没有可用正文，或超过单则材料 10000 字上限。未静默截断，请由本人分段提交。')
            source=text_source(body,title[:150]+'.html');source.update(kind='html',content=html.encode(),sha256=hashlib.sha256(html.encode()).hexdigest(),status='review',warning='来自获授权发布账号。已保留 HTML 原件并提取文字；图片、外链与关联附件未下载，请核对并补齐。')
            return title[:100],source
        except (KeyError,IndexError,TypeError,ValueError):
            raise HTTPException(502,'微信文章结构或所选位置无效，未导入') from None


def install_integrations(app,db,settings,user,admin):
    from .notice_ingest import ingest_notice
    publisher=PublisherClient(settings)
    app.state.publisher_client=publisher
    from .publisher_sync import install as install_publisher_sync
    install_publisher_sync(app,db,publisher,admin)

    def store_inbox(conn,uid,title,sources,receipt_key):
        previous=conn.execute('SELECT conversation_id FROM integration_receipts WHERE receipt_key=? AND user_id=?',(receipt_key,uid)).fetchone()
        if previous:
            return previous['conversation_id'],True
        check_count(conn,uid,'conversations','conversations','会话')
        check_storage(conn,uid,sum(len(s['content'] or b'') for s in sources))
        cid=ident();now=int(time.time())
        conn.execute('INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)',(cid,uid,title[:100],now,now))
        for s in sources:
            conn.execute('INSERT INTO conversation_sources VALUES(?,?,?,?,?,?,?,?,?,?)',(s['id'],cid,s['name'],s['kind'],s['content'],s['sha256'],s['status'],dumps(s['sections']),s['warning'],now))
        conn.execute('INSERT INTO integration_receipts VALUES(?,?,?,?)',(receipt_key,uid,cid,now))
        return cid,False

    def save_notice(conn,uid,title,sources,key,label,observed_at=None):
        return ingest_notice(conn,uid,title=title,sources=sources,source_label=label,
                             external_key=key,materials_complete=False,observed_at=observed_at)

    def event_time(data):
        value=data.get('timestamp')
        try:
            if isinstance(value,(float,int)) and not isinstance(value,bool):return float(value)
            if isinstance(value,str):
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo:return parsed.timestamp()
        except (ValueError,OverflowError):pass
        # Missing provider timestamps must stay idempotent by event identity.
        return 1.0

    @app.get('/api/integrations')
    def status(current=Depends(user)):
        with db.connect() as conn:
            binding=conn.execute('SELECT created_at,last_received_at FROM external_bindings WHERE user_id=? AND app_id=?',(current['id'],settings.qq_bot_app_id)).fetchone()
            groups=[dict(r) for r in conn.execute('SELECT s.group_id,s.created_at,s.last_received_at,g.authorized_by=? AS can_disable FROM qq_group_subscriptions s JOIN qq_authorized_groups g USING(app_id,group_id) WHERE s.user_id=? AND s.app_id=?',(current['id'],current['id'],settings.qq_bot_app_id))]
            from .group_delivery import status as delivery_status
            pending_delivery=delivery_status(conn,current['id'],settings.qq_bot_app_id)
            from .publisher_sync import status as publisher_status
            subscription=publisher_status(conn,current['id']) if current['role']=='admin' else None
        return {'qq':{'configured':bool(settings.qq_bot_app_id and settings.qq_bot_secret),'bound':bool(binding),'binding':dict(binding) if binding else None,'scope':'C2C_MESSAGE_CREATE','groups':groups,'pending_deliveries':pending_delivery,'group_events':['GROUP_MESSAGE_CREATE','GROUP_AT_MESSAGE_CREATE']},
                'wechat_publisher':{'configured':bool(settings.wechat_publisher_app_id and settings.wechat_publisher_secret),'can_import':current['role']=='admin','subscription':subscription},
                'school_identity':{'verified':False,'status':'requires_school_authorization'}}

    @app.post('/api/integrations/qq/link-code')
    def link_code(payload:BindingConsent,current=Depends(user)):
        if not settings.qq_bot_app_id or not settings.qq_bot_secret:
            raise HTTPException(503,'QQ 机器人尚未配置。管理员需要应用 AppID、Secret 和 HTTPS 回调。')
        rate_limit(db,'qq-bind:'+current['id'],10,3600)
        raw=secrets.token_urlsafe(24);now=int(time.time())
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM binding_codes WHERE expires_at<? OR user_id=?',(now,current['id']))
            conn.execute('INSERT INTO binding_codes VALUES(?,?,?,?)',(token_hash(raw),current['id'],settings.qq_bot_app_id,now+300))
        return {'command':'绑定 '+raw,'expires_in_seconds':300,'app_id':settings.qq_bot_app_id}

    @app.post('/api/integrations/qq/unlink')
    def unlink(current=Depends(user)):
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM external_bindings WHERE user_id=? AND app_id=?',(current['id'],settings.qq_bot_app_id))
            conn.execute('DELETE FROM binding_codes WHERE user_id=?',(current['id'],))
        return {'ok':True}

    @app.post('/api/integrations/qq/group-code')
    def group_code(payload:GroupConsent,current=Depends(user)):
        if not settings.qq_bot_app_id or not settings.qq_bot_secret:
            raise HTTPException(503,'QQ 机器人尚未配置')
        rate_limit(db,'qq-group-bind:'+current['id'],10,3600)
        raw=secrets.token_urlsafe(24);now=int(time.time())
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM qq_group_codes WHERE expires_at<? OR user_id=?',(now,current['id']))
            conn.execute('INSERT INTO qq_group_codes VALUES(?,?,?,?)',(token_hash(raw),current['id'],settings.qq_bot_app_id,now+300))
        return {'command':'接收群通知 '+raw,'authorize_command':'启用群通知 '+raw,'expires_in_seconds':300,'app_id':settings.qq_bot_app_id}

    @app.delete('/api/integrations/qq/groups/{group_id}')
    def unsubscribe_group(group_id:str,current=Depends(user)):
        with db.connect(write=True) as conn:
            conn.execute('DELETE FROM qq_group_subscriptions WHERE user_id=? AND app_id=? AND group_id=?',(current['id'],settings.qq_bot_app_id,group_id))
        return {'ok':True}

    @app.post('/api/integrations/qq/deliveries/{delivery_id}/retry')
    def retry_group_delivery(delivery_id:str,current=Depends(user)):
        rate_limit(db,'qq-delivery-retry:'+current['id'],20,3600)
        from .group_delivery import deliver_one
        with db.connect(write=True) as conn:
            row=conn.execute("SELECT * FROM qq_group_deliveries WHERE id=? AND user_id=? AND app_id=?",(delivery_id,current['id'],settings.qq_bot_app_id)).fetchone()
            if not row:raise HTTPException(404,'群收件记录不存在或接收授权已撤回')
            if row['state'] not in {'pending','failed'}:return {'ok':True,'state':row['state']}
            conn.execute("UPDATE qq_group_deliveries SET state='pending',attempts=0 WHERE id=?",(delivery_id,))
            row=conn.execute('SELECT * FROM qq_group_deliveries WHERE id=?',(delivery_id,)).fetchone()
            success=deliver_one(conn,row,int(time.time()))
        return {'ok':success,'state':'delivered' if success else 'pending'}

    @app.post('/api/integrations/qq/groups/{group_id}/disable')
    def disable_group(group_id:str,current=Depends(user)):
        with db.connect(write=True) as conn:
            if not conn.execute('DELETE FROM qq_authorized_groups WHERE app_id=? AND group_id=? AND authorized_by=?',(settings.qq_bot_app_id,group_id,current['id'])).rowcount:
                raise HTTPException(404,'群授权不存在或无权停用')
        return {'ok':True}

    def receive_group(conn,data,event_type):
        group_id=data.get('group_openid');author=data.get('author') or {}
        member_id=author.get('member_openid') if isinstance(author,dict) else None
        message_id=data.get('id');content=data.get('content','')
        if not isinstance(group_id,str) or not group_id:
            return
        if not all(isinstance(v,str) and 1<=len(v)<=512 for v in (group_id,member_id,message_id)) or not isinstance(content,str):
            raise HTTPException(400,'群事件缺少群、成员或消息标识')
        command=re.sub(r'^<@!?[^>]+>\s*','',content.strip()).lstrip('/')
        now=int(time.time())
        if command.startswith(('启用群通知 ','接收群通知 ')):
            code=command.split(' ',1)[1].strip()
            binding=conn.execute('SELECT * FROM qq_group_codes WHERE code_hash=? AND app_id=? AND expires_at>?',(token_hash(code),settings.qq_bot_app_id,now)).fetchone()
            if not binding:return
            group=conn.execute('SELECT * FROM qq_authorized_groups WHERE app_id=? AND group_id=?',(settings.qq_bot_app_id,group_id)).fetchone()
            if command.startswith('启用群通知 '):
                if author.get('member_role') not in {'owner','admin'}:return
                if group and group['authorized_by']!=binding['user_id']:return
                conn.execute('INSERT OR IGNORE INTO qq_authorized_groups VALUES(?,?,?,?,?)',(settings.qq_bot_app_id,group_id,binding['user_id'],member_id,now))
            elif not group:return
            conflict=conn.execute('SELECT user_id FROM qq_group_subscriptions WHERE app_id=? AND group_id=? AND member_id=?',(settings.qq_bot_app_id,group_id,member_id)).fetchone()
            if conflict and conflict['user_id']!=binding['user_id']:return
            conn.execute('INSERT INTO qq_group_subscriptions(user_id,app_id,group_id,member_id,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,app_id,group_id) DO UPDATE SET member_id=excluded.member_id',
                         (binding['user_id'],settings.qq_bot_app_id,group_id,member_id,now))
            conn.execute('DELETE FROM qq_group_codes WHERE code_hash=?',(binding['code_hash'],))
            return
        group=conn.execute('SELECT 1 FROM qq_authorized_groups WHERE app_id=? AND group_id=?',(settings.qq_bot_app_id,group_id)).fetchone()
        if not group or author.get('bot'):return
        subscribers=conn.execute('SELECT user_id FROM qq_group_subscriptions WHERE app_id=? AND group_id=?',(settings.qq_bot_app_id,group_id)).fetchall()
        if not subscribers:return
        source=message_source(data,'QQ 群消息原文')
        title='群通知 · '+((' '.join(s['text'] for s in source['sections']))[:60] or '待补充材料')
        for subscriber in subscribers:
            # A group payload is distributed only to separately proven members
            # who opted in, never to every account or every member by default.
            from .group_delivery import enqueue
            enqueue(conn,subscriber['user_id'],settings.qq_bot_app_id,group_id,
                    'qq-group:'+settings.qq_bot_app_id+':'+group_id+':'+message_id,title,source,event_time(data))

    @app.post('/api/integrations/qq/webhook')
    async def webhook(request:Request):
        if not settings.qq_bot_app_id or not settings.qq_bot_secret:
            raise HTTPException(404,'渠道未启用')
        if request.headers.get('x-bot-appid')!=settings.qq_bot_app_id:
            raise HTTPException(403,'应用不匹配')
        raw=await request.body()
        if len(raw)>256*1024:
            raise HTTPException(413,'事件体超过限制')
        try:
            payload=json.loads(raw);data=payload['d']
            if not isinstance(data,dict):
                raise ValueError('invalid')
        except (ValueError,TypeError,KeyError):
            raise HTTPException(400,'事件格式不合法') from None
        if payload.get('op')==13:
            rate_limit(db,'qq-challenge:'+(request.client.host if request.client else ''),30,60)
            plain=data.get('plain_token','');stamp=data.get('event_ts','')
            # The unsigned protocol challenge can sign only a token, never JSON event bodies.
            if not isinstance(plain,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',plain) or not isinstance(stamp,str) or not re.fullmatch(r'[0-9]{10,12}',stamp) or abs(time.time()-int(stamp))>300:
                raise HTTPException(400,'校验参数不合法或已过期')
            return {'plain_token':plain,'signature':qq_key(settings.qq_bot_secret).sign((stamp+plain).encode()).hex()}
        if not verify_qq(settings.qq_bot_secret,request.headers.get('x-signature-timestamp',''),request.headers.get('x-signature-ed25519',''),raw):
            raise HTTPException(403,'事件签名无效或已过期')
        event_type=payload.get('t');ack={'op':12}
        if payload.get('op')!=0:
            return ack
        if event_type in {'GROUP_MESSAGE_CREATE','GROUP_AT_MESSAGE_CREATE'}:
            with db.connect(write=True) as conn:receive_group(conn,data,event_type)
            return ack
        if event_type in {'GROUP_DEL_ROBOT','GROUP_MEMBER_REMOVE'}:
            group_id=data.get('group_openid')
            with db.connect(write=True) as conn:
                if event_type=='GROUP_DEL_ROBOT':
                    conn.execute('DELETE FROM qq_authorized_groups WHERE app_id=? AND group_id=?',(settings.qq_bot_app_id,group_id))
                else:
                    member_id=data.get('member_openid')
                    if member_id:
                        conn.execute('DELETE FROM qq_group_subscriptions WHERE app_id=? AND group_id=? AND member_id=?',(settings.qq_bot_app_id,group_id,member_id))
                        conn.execute('DELETE FROM qq_authorized_groups WHERE app_id=? AND group_id=? AND authorized_member=?',(settings.qq_bot_app_id,group_id,member_id))
            return ack
        if event_type!='C2C_MESSAGE_CREATE':return ack
        author=data.get('author',{})
        openid=author.get('user_openid') if isinstance(author,dict) else None
        content=data.get('content','');message_id=data.get('id')
        if not isinstance(openid,str) or not 1<=len(openid)<=128 or not isinstance(message_id,str) or not 1<=len(message_id)<=512 or not isinstance(content,str):
            raise HTTPException(400,'事件缺少有效用户、消息标识或正文')
        receipt='qq:'+hashlib.sha256((settings.qq_bot_app_id+'\n'+openid+'\n'+message_id).encode()).hexdigest()
        now=int(time.time())
        with db.connect(write=True) as conn:
            if conn.execute('SELECT 1 FROM integration_receipts WHERE receipt_key=?',(receipt,)).fetchone():
                return ack
            if content.strip().startswith(('绑定 ','/绑定 ')):
                code=content.strip().split(' ',1)[1].strip()
                binding=conn.execute('SELECT * FROM binding_codes WHERE code_hash=? AND app_id=? AND expires_at>?',(token_hash(code),settings.qq_bot_app_id,now)).fetchone()
                if not binding:
                    return ack
                conflict=conn.execute('SELECT user_id FROM external_bindings WHERE app_id=? AND open_id=?',(settings.qq_bot_app_id,openid)).fetchone()
                if conflict and conflict['user_id']!=binding['user_id']:
                    return ack
                conn.execute('DELETE FROM external_bindings WHERE user_id=? AND app_id=?',(binding['user_id'],settings.qq_bot_app_id))
                conn.execute('INSERT INTO external_bindings(user_id,app_id,open_id,created_at) VALUES(?,?,?,?)',(binding['user_id'],settings.qq_bot_app_id,openid,now))
                conn.execute('DELETE FROM binding_codes WHERE user_id=?',(binding['user_id'],))
                conn.execute('INSERT INTO integration_receipts VALUES(?,?,NULL,?)',(receipt,binding['user_id'],now))
                return ack
            binding=conn.execute('SELECT user_id FROM external_bindings WHERE app_id=? AND open_id=?',(settings.qq_bot_app_id,openid)).fetchone()
            if not binding:
                return ack
            if len(content)>10000:
                raise HTTPException(413,'单条正文超过 10000 字，请分段主动提交')
            incomplete=bool(data.get('attachments') or data.get('msg_elements') or data.get('ark_data') or data.get('message_type') not in (None,0))
            if not content.strip() and not incomplete:
                return ack
            source=message_source(data,'QQ 机器人单聊原文')
            store_inbox(conn,binding['user_id'],'QQ 收件 · '+(content.strip()[:60] or '待补充材料'),[source],receipt)
            save_notice(conn,binding['user_id'],'QQ 通知 · '+(content.strip()[:60] or '待补充材料'),[source],
                        'qq-c2c:'+settings.qq_bot_app_id+':'+openid+':'+message_id,'QQ 机器人单聊',event_time(data))
            conn.execute('UPDATE external_bindings SET last_received_at=? WHERE user_id=? AND app_id=?',(now,binding['user_id'],settings.qq_bot_app_id))
        return ack

    @app.get('/api/integrations/wechat/articles')
    def articles(offset:int=Query(default=0,ge=0,le=10000),current=Depends(admin)):
        rate_limit(db,'publisher-list:'+current['id'],60,3600)
        return publisher.articles(offset)

    @app.post('/api/integrations/wechat/import')
    def import_article(payload:ImportArticle,current=Depends(admin)):
        rate_limit(db,'publisher-import:'+current['id'],30,3600)
        title,source=publisher.article(payload.article_id,payload.index)
        receipt='wechat:'+hashlib.sha256((current['id']+'\n'+settings.wechat_publisher_app_id+'\n'+payload.article_id+'\n'+str(payload.index)+'\n'+source['sha256']).encode()).hexdigest()
        with db.connect(write=True) as conn:
            cid,existed=store_inbox(conn,current['id'],'公众号 · '+title,[source],receipt)
            if existed and cid is None:
                return {'conversation_id':None,'notice_id':None,'already_imported':True,'deleted_before':True}
            saved=save_notice(conn,current['id'],title,[source],
                'wechat:'+settings.wechat_publisher_app_id+':'+payload.article_id+':'+str(payload.index),'获授权公众号')
        return {'conversation_id':cid,'notice_id':saved['notice_id'],'already_imported':bool(saved.get('duplicate')),'updated':bool(saved.get('updated')),'deleted_before':False}
