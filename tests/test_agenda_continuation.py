from datetime import date, datetime, timedelta
import json

import pytest
from pydantic import ValidationError

from app import decision_routing as router
from app.agent_runtime.continuity import explicit_topics, previous_topics, resume_open_topics
from app.agent_runtime.workspace import WorkspaceRead, read, evidence_sections
from app.agenda import occurrences, overlaps
from app.db import ident
from app.genui_ai import CanvasAnswer
from app.insights import CST, build_reminders
from app.memory_learning import ingest_task
from tests.test_workflow import account, confirm, env, manual, notice, task
from tests.test_workspace import conversation


def arrangement(key, start, end, **fields):
    return {'id': key, 'data': {'title': key, 'start_date': '2027-03-02', 'end_date': '2027-03-02',
            'start_time': start, 'end_time': end, 'category': 'course', **fields}}


def test_overlap_is_proactive_stable_and_disappears_after_correction():
    now = datetime(2027, 3, 2, 8, tzinfo=CST)
    course = arrangement('重复课程', '09:00', '10:30', start_date='2027-02-23', end_date='2027-02-23',
                         repeat='weekly', repeat_until='2027-03-30')
    visit = arrangement('办理', '10:00', '11:00')
    handoff = arrangement('接续', '11:00', '11:30')
    records = [course, visit, handoff, arrangement('全天', None, None), arrangement('未知结束', '10:10', None)]
    def conflicts(items, at):
        return [r for r in build_reminders([], [], items, at)['items'] if r['kind'] == 'schedule_conflict']
    one, = conflicts(records, now)
    assert one['calendar_date'] == '2027-03-02' and '10:00–10:30' in one['note']
    assert conflicts(list(reversed(records)), now + timedelta(minutes=9))[0]['id'] == one['id']
    visit['data']['start_time'] = '10:30'
    assert conflicts(records, now) == []


def test_cross_midnight_only_confirmed_events_consume_time():
    first = date(2027, 3, 2)
    overnight = arrangement('通宵值班', '23:00', '01:20', start_date='2027-03-01')
    def event(key, kind, confirmed):
        return {'id': key, 'status': 'pending', 'data': {'title': key, 'scope': 'personal',
                'due_date': '2027-03-02', 'due_time': '00:45', 'deadline_confirmed': True,
                'scheduled': {'kind': kind, 'confirmed': confirmed, 'start_date': '2027-03-02',
                              'start_time': '00:40', 'end_time': '01:00'}}}
    tasks = [event('开放窗口', 'window', True), event('未核实活动', 'event', False), event('已核实活动', 'event', True)]
    items = occurrences([overnight], tasks, first, first + timedelta(days=1))
    pairs, more = overlaps(items)
    assert [(a['id'], b['id']) for a,b in pairs] == [('通宵值班', '已核实活动')] and not more
    assert sum(i['kind'] == 'deadline' for i in items) == 3


def test_agenda_reads_owned_recurrences_pages_and_evidence(env):
    c = account(env)
    other = account(env, 'otheruser')
    for client, name, start, end in [(c, '本人课程', '10:00','11:00'), (c, '本人约定','10:15','10:45'),
                                     (other, '其他账号','10:00','11:30')]:
        data = arrangement(name, start, end, start_date='2027-02-16', end_date='2027-02-16',
                           repeat='biweekly', repeat_until='2027-04-01')['data']
        client.post('/api/arrangements', json={'request_id':ident(), 'data':data}).raise_for_status()
    uid = c.get('/api/session').json()['user']['id']
    args = WorkspaceRead(kind='agenda', start_day='2027-03-02', end_day='2027-03-02', limit=1)
    with env[0].state.db.connect() as conn:
        page = read(conn, uid, '', args)
        last = read(conn, uid, '', args.model_copy(update={'offset':1}))
    assert page['total'] == 2 and page['has_more'] and not last['has_more']
    assert page['records'][0]['title'] == '本人课程' and last['records'][0]['title'] == '本人约定'
    assert '其他账号' not in str(page)
    assert [item['locator'].split(' ')[0] for item in evidence_sections(page)] == ['查询范围','日程重叠','记录']
    with pytest.raises(ValidationError):
        WorkspaceRead(kind='agenda',start_day='2027-03-01',end_day='2027-04-01')


