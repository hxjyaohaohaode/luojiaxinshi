"""Replay signed synthetic QQ callbacks through the actual intake and inbox."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx
import pytest
from fastapi import HTTPException

from app import group_delivery, notice_automation, push_delivery, qq_group_media
from app.documents import MAX_CHARS
from app.usage_limits import StorageCapacityError
from tests.test_group_delivery import members
from tests.test_integrations import event
from tests.test_workflow import account, env

GROUP = 'private-group'
INTAKE = '/api/integrations/qq/groups/'+GROUP+'/intake'
CDN = 'https://multimedia.nt.qq.com.cn/download?fileid='


def send(external, cfg, text, mid, *, group=GROUP, extra=None, at=False):
    response = event(external, cfg, text, mid=mid,
                     t='GROUP_AT_MESSAGE_CREATE' if at else 'GROUP_MESSAGE_CREATE',
                     extra={'group_openid':group,
                            'author':{'member_openid':'writer','member_role':'member'}, **(extra or {})})
    assert response.status_code == 200, response.text
    assert response.json() == {'op':12}


def history(client, **params):
    response = client.get(INTAKE, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def owner_id(client):
    return client.get('/api/session').json()['user']['id']


def received_ids(conn, uid):
    return {item['id'] for receipt in push_delivery.candidates(conn, uid, int(time.time())+60).values()
            for item in receipt.get('received_items', [])}


def process_media(db, cfg):
    assert asyncio.run(qq_group_media.run_one(db,cfg.qq_bot_app_id))
    group_delivery.tick(db,cfg.qq_bot_app_id)


def test_labelled_group_replay_preserves_uncertainty_and_distinguishes_receipt_from_delivery(env):
    alice,bob,external,cfg = members(env)
    replay = json.loads((Path(__file__).parents[1]/'fixtures/qq-group/replay.json').read_text(encoding='utf-8'))
    settings = alice.put(INTAKE,json={'version':0,'name':'答辩互助群','keywords':['CLUB-42','club-42']})
    assert settings.json() == {'name':'答辩互助群','mode':'notices','keywords':['CLUB-42'],'version':1}
    assert alice.put(INTAKE,json={'version':0,'name':'过期设置'}).status_code == 409
    assert alice.put(INTAKE,json={'version':1,'keywords':['词'*31]}).status_code == 422
    assert history(bob)['settings']['version'] == 0
    for item in replay:
        send(external,cfg,item['text'],item['id'],extra=item.get('extra'),at=item['id']=='apply')
    send(external,cfg,replay[0]['text'],replay[0]['id'])
    first = history(alice)
    assert len(first['items']) == 25 and first['next_before'] is not None
    last = history(alice,before=first['next_before'])
    assert last['next_before'] is None
    rows = list(reversed(first['items']+last['items']))
    assert len(rows) == len(replay) and len({r['id'] for r in rows}) == len(replay)
    assert first['counts']['delivered'] == len(replay) and first['counts']['repeats'] == 1
    assert len({r['notice_id'] for r in rows}) == len(replay)
    categories = Counter(item['category'] for item in replay)
    assert {key:first['counts'][key] for key in categories} == categories
    notices = {n['id']:n for n in alice.get('/api/notices').json()}
    for expected, actual in zip(replay, rows, strict=True):
        assert actual['category'] == expected['category'], expected['id']
        assert actual['result'] == 'new' and actual['rule_version'] and actual['reasons']
        assert actual['quiet'] == (expected['category']=='discussion')
        assert (notices[actual['notice_id']]['intent']=='discussion') == actual['quiet']
        if expected.get('change'):
            assert any('更正' in reason for reason in actual['reasons'])
    assert notices[rows[0]['notice_id']]['source_label'] == 'QQ 群 · 答辩互助群'
    assert all(r['category']=='review' for r in history(alice,category='review')['items'])
    assert len(history(alice,category='discussion')['items']) == categories['discussion']
    assert len(history(alice,category='unclassified')['items']) == 0
    assert bob.get('/api/notices/'+rows[0]['notice_id']).status_code == 404
    assert history(bob)['counts']['notice'] == categories['notice']-1
    with env[0].state.db.connect() as conn:
        quiet = {r['notice_id'] for r in rows if r['quiet']}
        reminders = received_ids(conn,owner_id(alice))
        assert not (quiet & reminders)
        assert reminders == {r['notice_id'] for r in rows if not r['quiet']}


def test_personal_mode_and_feedback_gate_analysis_and_reminders(env):
    alice,bob,external,cfg = members(env)
    assert bob.put(INTAKE,json={'version':0,'mode':'all'}).status_code == 200
    send(external,cfg,'好的','mode-check')
    a = history(alice)['items'][0]
    b = history(bob)['items'][0]
    assert a['category'] == b['category'] == 'discussion' and a['quiet'] and not b['quiet']
    a_id,b_id = owner_id(alice),owner_id(bob)
    db = env[0].state.db
    with db.connect() as conn:
        assert a['notice_id'] not in received_ids(conn,a_id)
        assert b['notice_id'] in received_ids(conn,b_id)
    assert alice.get('/api/proactive/notices/'+a['notice_id']).json()['assessment']['delivery'] == 'silent'
    for client in (alice,bob):
        assert client.put('/api/notice-automation',json={'enabled':True,'allow_external_processing':True}).status_code == 200
    assert history(alice)['items'][0]['automation_state'] is None
    assert history(bob)['items'][0]['automation_state'] == 'queued'
    notice = alice.get('/api/notices/'+a['notice_id']).json()
    response = alice.put('/api/proactive/notices/'+a['notice_id']+'/feedback',
                         json={'mode':'include','notice_version':notice['version'],'version':0})
    assert response.status_code == 200, response.text
    with db.connect(write=True) as conn:
        assert a['notice_id'] in received_ids(conn,a_id)
        notice_automation.queue_ready(conn,cfg,a_id)
    assert history(alice)['items'][0]['automation_state'] == 'queued'
    assert alice.get('/api/notices').json()[0]['recommended']


def test_authorization_boundary_versions_and_cross_group_forward(env):
    alice,bob,external,cfg = members(env)
    stranger = account(env,'stranger')
    assert stranger.get(INTAKE).status_code == 404
    assert stranger.put(INTAKE,json={'version':0,'mode':'all'}).status_code == 404
    now = int(time.time())
    past = datetime.fromtimestamp(now-120,timezone.utc).isoformat()
    send(external,cfg,'授权之前的历史消息','older',extra={'timestamp':past})
    assert not history(alice)['items']
    send(external,cfg,'请周五提交申请','versioned',extra={'timestamp':now+1})
    base = history(alice)['items'][0]
    send(external,cfg,'更正：申请截止改到周一','versioned',extra={'timestamp':now+3})
    send(external,cfg,'前次草案：周六前提交','versioned',extra={'timestamp':now+2})
    rows = history(alice)['items']
    assert [r['result'] for r in rows] == ['superseded','updated','new']
    assert {r['notice_id'] for r in rows} == {base['notice_id']}
    assert rows[1]['category']=='review' and not rows[1]['quiet']
    detail = alice.get('/api/notices/'+base['notice_id']).json()
    assert '改到周一' in detail['title'] and len(detail['intake_updates']) == 1
    other = 'same-course-other-group'
    code = alice.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()['authorize_command']
    assert event(external,cfg,code,t='GROUP_MESSAGE_CREATE',extra={
        'group_openid':other,'author':{'member_openid':'other-owner','member_role':'admin'}}).status_code == 200
    send(external,cfg,'更正：申请截止改到周一','forward',group=other)
    forwarded = alice.get('/api/integrations/qq/groups/'+other+'/intake').json()
    assert forwarded['counts']['merged'] == 1
    assert forwarded['items'][0]['notice_id'] == base['notice_id']
    assert bob.get('/api/integrations/qq/groups/'+other+'/intake').status_code == 404
    send(external,cfg,'收到','versioned',extra={'timestamp':now+4})
    edited = alice.get('/api/notices/'+base['notice_id']).json()
    assert edited['intent'] == 'verify' and edited['recommended'] and edited['pending_intake_updates'] == 2


def test_delayed_group_removals_do_not_revoke_newer_verified_membership(env):
    alice,bob,external,cfg = members(env)
    now = int(time.time())
    db = env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute('UPDATE qq_group_subscriptions SET created_at=?',(now-120,))
        conn.execute('UPDATE qq_authorized_groups SET created_at=?',(now-120,))
    for client,member,role,field in [(alice,'owner-id','owner','authorize_command'),
                                      (bob,'bob-member','member','command')]:
        code = client.post('/api/integrations/qq/group-code',json={'receive_group_notices':True}).json()[field]
        send(external,cfg,code,'renew-'+member,at=True,
             extra={'author':{'member_openid':member,'member_role':role}})
    for event_type,member in [('GROUP_MEMBER_REMOVE','bob-member'),('GROUP_MEMBER_REMOVE','owner-id'),
                              ('GROUP_DEL_ROBOT','owner-id')]:
        response = event(external,cfg,t=event_type,
                         extra={'group_openid':GROUP,'member_openid':member,'timestamp':now-60})
        assert response.status_code == 200
        assert history(alice)['settings']['version']==history(bob)['settings']['version']==0
    send(external,cfg,'新授权以后，请提交实验报告','still-active',extra={'timestamp':now+60})
    assert history(alice)['counts']['delivered']==history(bob)['counts']['delivered']==1
    assert event(external,cfg,t='GROUP_MEMBER_REMOVE',
                 extra={'group_openid':GROUP,'member_openid':'bob-member','timestamp':now+60}).status_code==200
    assert bob.get(INTAKE).status_code==404 and len(bob.get('/api/notices').json())==1
    assert event(external,cfg,t='GROUP_DEL_ROBOT',
                 extra={'group_openid':GROUP,'timestamp':now+60}).status_code==200
    assert alice.get(INTAKE).status_code==404 and len(alice.get('/api/notices').json())==1


def test_oversized_or_deep_group_material_preserves_visible_text_and_review(env):
    alice,bob,external,cfg = members(env)
    top = '更正：实习材料以新版为准。'
    deep = {'content':'保留上层正文'}
    for _ in range(8):
        deep = {'content':'转发聊天记录','msg_elements':[deep]}
    send(external,cfg,top,'nested-chat',extra={'msg_elements':[deep]})
    long = '周五前补交'+'甲'*MAX_CHARS
    send(external,cfg,long+'第一版尾部','overlong')
    send(external,cfg,long+'第二版尾部','overlong-other')
    rows = history(alice)['items']
    assert len({r['notice_id'] for r in rows}) == 3
    assert all(r['category']=='review' and not r['quiet'] for r in rows)
    deep_notice = alice.get('/api/notices/'+rows[2]['notice_id']).json()
    assert any(section['text']==top for source in deep_notice['sources'] for section in source['sections'])
    assert any('嵌套过多' in s['warning'] for s in deep_notice['sources'])
    for row in rows[:2]:
        detail = alice.get('/api/notices/'+row['notice_id']).json()
        assert any(section['text']==long[:MAX_CHARS] for s in detail['sources'] for section in s['sections'])
        assert any('前 10000 字' in s['warning'] for s in detail['sources'])


def test_shared_attachment_fetch_retains_original_and_marks_partial_success(env,monkeypatch):
    alice,bob,external,cfg = members(env)
    db = env[0].state.db
    calls = []
    original = '报名请携带校园卡。'.encode()
    async def fetch(url):
        calls.append(url)
        if len(calls)==1:
            raise qq_group_media.AttachmentError('文件服务临时失败',retry=True)
        return original
    monkeypatch.setattr(qq_group_media,'fetch_file',fetch)
    raw = [{'url':CDN+'original&rkey=first-token','filename':'通知原件.txt','size':len(original)},
           {'url':'https://example.invalid/unavailable','filename':'缺失原件.pdf'}]
    send(external,cfg,'收到','with-media',extra={'msg_elements':[{'attachments':raw}]})
    pending = history(alice)['items'][0]
    assert pending['media_state'] == 'waiting' and pending['category'] == 'review' and not pending['quiet']
    assert not calls and not alice.get('/api/notices').json()
    retry = alice.post('/api/integrations/qq/deliveries/'+pending['id']+'/retry').json()
    assert retry == {'ok':False,'state':'pending','waiting_attachments':True}
    process_media(db,cfg)
    for client in (alice,bob):
        row = history(client)['items'][0]
        assert row['state'] == 'delivered' and row['media_state'] == 'partial'
        assert row['media_saved'] == 1 and row['media_total'] == 2 and row['media_note']
        notice_path = '/api/notices/'+row['notice_id']
        response = client.get(notice_path)
        notice = response.json()
        assert not notice['materials_complete']
        assert 'first-token' not in response.text and 'first-token' not in json.dumps(row)
        source = next(s for s in notice['sources'] if s['name']=='通知原件.txt')
        assert source['status'] == 'ok' and source['sections'][0]['text'] == original.decode()
        assert client.get(notice_path+'/sources/'+source['id']+'/download').content == original
        assert any('收到' in sec['text'] for s in notice['sources'] for sec in s['sections'])
        other = alice if client is bob else bob
        assert other.get(notice_path+'/sources/'+source['id']+'/download').status_code == 404
    raw[0]['url'] = CDN+'original&rkey=reissued-token'
    send(external,cfg,'收到','with-media',extra={'msg_elements':[{'attachments':raw}]})
    assert not asyncio.run(qq_group_media.run_one(db,cfg.qq_bot_app_id))
    assert calls == [CDN+'original&rkey=first-token']*2
    assert len(history(alice)['items']) == 1 and history(alice)['counts']['repeats'] == 1


def test_attachment_failure_and_member_storage_limit_preserve_readable_text(env,monkeypatch):
    alice,bob,external,cfg = members(env)
    uid = owner_id(alice)
    db = env[0].state.db
    async def fetch(url):
        if 'lost' in url:
            raise qq_group_media.AttachmentError('原件链接已失效或暂无下载权限')
        return b'attachment body'
    monkeypatch.setattr(qq_group_media,'fetch_file',fetch)
    original_ingest = group_delivery.ingest_notice
    def storage_limit(conn,owner,**kwargs):
        if owner==uid and any(s['content'] for s in kwargs['sources']):
            raise StorageCapacityError(413,'文件空间不足')
        return original_ingest(conn,owner,**kwargs)
    monkeypatch.setattr(group_delivery,'ingest_notice',storage_limit)
    send(external,cfg,'请周一提交证明','storage',extra={'attachments':[{'url':CDN+'valid','filename':'材料.txt'}]})
    process_media(db,cfg)
    assert history(bob)['items'][0]['media_state'] == 'complete'
    send(external,cfg,'明早请带笔','expired',extra={'attachments':[{'url':CDN+'lost','filename':'失效.txt'}]})
    process_media(db,cfg)
    a_lost,a_quota = history(alice)['items']
    assert a_lost['media_state'] == a_quota['media_state'] == 'missing'
    assert '已失效' in a_lost['media_note'] and '空间不足' in a_quota['media_note']
    for row,text in [(a_lost,'明早请带笔'),(a_quota,'请周一提交证明')]:
        detail = alice.get('/api/notices/'+row['notice_id']).json()
        assert any(sec['text']==text for s in detail['sources'] for sec in s['sections'])
        assert any('待补材料' in s['name'] for s in detail['sources'])

    # Users can upload the actual original even when it is byte-for-byte
    # equal to the already preserved inline text.
    path = '/api/notices/'+a_lost['notice_id']
    saved = alice.get(path).json()
    original = '明早请带笔'.encode()
    attached = alice.post(path+'/supplement',data={'version':str(saved['version'])},
                          files={'files':('从群补传的原件.txt',original,'text/plain')})
    assert attached.status_code==200,attached.text
    attached = attached.json()
    file = next(s for s in attached['sources'] if s['kind']=='txt')
    assert alice.get(path+'/sources/'+file['id']+'/download').content==original
    gap = next(s for s in attached['sources'] if s['name']=='QQ 待补材料')
    checked = alice.post(path+'/sources/'+gap['id']+'/review',
                         json={'version':attached['version'],'action':'resolve','reason':'已核对补传的群原件'})
    assert checked.status_code==200 and checked.json()['version']>attached['version']


def test_waiting_token_refresh_and_recipient_retry_keep_both_text_and_original(env,monkeypatch):
    alice,bob,external,cfg = members(env)
    db = env[0].state.db
    bob_id = owner_id(bob)
    original = '附件与正文完全相同，请带校园卡'
    calls = []
    async def fetch(url):
        calls.append(url)
        return original.encode()
    monkeypatch.setattr(qq_group_media,'fetch_file',fetch)
    real = group_delivery.ingest_notice
    def notice_limit(conn,uid,**kwargs):
        if uid==bob_id:
            raise HTTPException(413,'通知容量已满')
        return real(conn,uid,**kwargs)
    monkeypatch.setattr(group_delivery,'ingest_notice',notice_limit)
    for token in ('old','renewed'):
        send(external,cfg,original,'refresh-token',
             extra={'attachments':[{'url':CDN+'same-content&rkey='+token,'filename':'原件.txt'}]})
    process_media(db,cfg)
    assert calls == [CDN+'same-content&rkey=renewed']
    item = history(alice)['items'][0]
    assert item['repeats'] == 1 and item['media_state'] == 'complete'
    notice = alice.get('/api/notices/'+item['notice_id']).json()
    assert {s['kind'] for s in notice['sources']} == {'text','txt'}
    assert len({s['sha256'] for s in notice['sources']}) == 1
    pending = history(bob)['items'][0]
    assert pending['media_state'] == 'ready' and '容量已满' in pending['error']
    monkeypatch.setattr(group_delivery,'ingest_notice',real)
    result = bob.post('/api/integrations/qq/deliveries/'+pending['id']+'/retry')
    assert result.json()['ok'] and history(bob)['items'][0]['media_state'] == 'complete'
    assert len(calls) == 1


def test_attachment_revocation_during_download_and_expired_leases(env,monkeypatch):
    alice,bob,external,cfg = members(env)
    db = env[0].state.db
    attach = {'attachments':[{'url':CDN+'short-lived','filename':'材料.txt'}]}
    send(external,cfg,'明天提交附件','revoke-one',extra=attach)
    async def revoke_one(url):
        assert bob.delete(INTAKE.removesuffix('/intake')).status_code == 200
        return b'only remaining subscriber'
    monkeypatch.setattr(qq_group_media,'fetch_file',revoke_one)
    process_media(db,cfg)
    assert history(alice)['items'][0]['media_state'] == 'complete'
    assert not bob.get('/api/notices').json()
    assert bob.get(INTAKE).status_code == 404
    send(external,cfg,'原件补齐前保留文字','expired-window',extra=attach)
    now = int(time.time())
    expired = qq_group_media.claim(db,cfg.qq_bot_app_id,now)
    now += qq_group_media.DOWNLOAD_WINDOW+1
    assert not asyncio.run(qq_group_media.run_one(db,cfg.qq_bot_app_id,now=now))
    assert not qq_group_media.finish(db,expired,[],'旧租约结果',now)
    group_delivery.tick(db,cfg.qq_bot_app_id,now)
    assert '下载窗口已结束' in history(alice)['items'][0]['media_note']
    send(external,cfg,'退群后不再接收附件','revoke-group',extra=attach)
    async def revoke_all(url):
        assert event(external,cfg,t='GROUP_DEL_ROBOT',extra={'group_openid':GROUP}).status_code == 200
        return b'no subscriber'
    monkeypatch.setattr(qq_group_media,'fetch_file',revoke_all)
    assert not asyncio.run(qq_group_media.run_one(db,cfg.qq_bot_app_id))
    assert alice.get(INTAKE).status_code == 404 and len(alice.get('/api/notices').json()) == 2
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM qq_group_attachment_batches').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM qq_group_attachment_files').fetchone()[0] == 0


def test_transient_file_failure_does_not_start_a_retry_after_group_revocation(env,monkeypatch):
    alice,bob,external,cfg = members(env)
    send(external,cfg,'请确认附件','revoke-before-retry',
         extra={'attachments':[{'url':CDN+'pending-retry','filename':'原件.txt'}]})
    attempts = []
    async def fetch(url):
        attempts.append(url)
        assert event(external,cfg,t='GROUP_DEL_ROBOT',extra={'group_openid':GROUP}).status_code==200
        raise qq_group_media.AttachmentError('连接中断',retry=True)
    monkeypatch.setattr(qq_group_media,'fetch_file',fetch)
    assert not asyncio.run(qq_group_media.run_one(env[0].state.db,cfg.qq_bot_app_id))
    assert len(attempts)==1
    assert not alice.get('/api/notices').json() and not bob.get('/api/notices').json()


def test_media_redirect_and_size_validation_stops_before_unapproved_request(monkeypatch,caplog):
    seen = []
    def transport(request):
        seen.append(str(request.url))
        if request.url.params['fileid']=='redirect':
            return httpx.Response(302,headers={'location':'https://example.invalid/not-a-qq-file'})
        if request.url.params['fileid']=='approved':
            return httpx.Response(302,headers={'location':'https://gchat.qpic.cn/download?fileid=ok'})
        if request.url.params['fileid']=='ok':
            return httpx.Response(200,stream=httpx.ByteStream(b'synthetic file'))
        return httpx.Response(200,headers={'content-length':str(qq_group_media.MAX_FILE+1)})
    monkeypatch.setattr(qq_group_media,'PublicHTTPTransport',lambda **kwargs:httpx.MockTransport(transport))
    with pytest.raises(qq_group_media.AttachmentError,match='跳转出了 QQ'):
        asyncio.run(qq_group_media.fetch_file(CDN+'redirect'))
    with pytest.raises(qq_group_media.AttachmentError,match='超过 5 MB'):
        asyncio.run(qq_group_media.fetch_file(CDN+'too-large'))
    signed = CDN+'approved&rkey=synthetic-file-token'
    with caplog.at_level('INFO',logger='httpx'):
        assert asyncio.run(qq_group_media.fetch_file(signed)) == b'synthetic file'
    assert 'synthetic-file-token' not in caplog.text
    assert seen == [CDN+'redirect',CDN+'too-large',signed,'https://gchat.qpic.cn/download?fileid=ok']
