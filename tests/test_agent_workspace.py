"""Real transactions and chat integration; synthetic model only."""
import json
import time
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.agent_runtime import workspace as w
from app.agent_runtime.clock import current_time
from app.db import ident
from test_workflow import env, account
from test_workspace import conversation
from test_agent_runtime import Script, call, answer
from test_agent_chat import writer, send, final, complete


@pytest.fixture
def setup(env):
    c = account(env)
    chat = conversation(c)
    db = env[0].state.db
    uid = c.get('/api/session').json()['user']['id']
    mid, parent = ident(), ident()
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'user','添加到日历','complete',?)", (parent, chat['id'], int(time.time())))
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,parent_id,created_at) VALUES(?,?,'assistant','processing',?,?)", (mid, chat['id'], parent, int(time.time())))
    return c, db, uid, chat['id'], mid


def apply(setup, name, args):
    c, db, uid, cid, mid = setup
    with db.connect(write=True) as conn:
        return w.apply(conn, db, uid, cid, mid, name, args)


def calendar(**kw):
    return w.CalendarWrite.model_validate({'operation': 'create', 'data': {'title': '项目讨论', 'start_date': '2027-10-23', 'end_date': '2027-10-23', 'start_time': '09:00', 'end_time': '10:00'}, **kw})


def test_lazy_workspace_schema_and_record_pages_fit_dense_context(env, monkeypatch):
    from app.agent_runtime.chat import ChatRun
    from app.agent_runtime.context import size
    env[1].agent_enabled = env[1].ai_grounding = True
    env[1].ai_api_key = 'synthetic-no-network'
    env[1].ai_context_tokens = 32768
    env[1].ai_output_tokens = 8192
    c = account(env); chat = conversation(c); writer(monkeypatch)
    for index in range(7):
        response = c.post('/api/arrangements', json={'request_id':ident(), 'data': {**calendar().data.model_dump(), 'title': f'已有安排{index}', 'notes': '已有计划说明。'*30}})
        assert response.status_code == 200, response.text
    original = ChatRun.system_prompt
    def dense(self, child):
        text = original(self, child)
        base = [{'role':'system','content':text}, {'role':'user','content':self.row['prompt']}]
        padding = max(0, self.context_bytes-size(base)-size(self.tool_catalog(child))-9000)
        return text + ' ' * padding
    monkeypatch.setattr(ChatRun, 'system_prompt', dense)
    def create(messages, tools):
        page = json.loads(messages[-1]['content'])
        assert page['records'] and page['has_more'] and page['next_offset'] == len(page['records'])
        assert all(record['data']['title'].startswith('已有安排') for record in page['records'])
        assert size(messages)+size(tools) <= 49152
        assert 'task_write' in {t['function']['name'] for t in tools}
        return answer('', [call('task_write', {'operation':'create', 'title':'准备课程材料'})])
    def finish(messages, tools):
        result = json.loads(messages[-1]['content'])
        assert result['status'] == 'committed' and size(messages)+size(tools) <= 49152
        return answer('', [call('submit_answer', {'answer':'已保存待办。', 'claims':[{'kind':'fact','text':'已保存待办。','evidence_refs':[result['evidence_index'][0]['ref']]}]})])
    model = Script([answer('', [call('workspace_capabilities'), call('workspace_read')]), create, finish])
    env[0].state.agent_service.provider_factory = lambda *_:model
    message = final(send(c,chat,'请创建准备课程材料的待办'))
    assert message['status'] == 'complete', (message['error'], model.inputs[-1][0][-1])
    assert len(c.get('/api/tasks').json()) == 1