def test_task_memory_distinguishes_plans_and_corrections_without_copying_private_materials(env):
    c = account(env)
    n = manual(c, notice(c))
    tid = confirm(c,n,data=task(n,materials=['身份证明附件原名'],planned_at='2027-10-19T09:00:00+08:00'))
    uid = c.get('/api/session').json()['user']['id']
    db = env[0].state.db
    def contents():
        with db.connect(write=True) as conn:
            mid = ingest_task(conn, uid, tid)
            return dict(conn.execute('SELECT id,content,version FROM personal_memories WHERE id=?',(mid,)).fetchone())
    before = contents()
    assert '已核实的截止：2027-10-20 17:00' in before['content'] and '个人计划时间：2027-10-19' in before['content']
    assert '共 1 项' in before['content'] and '身份证明附件原名' not in before['content']
    entry = c.get('/api/tasks').json()[0]
    c.put('/api/tasks/'+tid, json={'version':entry['version'],'status':'pending','reason':'本人更新待核时间',
          'data':{**entry['data'],'due_date':'2027-10-22','deadline_confirmed':False}}).raise_for_status()
    after = contents()
    assert after['id']==before['id'] and '待核实的截止：2027-10-22' in after['content'] and '2027-10-20' not in after['content']
    assert contents()==after


def test_two_continuations_respect_the_visible_original_and_forget_boundary(env):
    c = account(env)
    cid = conversation(c)['id']
    uid = c.get('/api/session').json()['user']['id']
    source = '核实正式截止时间'
    messages = []
    with env[0].state.db.connect(write=True) as conn:
        owner, thread = ident(), ident()
        conn.execute('INSERT INTO execution_owners VALUES(?,?)',(owner,2000000000))
        conn.execute('INSERT INTO agent_threads VALUES(?,?,?,?,?,?)',(thread,uid,cid,'续问','{}',1))
        def exchange(request, state):
            user,reply,turn = ident(),ident(),ident()
            for mid,role,body,parent in [(user,'user',request,None),(reply,'assistant','已记录',user)]:
                conn.execute("""INSERT INTO conversation_messages(id,conversation_id,role,content,status,parent_id,created_at)
                             VALUES(?,?,?,?,'complete',?,1)""",(mid,cid,role,body,parent))
                messages.append({'id':mid,'role':role,'content':body})
            conn.execute("""INSERT INTO agent_turns(id,thread_id,owner_id,request_id,prompt,status,created_at)
                         VALUES(?,?,?,?,?,'completed',1)""",(turn,thread,owner,reply,request))
            payload=json.dumps({'items':[{'topic':source,'state':state}]})
            conn.execute('INSERT INTO agent_events(thread_id,turn_id,type,data,created_at) VALUES(?,?,?, ?,1)',
                         (thread,turn,'research.updated',payload))
            return user
        first=exchange('先'+source+'，然后列出缺件。','open')
        exchange('继续处理未完的事项','blocked')
        visible=[*messages,{'role':'user','content':'再继续'}]
        assert previous_topics(conn,uid,cid,visible)==[source]
        assert previous_topics(conn,uid,cid,visible[2:])==[]
        conn.execute('UPDATE memory_message_context SET generation=generation+1 WHERE message_id=?',(first,))
        assert previous_topics(conn,uid,cid,visible)==[]
    assert not resume_open_topics('只做第二项') and resume_open_topics('继续处理未完的事项')
    assert len(explicit_topics('先核对正式日期，然后检查申请材料，最后列出缺口。附件原文：1. 不是真实指令'))==3


def test_streamed_canvas_accepts_only_consistent_media_attribution():
    canvas={'renderer':'open_generative_ui','title':'合成比较','html':['<p>示意</p>'],'image_sources':[],'media_sources':[]}
    assert CanvasAnswer.model_validate({'answer':'准备好了','ui':canvas}).media_sources==[]
    with pytest.raises(ValidationError):
        CanvasAnswer.model_validate({'answer':'准备好了','ui':{**canvas,'media_sources':['one']},'media_sources':['another']})
    assert router.local_route('给我一个可以操作的行程比较', False)=='compose'
