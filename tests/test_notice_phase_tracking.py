import json
import sqlite3

import pytest

from app.db import Database
from tests.test_workflow import account,env,notice,manual,confirm,task


def path(n):return '/api/notices/'+n['id']+'/lifecycle-tracking'


def evidence(n):
    source=n['sources'][0];part=source['sections'][0]
    return {'source_id':source['id'],'locator':part['locator'],'quote':part['text']}


def save(client,n,data,version=0):
    return client.put(path(n),json={'version':version,'notice_version':n['version'],'data':data})


def test_unannounced_lead_has_real_personal_followup_without_official_deadline(env):
    client=account(env);n=notice(client,'朋友说下周可能发布奖学金通知，尚待官网确认。')
    result=save(client,n,{'phase':'unannounced','basis':'personal_lead','note':'下周查学院官网'})
    assert result.status_code==200,result.text
    assert not client.get('/api/tasks').json()
    bad=save(client,n,{'phase':'unannounced','basis':'personal_lead','objection_window':{'end_date':'2027-12-01','evidence':[evidence(n)]}},version=1)
    assert bad.status_code==422
    payload={'version':1,'notice_version':n['version'],'kind':'check_publication','arrangement':{'request_id':'followup_request_12345678','data':{
        'title':'查看是否正式公告','category':'personal','start_date':'2027-12-01','end_date':'2027-12-01','reminder_minutes':0}}}
    first=client.post(path(n)+'/followup',json=payload)
    assert first.status_code==200,first.text
    repeated=client.post(path(n)+'/followup',json=payload)
    assert repeated.status_code==200,repeated.text
    items=client.get('/api/arrangements').json()
    assert len(items)==1 and items[0]['data']['reminder_minutes']==0
    assert first.json()['created_followup']['id']==repeated.json()['created_followup']['id']==items[0]['id']
    assert not client.get('/api/tasks').json()


def test_publicity_expiry_never_becomes_final_and_dates_need_actual_quotes(env):
    client=account(env);n=notice(client,'公示时间为2025年10月1日至2025年10月7日17:00，名单仅为拟推荐。')
    data={'phase':'publicity','basis':'official_notice','evidence':[evidence(n)],'objection_intent':'considering',
        'objection_window':{'start_date':'2025-10-01','end_date':'2025-10-07','end_time':'17:00','evidence':[evidence(n)]}}
    result=save(client,n,data)
    assert result.status_code==200,result.text
    state=result.json()
    assert state['objection_window_closed'] and not state['publicity_is_final_result']
    assert state['data']['phase']=='publicity' and state['data']['outcome']=='unknown'
    assert save(client,n,{**data,'outcome':'selected','identity_confirmed':True,'identity_note':'已核对学号'},version=1).status_code==422
    forged={**data,'objection_window':{**data['objection_window'],'end_date':'2025-12-01'}}
    assert save(client,n,forged,version=1).status_code==422


def test_results_require_identity_check_and_keep_followup_task_receipts(env):
    client=account(env);n=manual(client,notice(client,'正式结果公布，入选者需核实本人身份后确认名额。'))
    tid=confirm(client,n,task(n,title='确认名额',due_date=None,due_time=None,deadline_text='',deadline_confirmed=False))
    n=client.get('/api/notices/'+n['id']).json()
    data={'phase':'result','basis':'official_notice','evidence':[evidence(n)],'outcome':'selected','actions':[{'kind':'confirm_place','task_id':tid}]}
    assert save(client,n,data).status_code==422
    data.update(identity_confirmed=True,identity_note='本人逐项对照学号与院系，已核实')
    result=save(client,n,data)
    assert result.status_code==200,result.text
    assert result.json()['actions'][0]['task_id']==tid
    assert client.get('/api/tasks/'+tid+'/workflow').json()['task']['workflow']['data']['stage']=='preparing'
    assert client.get('/api/notices').json()[0]['phase_tracking']['outcome']=='selected'


def test_tracking_is_owner_scoped_versioned_and_invalidated_by_corrected_evidence(env):
    client,other=account(env),account(env,'stranger');n=notice(client,'公示原文请核对。');foreign=notice(other,'其他人的正文。')
    assert other.get(path(n)).status_code==404
    assert save(client,n,{'phase':'publicity','basis':'official_notice','evidence':[evidence(foreign)]}).status_code==422
    data={'phase':'publicity','basis':'official_notice','evidence':[evidence(n)]}
    assert save(client,n,data).status_code==200
    assert save(client,n,data).status_code==409
    with env[0].state.db.connect(write=True) as conn:conn.execute('UPDATE notices SET version=version+1 WHERE id=?',(n['id'],))
    assert client.get(path(n)).json()['review_required']
    assert save(client,n,data,version=1).status_code==409


