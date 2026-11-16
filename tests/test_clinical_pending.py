import asyncio
import io
import time
import zipfile

import httpx
import pytest

from app import notice_automation,notice_intake,source_fetch,source_sync
from app.official_sources import get_preset
from tests.test_workflow import account,env


def docx_bytes():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>附件申请材料内容</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


@pytest.mark.parametrize(('preset_id','blocked_code'),[
    ('whu-college-rmhospital',521),('whu-college-znhospital',412)])
def test_pending_hospitals_activate_for_subscribers_and_deliver_body_and_attachment(env,monkeypatch,preset_id,blocked_code):
    app,_=env;clients=[account(env),account(env,'second')];preset=get_preset(preset_id)
    first=preset_id.endswith('rmhospital');blocked=True;calls=[];attachment=docx_bytes()
    if first:
        entries=''.join(f'<li><span class="day">0{i}</span><span class="mon">2026-11</span><a href="/article/id/{i}.html">学院通知{i}</a></li>' for i in (1,2))
        index='<div class="innoticelist">'+entries+'</div>'
    else:
        entries=''.join(f'<div class="item"><a href="/graduate_student_notice_detail/{i}.html"><div class="t1">学院通知{i}</div><div class="t3">2026-11-0{i}</div></a></div>' for i in (1,2))
        index='<div id="datalist">'+entries+'</div>'
    def handler(request):
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
        calls.append(request.url.path)
        if blocked:return httpx.Response(blocked_code)
        if request.url.path==httpx.URL(preset['url']).path:body=index
        elif request.url.path.endswith('.docx'):
            return httpx.Response(200,headers={'content-type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},content=attachment)
        elif first:
            number=request.url.path.rsplit('/',1)[-1].split('.')[0]
            body=f'<div class="contentout"><div class="title">学院通知{number}</div><div class="newsinfo">2026-11-0{number}</div><div class="content"><p>通知正文需要提交申请材料，事项{number}。</p><a href="/files/form.docx">申请表.docx</a></div></div>'
        else:
            number=request.url.path.rsplit('/',1)[-1].split('.')[0]
            body=f'<div class="article-page"><div class="article-head"><div class="t">学院通知{number}</div><span>2026-11-0{number}</span></div><div class="article-cont"><p>通知正文需要提交申请材料，事项{number}。</p><a href="/files/form.docx">申请表.docx</a></div></div>'
        return httpx.Response(200,headers={'content-type':'text/html; charset=utf-8'},text=body)
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(handler))
    monkeypatch.setattr(source_fetch,'DOMAIN_INTERVAL',0)
    results=[client.post('/api/source-presets/'+preset_id+'/subscribe',json={}) for client in clients]
    assert all(r.status_code==200 and r.json()['pending'] for r in results)
    ids=[r.json()['source_id'] for r in results]
    assert len(calls)==1
    assert all(c.get('/api/source-subscriptions').json()[-1]['state']=='awaiting_access' for c in clients)
    with app.state.db.connect(write=True) as conn:
        assert conn.execute('SELECT count(*) FROM source_subscriptions').fetchone()[0]==0
        conn.execute('UPDATE source_host_limits SET retry_after=0')
        conn.execute('UPDATE source_pending_groups SET next_attempt=0')
    asyncio.run(source_sync.activate_pending_group(app.state.db,preset_id))
    assert len(calls)==2  # a failed retry serves the whole group
    with app.state.db.connect(write=True) as conn:
        group=conn.execute('SELECT * FROM source_pending_groups WHERE preset_id=?',(preset_id,)).fetchone()
        assert group['next_attempt']>=int(time.time())+1700
        conn.execute('UPDATE source_host_limits SET retry_after=0')
        conn.execute('UPDATE source_pending_groups SET next_attempt=0')
    blocked=False
    asyncio.run(source_sync.activate_pending_group(app.state.db,preset_id))
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM source_pending_activations').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM source_subscriptions WHERE enabled=1').fetchone()[0]==2
    for client,sid in zip(clients,ids):
        uid=client.get('/api/session').json()['user']['id']
        outcome=asyncio.run(source_sync.sync_source(app.state.db,sid,uid))
        assert outcome['received_count']==2
        notices=client.get('/api/notices').json()
        assert len(notices)==2
        notice=client.get('/api/notices/'+notices[0]['id']).json()
        assert any('通知正文需要提交申请材料' in part['text'] for source in notice['sources'] for part in source['sections'])
        assert any(source['kind']=='docx' and any('附件申请材料内容' in p['text'] for p in source['sections']) for source in notice['sources'])
        assert not client.get('/api/notice-automation').json()['enabled']
    assert len([p for p in calls if p.endswith('.docx')])==2  # one per distinct parent, reused across accounts
    with app.state.db.connect() as conn:
        originals=conn.execute("SELECT s.content FROM sources s JOIN notices n ON n.id=s.notice_id WHERE s.kind='docx'").fetchall()
        assert len(originals)==4 and all(row['content']==attachment for row in originals)
        assert conn.execute('SELECT count(*) FROM ai_calls').fetchone()[0]==0
    # The collector remains AI-free even when a subscriber explicitly enabled
    # automatic AI organization for their other sources.
    for client in clients:
        current=client.get('/api/notice-automation').json()
        result=client.put('/api/notice-automation',json={'enabled':True,'allow_external_processing':True,
                          'daily_limit':10,'version':current['version']})
        assert result.status_code==200,result.text
    # A duplicate previously received via another source can retain that
    # source's origin metadata instead of the clinical parser ID.
    with app.state.db.connect(write=True) as conn:
        conn.execute("UPDATE notice_source_origins SET data=json_remove(data,'$.parser_id')")
    assert notice_automation.run_once(app,app.state.db,env[1]) is None
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM notice_automation_jobs').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM ai_calls').fetchone()[0]==0


