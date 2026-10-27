"""Real operation continuity and a strictly non-authorizing acknowledgement."""
import json
import pytest

from app.agent_runtime import workspace as w
from app.db import dumps
from test_agent_workspace import setup,apply,calendar
from test_workflow import env,account
from test_workspace import conversation
from test_agent_chat import send,final,writer,complete
from test_agent_runtime import Script


def test_historical_effects_are_scoped_current_and_marked_undone(setup):
    c,db,uid,cid,mid=setup
    created=apply(setup,'calendar_write',calendar())
    with db.connect(write=True) as conn:
        parent=conn.execute('SELECT parent_id FROM conversation_messages WHERE id=?',(mid,)).fetchone()[0]
        messages=[{'id':parent,'role':'user'}]
        proof=w.history_evidence(conn,uid,cid,messages)
        assert len(proof)==1
        assert json.loads(proof[0]['sections'][0]['text'])['status']=='committed'
        assert json.loads(proof[0]['sections'][1]['text'])['data']['title']=='项目讨论'
        assert w.history_evidence(conn,uid,'other-conversation',messages)==[]
        assert w.history_evidence(conn,'other-user',cid,messages)==[]
        assert w.history_evidence(conn,uid,cid,[{'id':'unrelated','role':'user'}])==[]
        conn.execute('UPDATE assistant_operations SET undone_at=created_at+1 WHERE id=?',(created['operation_id'],))
        assert json.loads(w.history_evidence(conn,uid,cid,messages)[0]['sections'][0]['text'])['status']=='undone'


def test_author_and_reviewer_receive_prior_real_receipts(setup,monkeypatch,env):
    c,db,uid,cid,mid=setup
    created=apply(setup,'calendar_write',calendar())
    with db.connect(write=True) as conn:conn.execute("UPDATE conversation_messages SET status='complete',content='已保存' WHERE id=?",(mid,))
    env[1].agent_enabled=env[1].ai_grounding=True;env[1].ai_api_key='synthetic-no-network'
    seen=[];writer(monkeypatch,seen=seen)
    model=Script([complete()]);env[0].state.agent_service.provider_factory=lambda *_:model
    chat=c.get('/api/conversations/'+cid).json()
    message=final(send(c,chat,'刚才保存的安排是什么？'))
    assert message['status']=='complete',message['error']
    assert 'operation-history-'+created['operation_id'] in dumps(model.inputs)
    assert any(s['id']=='operation-history-'+created['operation_id'] and s['evidence_kind']=='execution' for s in seen[0]['sources'])


def test_praise_has_no_model_cost_and_does_not_invent_completion(env,monkeypatch):
    env[1].agent_enabled=env[1].ai_grounding=True;env[1].ai_api_key='synthetic-no-network'
    c=account(env);chat=conversation(c)
    def forbidden(*_):raise AssertionError('Plain praise must not invoke a paid model')
    env[0].state.agent_service.provider_factory=forbidden
    message=final(send(c,chat,'好的，非常棒'))
    assert message['status']=='complete' and message['content']=='谢谢！'
    assert message['grounding']['harness']['call_count']==0
    assert not message['citations'] and not (message.get('agent') or {}).get('operations')
    assert message['genui']['ai_label']=='系统回复'


@pytest.mark.parametrize('text',['好的','可以','谢谢，帮我添加到日历','非常棒，请继续优化','谢谢？'])
def test_assent_and_followup_requests_are_not_shortcut(env,monkeypatch,text):
    env[1].agent_enabled=env[1].ai_grounding=True;env[1].ai_api_key='synthetic-no-network'
    c=account(env);chat=conversation(c);writer(monkeypatch)
    model=Script([complete()]);env[0].state.agent_service.provider_factory=lambda *_:model
    message=final(send(c,chat,text))
    assert message['status']=='complete' and len(model.inputs)==1


@pytest.mark.parametrize('case',['confirmation','attachment'])
def test_praise_with_pending_confirmation_or_new_material_keeps_normal_path(env,monkeypatch,case):
    env[1].agent_enabled=env[1].ai_grounding=True;env[1].ai_api_key='synthetic-no-network'
    c=account(env);chat=conversation(c);writer(monkeypatch)
    model=Script([complete(),complete()]);env[0].state.agent_service.provider_factory=lambda *_:model
    options={}
    if case=='confirmation':chat=send(c,chat,'是否要继续处理这个安排？')[-1]['data']['conversation']
    else:
        from test_workspace import material
        chat=material(c,chat,'新增的合成材料需要核对。');options['source_ids']=[chat['sources'][0]['id']]
    message=final(send(c,chat,'谢谢',**options))
    assert message['status']=='complete' and message['grounding'].get('planning_mode')!='host_acknowledgement'
    assert len(model.inputs)==(2 if case=='confirmation' else 1)