def test_tracking_survives_backup_and_rejects_missing_tables(env,tmp_path):
    client=account(env);n=notice(client,'尚待正式公告。');assert save(client,n,{'note':'本人跟进'}).status_code==200
    target=tmp_path/'tracking.sqlite3';env[0].state.db.backup(target)
    restored=Database(target)
    with restored.connect() as conn:assert json.loads(conn.execute('SELECT data FROM notice_phase_tracking').fetchone()[0])['note']=='本人跟进'
    with sqlite3.connect(target) as conn:conn.execute('DROP TABLE notice_phase_tracking')
    with pytest.raises((ValueError,RuntimeError),match='通知阶段跟踪|notice_tracking_schema_version'):Database(target)


def test_portable_phase_history_preserves_quotes_without_restoring_result_or_reminders(env):
    a,b,c=account(env),account(env,'imported-phases'),account(env,'reexported-phases')
    n=notice(a,'正式结果：名单须由本人核实身份，确认名额后办理。')
    data={'phase':'result','basis':'official_notice','evidence':[evidence(n)],'outcome':'selected',
        'identity_confirmed':True,'identity_note':'本人核对学号与院系','note':'曾确认拟入选，等待后续'}
    assert save(a,n,data).status_code==200
    exported=a.get('/api/export').json()
    assert exported['notice_phase_tracking'][0]['data']['outcome']=='selected'
    def restore(client,payload):
        preview=client.post('/api/import',json={'data':payload})
        assert preview.status_code==200,preview.text
        result=client.post('/api/import',json={'data':payload,'confirm':True,'digest':preview.json()['digest']})
        assert result.status_code==200,result.text
        return client.get('/api/notices').json()[0]
    imported=restore(b,exported)
    state=b.get(path(imported)).json()
    assert state['notice_version']==0 and state['review_required']
    assert state['data']['outcome']=='unknown' and not state['data']['identity_confirmed']
    assert not state['actions'] and not state['followups']
    assert state['imported_history'][0]['data']['evidence']==data['evidence']
    assert state['imported_history'][0]['data']['outcome']=='selected'
    assert restore(b,exported)['id']==imported['id']
    again=restore(c,b.get('/api/export').json())
    assert len(c.get(path(again)).json()['imported_history'])==1


@pytest.mark.parametrize('include_related',[False,True])
def test_batched_phase_summary_keeps_related_version_and_owner_checks(env,include_related):
    from app.notice_matters import annotate
    from app.notice_tracking import summary
    from tests.test_notice_matters import join
    client,other=account(env),account(env,'summary-other')
    a=notice(client,'本人等待正式公告的线索。');b=notice(client,'另一个待核对的补充线索。')
    untracked=notice(client,'尚未建立阶段记录的线索。');foreign=notice(other,'其他账号的私有线索。')
    group=join(client,a,b)
    assert save(client,a,{'related_notice_versions':{b['id']:b['version']}}).status_code==200
    assert save(other,foreign,{'note':'不应进入本人列表'}).status_code==200
    uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    ids=[a['id'],untracked['id'],foreign['id']]+([b['id']] if include_related else [])
    with db.connect(write=True) as conn:
        statements=[];conn.set_trace_callback(statements.append)
        records={r['id']:r for r in annotate(conn,uid,[{'id':nid} for nid in ids])}
        conn.set_trace_callback(None)
        selects=[s for s in statements if s.lstrip().upper().startswith('SELECT')]
        assert len(selects)==(1 if include_related else 2)
        phase=records[a['id']]['phase_tracking']
        assert phase==summary(conn,uid,[a['id']])[a['id']]
        assert phase['phase']=='unannounced' and not phase['review_required']
        assert records[a['id']]['matter']=={'notice_id':a['id'],'id':group['id'],
            'title':group['title'],'version':group['version'],'member_count':2}
        assert records[untracked['id']]['phase_tracking'] is None
        assert records[foreign['id']]['phase_tracking'] is None and records[foreign['id']]['matter'] is None
        assert summary(conn,uid,[foreign['id']])=={}
        conn.execute('UPDATE notices SET version=version+1 WHERE id=?',(b['id'],))
        changed=annotate(conn,uid,[{'id':nid} for nid in ids])
        assert next(r for r in changed if r['id']==a['id'])['phase_tracking']['review_required']
        assert summary(conn,uid,[a['id']])[a['id']]['review_required']
        conn.execute('DELETE FROM notices WHERE id=?',(b['id'],))
        removed=annotate(conn,uid,[{'id':a['id']}])[0]
        assert removed['phase_tracking']['review_required']