def test_pending_cancel_is_owner_scoped_and_does_not_activate(env,monkeypatch):
    app,_=env;a,b=account(env),account(env,'second');preset='whu-college-rmhospital'
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(lambda request:httpx.Response(521)))
    result=a.post('/api/source-presets/'+preset+'/subscribe',json={}).json();sid=result['source_id']
    assert b.delete('/api/source-catalog/'+sid+'/subscription/pending').status_code==404
    cancelled=a.delete('/api/source-catalog/'+sid+'/subscription/pending')
    assert cancelled.status_code==200 and cancelled.json()['state']=='manual'
    asyncio.run(source_sync.activate_pending_group(app.state.db,preset))
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM source_subscriptions').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM source_pending_groups').fetchone()[0]==0


def test_cancel_during_successful_trial_cannot_reactivate_source(env,monkeypatch):
    app,_=env;client=account(env);preset='whu-college-rmhospital'
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(lambda request:httpx.Response(521)))
    sid=client.post('/api/source-presets/'+preset+'/subscribe',json={}).json()['source_id']
    with app.state.db.connect(write=True) as conn:conn.execute('UPDATE source_pending_groups SET next_attempt=0')
    async def exercise():
        started=asyncio.Event();resume=asyncio.Event()
        async def trial(*args):
            started.set();await resume.wait();return {'can_apply':True,'trial_id':'unused'}
        monkeypatch.setattr(source_sync,'trial_rule',trial)
        task=asyncio.create_task(source_sync.activate_pending_group(app.state.db,preset))
        await started.wait()
        assert client.delete('/api/source-catalog/'+sid+'/subscription/pending').status_code==200
        resume.set();await task
    asyncio.run(exercise())
    with app.state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM source_subscriptions').fetchone()[0]==0


def test_restoring_backup_does_not_reactivate_old_pending_opt_in(env,monkeypatch,tmp_path):
    from app.backups import restore_database
    import sqlite3
    app,cfg=env;client=account(env);preset='whu-college-rmhospital'
    monkeypatch.setattr(source_sync,'PublicHTTPTransport',lambda:httpx.MockTransport(lambda request:httpx.Response(521)))
    assert client.post('/api/source-presets/'+preset+'/subscribe',json={}).json()['pending']
    target=tmp_path/'restored'/'campus.sqlite3'
    restore_database(cfg.data_dir/'campus.sqlite3',target)
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT count(*) FROM source_pending_activations').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM source_pending_groups').fetchone()[0]==0