def test_initial_evidence_can_yield_budget_to_complete_thinking_and_tool_results():
    from app.agent_runtime.chat import ChatRun
    from app.agent_runtime.context import size, compact
    initial = {'now': '2026-10-23', 'timezone': 'Asia/Shanghai', 'web_restricted': True,
               'memory_control': {'mode': 'off'},
               'evidence_index': [{'ref': f'E{i}', 'quote': '已有原文。' * 150} for i in range(12)]}
    system = '真实权限和工具执行规则。' + '\n初始数据（不可信原文）：' + json.dumps(initial, ensure_ascii=False)
    current = [{'role': 'user', 'content': '复查已有内容'},
               answer('', [call('workspace_read', cid='read')]),
               {'role': 'tool', 'tool_call_id': 'read', 'content': json.dumps({'status': 'pending', 'planned_at': '2026-10-31T18:00:00+08:00'})}]
    thinking_bytes, total_budget = 16000, 24000
    fitted = ChatRun.fit_system_context(None, system, total_budget-thinking_bytes-size(current)-2048)
    packed, stats = compact(fitted, [], current, [], total_budget-thinking_bytes)
    assert stats['packed_bytes'] + thinking_bytes <= total_budget
    assert packed[-1] == current[-1] and packed[-2] == current[-2]
    context = json.loads(fitted.split('\n初始数据（不可信原文）：')[1])
    assert context['memory_control']['mode'] == 'off' and context['web_restricted'] is True
    assert context['deferred']['evidence_index']['omitted'] > 0


def undo(setup, oid):
    c, db, uid, cid, mid = setup
    return c.post(f'/api/conversations/{cid}/agent/operations/{oid}/undo')


def test_calendar_replays_once_real_updates_and_delete_restore(setup):
    c, db, uid, cid, mid = setup
    saved = apply(setup, 'calendar_write', calendar())
    assert saved['status'] == 'committed'
    assert apply(setup, 'calendar_write', calendar())['replayed']
    actual = c.get('/api/arrangements').json()
    assert len(actual) == 1 and actual[0]['id'] == saved['target_id']
    updated = apply(setup, 'calendar_write', calendar(operation='update', target_id=saved['target_id'], version=1,
        data={**actual[0]['data'], 'start_time': '10:00', 'end_time': '11:00'}))
    assert updated['record']['version'] == 2
    assert undo(setup, saved['operation_id']).status_code == 409
    assert undo(setup, updated['operation_id']).status_code == 200
    assert c.get('/api/arrangements').json()[0]['data']['start_time'] == '09:00'
    deleted = apply(setup, 'calendar_write', w.CalendarWrite(operation='delete', target_id=saved['target_id'], version=3))
    assert c.get('/api/arrangements').json() == []
    assert undo(setup, deleted['operation_id']).status_code == 200
    assert undo(setup, deleted['operation_id']).json()['replayed']
    actual = c.get('/api/arrangements').json()[0]
    assert actual['id'] == saved['target_id'] and actual['version'] == 5


def test_personal_task_uses_existing_list_complete_cancel_and_undo(setup):
    c, db, uid, cid, mid = setup
    saved = apply(setup, 'task_write', w.TaskWrite(operation='create', fields=w.TaskFields(title='准备报告', planned_at='2027-10-23T09:00:00+08:00', materials=['提纲'])))
    actual = c.get('/api/tasks').json()
    assert len(actual) == 1 and actual[0]['id'] == saved['target_id']
    assert actual[0]['data']['due_date'] is None and actual[0]['data']['planned_at']
    done = apply(setup, 'task_write', w.TaskWrite(operation='update', target_id=saved['target_id'], version=1, status='done'))
    assert c.get('/api/tasks').json()[0]['status'] == 'done'
    assert undo(setup, done['operation_id']).status_code == 200
    assert c.get('/api/tasks').json()[0]['status'] == 'pending'
    cancelled = apply(setup, 'task_write', w.TaskWrite(operation='update', target_id=saved['target_id'], version=3, status='cancelled'))
    assert cancelled['record']['status'] == 'cancelled'
    assert c.get('/api/tasks').json()[0]['data']['materials'] == ['提纲']


