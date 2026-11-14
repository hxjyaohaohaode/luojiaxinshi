"""Explicit owner routes refine timing, never audience or evidence eligibility."""
import json
import hashlib
from fastapi import HTTPException
from .db import dumps


def source_routes(conn,uid):
    """Stable private IDs for actual ingestion routes, not unconnected labels."""
    result=[]
    for row in conn.execute('SELECT c.id,c.data,s.source_id AS subscribed FROM source_catalog c LEFT JOIN source_subscriptions s ON s.source_id=c.id WHERE c.user_id=? ORDER BY c.updated_at DESC,c.id',(uid,)):
        data=json.loads(row['data'])
        if data.get('platform')=='website' or row['subscribed']:
            result.append({'id':row['id'],'title':data.get('name','未命名来源'),'prefix':'website:'+row['id']+':'})
    def add(prefix,title):
        result.append({'id':hashlib.sha256(('notification-source:'+prefix).encode()).hexdigest()[:32],'title':title,'prefix':prefix})
    publishers={row[0] for row in conn.execute('SELECT app_id FROM publisher_subscriptions WHERE user_id=?',(uid,))}
    for row in conn.execute("SELECT DISTINCT external_key FROM notice_ingest_receipts WHERE user_id=? AND external_key LIKE 'wechat:%'",(uid,)):
        parts=row[0].split(':',2)
        if len(parts)==3:publishers.add(parts[1])
    for app_id in sorted(publishers):add('wechat:'+app_id+':','本人获授权的公众号收件')
    if conn.execute("SELECT 1 FROM external_bindings WHERE user_id=? UNION SELECT 1 FROM notice_ingest_receipts WHERE user_id=? AND external_key LIKE 'qq:%' LIMIT 1",(uid,uid)).fetchone():
        add('qq:','本人 QQ 私聊收件')
    for row in conn.execute('''SELECT s.app_id,s.group_id,COALESCE(i.name,'') AS name FROM qq_group_subscriptions s
        LEFT JOIN qq_group_intake_settings i USING(user_id,app_id,group_id) WHERE s.user_id=?''',(uid,)):
        add('qq-group:'+row['app_id']+':'+row['group_id']+':','QQ 群：'+(row['name'] or '本人已授权群'))
    return result


def validate_owner_routes(conn,uid,pref,previous):
    for name,table in [('source_delivery','source_catalog'),('notice_delivery','notices')]:
        routes=getattr(pref,name)
        if not routes:continue
        owned=({row['id'] for row in source_routes(conn,uid)} if name=='source_delivery' else
               {row[0] for row in conn.execute('SELECT id FROM '+table+' WHERE user_id=? AND id IN (SELECT value FROM json_each(?))',(uid,dumps(list(routes))))})
        for key in set(routes)-owned:
            if key not in previous.get(name,{}):raise HTTPException(422,'提醒规则只能关联本人现有通知或来源')
            # Deleted records no longer route events; clean only known stale IDs.
            routes.pop(key)


def notice_modes(conn,uid,pref):
    result=dict(pref.notice_delivery)
    if not pref.source_delivery:return result
    sources=[(row['prefix'],pref.source_delivery[row['id']]) for row in source_routes(conn,uid) if row['id'] in pref.source_delivery]
    sources.sort(key=lambda item:len(item[0]),reverse=True)
    priorities={'immediate':0,'digest':1,'in_app':2,'off':3}
    grouped={}
    for row in conn.execute('SELECT notice_id,external_key FROM notice_ingest_receipts WHERE user_id=?',(uid,)):
        mode=next((mode for prefix,mode in sources if row['external_key'].startswith(prefix)),None)
        if mode and row['notice_id'] not in result:
            prior=grouped.get(row['notice_id'],'immediate')
            grouped[row['notice_id']]=max((prior,mode),key=lambda value:priorities[value])
    return {**grouped,**result}


def receipt_decision(decision,pref,override=None):
    value=dict(decision)
    if value.get('delivery')=='silent':return value
    mode=override or pref.receipt_delivery
    if mode in {'in_app','off'}:value['delivery']='silent'
    elif mode=='digest':value['delivery']='daily_digest'
    elif override=='immediate':value['delivery']='near_term'
    return value
