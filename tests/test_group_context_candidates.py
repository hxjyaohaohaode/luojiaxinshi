"""Signed synthetic QQ events; suggestions never perform a business change."""
import time

from app import notice_matters,qq_group_media
from tests.test_workflow import env,account
from tests.test_group_delivery import members
from tests.test_integrations import event
from tests.test_qq_group_intake import send,history,process_media,CDN
from tests.test_notice_matters import preview,related,join


def lookup(client,part):
    return next(n for n in client.get('/api/notices').json() if part in n['title'])


def test_short_correction_and_later_attachment_are_only_traceable_candidates(env,monkeypatch):
    a,b,external,cfg=members(env)
    send(external,cfg,'2026年项目申请通知：请本人核对资格并准备申请表。','base')
    send(external,cfg,'延期了','correction')
    original='新模板字段需本人核对。'.encode()
    async def fetch(url):return original
    monkeypatch.setattr(qq_group_media,'fetch_file',fetch)
    send(external,cfg,'附件补发','attachment',extra={'attachments':[{'url':CDN+'template','filename':'补充表.txt','size':len(original)}]})
    process_media(env[0].state.db,cfg)
    base,correction,attachment=[lookup(a,text) for text in ('2026年项目','延期了','附件补发')]
    result=related(a,correction)
    assert result['group'] is None
    candidates={item['id']:item for item in result['suggestions']}
    assert base['id'] in candidates and attachment['id'] in candidates
    context=candidates[base['id']]['context']
    assert context['kind']=='qq_group_adjacent' and not context['verified']
    assert context['thread_id'] is None and context['same_author'] is None
    assert context['time_basis']=='local_received_at' and context['elapsed_seconds']<=600
    assert len(context['delivery_ids'])==len(context['message_keys'])==2
    assert any('未取得回复线程' in reason for reason in candidates[base['id']]['reasons'])
    assert related(a,attachment)['group'] is None and len(a.get('/api/notices').json())==3
    assert a.get('/api/tasks').json()==[]
    other_ids={n['id'] for n in b.get('/api/notices').json()}
    assert not other_ids.intersection(candidates) and b.get('/api/notices/'+base['id']+'/matter').status_code==404
    detail=a.get('/api/notices/'+attachment['id']).json()
    source=next(s for s in detail['sources'] if s['name']=='补充表.txt')
    assert a.get('/api/notices/'+attachment['id']+'/sources/'+source['id']+'/download').content==original
    grouped=join(a,base,correction)
    assert len(grouped['members'])==2 and a.get('/api/tasks').json()==[]


def test_rejected_neighbor_stays_rejected_after_replay_and_material_version_change(env):
    a,b,external,cfg=members(env)
    send(external,cfg,'2026年科研申报通知：请准备本人材料。','base')
    send(external,cfg,'延期了','later')
    base,later=lookup(a,'科研申报'),lookup(a,'延期了')
    view=preview(a,base,later)
    assert a.post('/api/notices/'+base['id']+'/matter/dismiss',json={'other_id':later['id'],'token':view['token']}).status_code==200
    send(external,cfg,'延期了','later')
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE notices SET version=version+1 WHERE id=?',(later['id'],))
    assert not related(a,base)['suggestions'] and not related(a,later)['suggestions']
    # A new connection reconstructs candidates from stored receipts and the
    # stored rejection; no in-memory or process-local suppression is required.
    with env[0].state.db.connect() as conn:
        uid=a.get('/api/session').json()['user']['id']
        assert not notice_matters.suggest(conn,uid,notice_matters.own(conn,uid,later['id']),None)


def test_neighbor_scope_never_crosses_group_account_or_business_round(env):
    a,b,external,cfg=members(env)
    send(external,cfg,'2025年旧项目申请通知：准备资格材料。','old')
    send(external,cfg,'2026年更正：新项目材料延期。','new')
    old,new=lookup(a,'2025年'),lookup(a,'2026年')
    assert old['id'] not in {n['id'] for n in related(a,new)['suggestions']}
    code=a.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()['authorize_command']
    assert event(external,cfg,code,t='GROUP_MESSAGE_CREATE',extra={'group_openid':'other-group','author':{'member_openid':'other-owner','member_role':'admin'}}).status_code==200
    send(external,cfg,'延期了','other-correction',group='other-group')
    separate=lookup(a,'延期了')
    assert not related(a,separate)['suggestions']
    stranger=account(env,'not-subscribed')
    assert stranger.get('/api/notices/'+separate['id']+'/matter').status_code==404


def test_expired_neighbor_or_revoked_group_authorization_stops_suggestions(env):
    a,b,external,cfg=members(env)
    now=int(time.time())
    send(external,cfg,'2026年报名通知：请准备申请材料。','base',extra={'timestamp':now+1})
    send(external,cfg,'延期了','later',extra={'timestamp':now+700})
    base,later=lookup(a,'2026年'),lookup(a,'延期了')
    assert not related(a,later)['suggestions']
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE qq_group_deliveries SET observed_at=? WHERE notice_id=?',(now+60,later['id']))
    assert base['id'] in {n['id'] for n in related(a,later)['suggestions']}
    assert a.delete('/api/integrations/qq/groups/private-group').status_code==200
    assert not related(a,later)['suggestions']
    assert a.get('/api/notices/'+base['id']).status_code==200


def test_proximity_without_correction_or_material_signal_does_not_link(env):
    a,b,external,cfg=members(env)
    send(external,cfg,'今天图书馆有一场公开讲座，请自愿报名。','lecture')
    send(external,cfg,'周五交费','payment')
    payment=lookup(a,'周五交费')
    assert not related(a,payment)['suggestions']


def test_short_material_request_is_candidate_even_before_file_is_supplied(env):
    a,b,external,cfg=members(env)
    send(external,cfg,'2026年困难补助申请通知，请核对资格和材料。','base')
    send(external,cfg,'还需补交证明','material-request')
    base,later=lookup(a,'2026年'),lookup(a,'补交证明')
    candidate=next(item for item in related(a,later)['suggestions'] if item['id']==base['id'])
    assert candidate['context']['signals']==['material']
    assert related(a,later)['group'] is None and a.get('/api/tasks').json()==[]