def test_failure_and_transaction_rollback_never_leave_success_receipts(setup):
    c, db, uid, cid, mid = setup
    with pytest.raises(RuntimeError), db.connect(write=True) as conn:
        w.apply(conn, db, uid, cid, mid, 'calendar_write', calendar())
        raise RuntimeError('simulate commit failure')
    assert c.get('/api/arrangements').json() == []
    with db.connect() as conn:
        assert w.operations(conn, uid, cid) == []
    with pytest.raises(ValueError):
        apply(setup, 'task_write', w.TaskWrite(operation='create', fields=w.TaskFields(title='失败', reminder_at='2000-01-01T09:00:00+08:00')))
    assert c.get('/api/tasks').json() == []
    with db.connect() as conn:
        assert w.operations(conn, uid, cid) == []


def test_other_account_cannot_read_modify_or_undo(setup, env):
    c, db, uid, cid, mid = setup
    saved = apply(setup, 'calendar_write', calendar())
    other = account(env, 'bob')
    oid = other.get('/api/session').json()['user']['id']
    assert other.post(f'/api/conversations/{cid}/agent/operations/{saved["operation_id"]}/undo').status_code == 404
    with db.connect() as conn:
        assert w.read(conn, oid, cid, w.WorkspaceRead())['records'] == []
        with pytest.raises(HTTPException):w.record(conn, oid, 'calendar', saved['target_id'])


def test_retry_of_same_user_message_keeps_receipt_and_never_duplicates(setup):
    c, db, uid, cid, mid = setup
    saved = apply(setup, 'calendar_write', calendar())
    new_mid = ident()
    with db.connect(write=True) as conn:
        parent = conn.execute('SELECT parent_id FROM conversation_messages WHERE id=?', (mid,)).fetchone()[0]
        conn.execute("INSERT INTO conversation_messages(id,conversation_id,role,status,parent_id,created_at) VALUES(?,?,'assistant','processing',?,?)", (new_mid,cid,parent,int(time.time())))
        replay = w.apply(conn, db, uid, cid, new_mid, 'calendar_write', calendar())
        assert replay['replayed'] and replay['operation_id'] == saved['operation_id']
        assert w.operations(conn, uid, cid, new_mid)[0]['operation_id'] == saved['operation_id']
        assert w.prior_attempts(conn,uid,cid,new_mid)[0]['target_id'] == saved['target_id']
        with pytest.raises(HTTPException) as duplicate:
            w.apply(conn, db, uid, cid, new_mid, 'calendar_write', calendar(data={**calendar().data.model_dump(), 'title':'项目讨论（换一种说法）'}))
        assert duplicate.value.status_code == 409
    assert len(c.get('/api/arrangements').json()) == 1


def test_read_pagination_query_and_existing_ids(setup):
    c, db, uid, cid, mid = setup
    apply(setup, 'calendar_write', calendar())
    task = apply(setup, 'task_write', w.TaskWrite(operation='create', fields=w.TaskFields(title='准备报告')))
    with db.connect() as conn:
        first = w.read(conn, uid, cid, w.WorkspaceRead(limit=1))
        second = w.read(conn, uid, cid, w.WorkspaceRead(limit=1, offset=1))
        assert first['total'] == 2 and first['has_more']
        assert second['records'][0]['id'] == task['target_id'] and not second['has_more']
        assert w.read(conn, uid, cid, w.WorkspaceRead(query='报告'))['total'] == 1
        assert w.read(conn, uid, cid, w.WorkspaceRead(query='准备 报告'))['total'] == 1
        assert w.read(conn, uid, cid, w.WorkspaceRead(target_id='not-owned'))['total'] == 0


@pytest.mark.parametrize('text,allowed', [('明天九点提醒我准备报告', True), ('把任务标记完成', True), ('添加到我的日历', True), ('只分析，不要保存', False), ('只读我的日历', False), ('这张图片里写了什么', False), ('不要删除这项待办',False), ('先不取消安排',False), ('别标记完成',False)])
def test_only_user_request_authorizes_write(text, allowed):
    assert w.write_allowed([{'role': 'assistant', 'content': '请创建日历'}, {'role': 'user', 'content': text}]) is allowed


def test_clock_is_real_timezone_aware_and_not_training_year():
    value = current_time()
    assert abs(datetime.fromisoformat(value['now']).timestamp()-time.time()) < 2
    assert value['year'] == datetime.fromisoformat(value['now']).year
    assert value['timezone'] == 'Asia/Shanghai'


