"""Inbox categories reflect personal actions without changing their state."""
import json
from uuid import uuid4

from tests.test_workflow import env,account,notice,manual,confirm,task


def category(c,nid):return next(n for n in c.get('/api/notices').json() if n['id']==nid)


def planned(c,mode='task',kind='required'):
    n=manual(c,notice(c,'合成通知 '+uuid4().hex))
    tid=confirm(c,n,task(n,submission='材料交给合成学院系统'),plans={'0':{'execution_mode':mode,'action_kind':kind,'depends_on':[],'conditions':[]}})
    return n['id'],tid


def test_inbox_routes_personal_steps_by_next_action_without_mutation(env):
    c=account(env);db=env[0].state.db
    expected={}
    for mode,bucket in [('task','act'),('decision','decide'),('reading','read'),('waiting','followup')]:
        nid,tid=planned(c,mode);expected[nid]=bucket
    nid,tid=planned(c,'attendance','optional');expected[nid]='decide'
    nid,tid=planned(c,'submission');expected[nid]='followup'
    with db.connect(write=True) as conn:
        row=conn.execute('SELECT data FROM task_workflows WHERE task_id=?',(tid,)).fetchone()
        value=json.loads(row[0]);value['stage']='submitted'
        conn.execute('UPDATE task_workflows SET data=? WHERE task_id=?',(json.dumps(value),tid))
    before=c.get('/api/tasks').json()
    for nid,bucket in expected.items():assert category(c,nid)['intent']==bucket
    assert c.get('/api/tasks').json()==before
    assert len(c.get('/api/notices/search',params={'q':'合成学院系统'}).json())==6


def test_unreviewed_changes_outweigh_done_state_and_old_applicability(env):
    c=account(env);db=env[0].state.db;nid,tid=planned(c)
    with db.connect(write=True) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id=?",(tid,))
    assert category(c,nid)['intent']=='closed'
    with db.connect(write=True) as conn:
        n=conn.execute('SELECT * FROM notices WHERE id=?',(nid,)).fetchone()
        draft=json.loads(n['draft']);draft['applicability']='not_matching'
        conn.execute("UPDATE notices SET status='received',version=version+1,draft=? WHERE id=?",(json.dumps(draft),nid))
        conn.execute('INSERT INTO notice_ingest_updates(id,notice_id,receipt_id,previous_source_ids,new_source_ids,created_at) VALUES(?,?,?,?,?,?)',
                     (uuid4().hex,nid,conn.execute('SELECT id FROM notice_ingest_receipts WHERE notice_id=?',(nid,)).fetchone()[0],'[]','[]',1))
    after=category(c,nid)
    assert after['intent']=='verify' and after['applicability'] is None
    assert c.get('/api/tasks').json()[0]['status']=='done'


def test_profile_change_invalidates_irrelevant_filter_and_other_accounts_see_nothing(env):
    c,other=account(env),account(env,'another');db=env[0].state.db
    n=manual(c,notice(c,'本校某学院通知'))
    with db.connect(write=True) as conn:
        draft=n['draft'];draft['applicability']='not_matching'
        conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(draft),n['id']))
    assert category(c,n['id'])['intent']=='irrelevant'
    uid=c.get('/api/session').json()['user']['id']
    with db.connect(write=True) as conn:
        profile=json.loads(conn.execute('SELECT profile FROM users WHERE id=?',(uid,)).fetchone()[0]);profile['college']='新学院'
        conn.execute('UPDATE users SET profile=? WHERE id=?',(json.dumps(profile),uid))
    after=category(c,n['id'])
    assert after['intent']=='verify' and after['needs_profile_review'] and after['applicability'] is None
    assert other.get('/api/notices').json()==[]


def test_known_reference_and_closed_dispositions_keep_their_place(env):
    c=account(env)
    for disposition,bucket in [('reference','read'),('not_applicable','irrelevant'),('closed','closed')]:
        n=notice(c,'归档状态合成通知 '+disposition)
        result=c.put('/api/notices/'+n['id']+'/disposition',json={'version':n['version'],'disposition':disposition,'note':'本人核对'})
        assert result.status_code==200,result.text
        assert category(c,n['id'])['intent']==bucket