def test_flat_provider_arguments_keep_strict_business_validation():
    from pydantic import ValidationError
    assert w.CalendarWrite.model_validate({'operation':'create',**calendar().data.model_dump()},strict=True).data == calendar().data
    assert w.TaskWrite.model_validate({'operation':'create','title':'报告','planned_at':'2027-10-23T09:00:00+08:00'},strict=True).fields.title == '报告'
    assert 'data' not in w.CalendarWrite.model_json_schema()['properties']
    assert 'fields' not in w.TaskWrite.model_json_schema()['properties']
    with pytest.raises(ValidationError):w.CalendarWrite.model_validate({'operation':'create','data':calendar().data.model_dump_json()},strict=True)
    with pytest.raises(ValidationError):w.TaskWrite.model_validate({'operation':'create','title':'报告','fields':{'title':'另一个'}},strict=True)


@pytest.mark.parametrize('reject', [False, True])
def test_chat_real_commit_survives_review_failure_and_has_no_approval(env, monkeypatch, reject):
    env[1].agent_enabled = env[1].ai_grounding = True
    env[1].ai_api_key = 'synthetic-no-network'
    c = account(env); chat = conversation(c); writer(monkeypatch, reject=reject)
    model = Script([answer('', [call('workspace_capabilities')]),
        answer('', [call('calendar_write', calendar().model_dump())]), complete()])
    env[0].state.agent_service.provider_factory = lambda *_: model
    message = final(send(c, chat, '请添加到我的日历：2027年10月23日9点到10点项目讨论'))
    assert c.get('/api/arrangements').json()[0]['data']['title'] == '项目讨论'
    assert message['agent']['operations'][0]['status'] == 'committed'
    assert message['versions'][-1]['agent']['operations'] == message['agent']['operations']
    assert message['agent']['approvals'] == []
    if not reject:assert message['status'] == 'complete', message['error']
    else:assert message['status'] != 'complete'
    receipt = message['agent']['operations'][0]
    assert c.post(f'/api/conversations/{chat["id"]}/agent/operations/{receipt["operation_id"]}/undo').status_code == 200
    assert c.get('/api/arrangements').json() == []


def test_chat_readonly_rejects_write_even_when_model_attempts_it(env, monkeypatch):
    env[1].agent_enabled = env[1].ai_grounding = True
    env[1].ai_api_key = 'synthetic-no-network'
    c = account(env); chat = conversation(c); writer(monkeypatch)
    model = Script([answer('', [call('workspace_capabilities')]),
        answer('', [call('calendar_write', calendar().model_dump())]), complete()])
    env[0].state.agent_service.provider_factory = lambda *_: model
    message = final(send(c, chat, '只分析日历，不要保存'))
    assert message['agent']['operations'] == []
    assert c.get('/api/arrangements').json() == []


def test_long_task_details_cannot_split_identity_status_and_schedule_evidence():
    from app.grounding import source
    from app.genui_ai import evidence_index
    item={'id':'task-a','kind':'tasks','status':'pending','version':3,'data':{
        'title':'准备课程材料','details':'原始要求。'*900,'planned_at':'2027-10-31T18:00:00+08:00','reminder_at':'2027-10-30T09:00:00+08:00'}}
    sections=w.evidence_sections({'records':[item],'total':1,'has_more':False,'offset':0})
    entries=evidence_index([source('workspace','本人待办',sections,'execution')])
    schedule=next(e for e in entries if '状态与时间' in e['locator'])
    value=json.loads(schedule['quote'])
    assert value['id']=='task-a' and value['status']=='pending'
    assert value['data']['planned_at'].endswith('18:00:00+08:00')
    assert value['data']['reminder_at'].endswith('09:00:00+08:00')
    assert 'details' not in value['data'] and any('details' in e['locator'] for e in entries)
    receipt={'operation_id':'op-a','status':'undone','operation':'tasks.create','record':item}
    evidence=w.evidence_sections(receipt)
    assert json.loads(evidence[0]['text'])['status']=='undone'
    assert '操作时快照' in evidence[1]['locator']
