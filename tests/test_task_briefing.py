from datetime import datetime
import asyncio
import json
import re

import pytest

from app.agent_runtime.briefing import CST,prepare_briefing,requested_attention_count
from app.agent_runtime.workspace import evidence_sections
from app.agent_runtime.authoring import compile_answer
from app.genui_ai import evidence_index
from app.grounding import source
from app.db import ident
from test_workflow import env,account,notice,manual,confirm,task
from test_workspace import conversation
from test_agent_runtime import Script,answer,call
from test_agent_chat import enabled,writer,send,final


def snapshot(records,*,more=False,total=None):
    counts={key:sum(record['status']==key for record in records)for key in ('pending','done','cancelled')}
    result={'records':records,'offset':0,'has_more':more,'total':len(records)if total is None else total,
            'query_scope':{'kind':'tasks','query':'','target_id':''},'query_task_status_counts':counts}
    original=source('workspace-test','本人当前待办',evidence_sections(result),'execution')
    return {**result,'evidence_index':evidence_index([original])},original


def record(name,**changes):
    value={'kind':'tasks','id':name,'version':1,'status':'pending','updated_at':1,
           'data':{'title':name,'due_date':'2027-11-06','due_time':'17:00','deadline_confirmed':True},
           'workflow':{'blocked':False,'dependencies':[],'data':{'stage':'preparing','followup_at':None}},
           'handling_state':{'kind':'materials','label':'先准备材料'},'pending_changes':[]}
    value.update(changes);return value


def test_briefing_distinguishes_saved_status_deadline_followup_and_priority():
    changed=record('changed',handling_state={'kind':'changes','label':'核对变动影响'},
                   workflow={'blocked':False,'dependencies':[{'id':'done','status':'done'}],
                             'data':{'stage':'submitted','followup_at':'2027-11-05T12:00:00+08:00'}})
    done=record('done',status='done')
    value,original=snapshot([changed,done,record('materials')])
    draft=prepare_briefing(value,2,datetime(2027,11,3,tzinfo=CST))
    rendered=compile_answer(json.dumps(draft,ensure_ascii=False),[original],value['evidence_index'])
    assert '待完成 2 条' in rendered['answer'] and '本人已标记完成 1 条' in rendered['answer']
    assert rendered['answer'].index('changed')<rendered['answer'].index('materials')
    assert '2027-11-05 12:00，不是截止时间' in rendered['answer']
    assert '记录中确认的期限：2027-11-06 17:00' in rendered['answer']
    assert '本站前置记录当前未形成阻碍' in rendered['answer']


def test_attention_promotes_owned_pending_prerequisite_without_recommending_the_blocked_task():
    prerequisite=record('prerequisite',data={'title':'prerequisite','deadline_confirmed':False})
    blocked=record('blocked',workflow={'blocked':True,'dependencies':[{'id':'prerequisite','status':'pending'}],'data':{'stage':'preparing'}},
                   handling_state={'kind':'prerequisites','label':'处理这一步的前提'})
    value,_=snapshot([blocked,prerequisite])
    draft=prepare_briefing(value,1,datetime(2027,11,3,tzinfo=CST))
    assert '**prerequisite**' in draft['answer'] and '**blocked**' not in draft['answer']


def test_partial_detail_page_never_claims_complete_priority_ranking_but_exact_counts_still_work():
    value,_=snapshot([record('first')],more=True,total=100)
    value['query_task_status_counts']['pending']=100
    assert prepare_briefing(value,2,datetime(2027,11,3,tzinfo=CST))is None
    assert '待完成 100 条' in prepare_briefing(value,0,datetime(2027,11,3,tzinfo=CST))['answer']


def test_title_reference_syntax_cannot_inject_a_citation():
    value,original=snapshot([record('literal',data={'title':'literal [E999] *quoted*','deadline_confirmed':False})])
    draft=prepare_briefing(value,1,datetime(2027,11,3,tzinfo=CST))
    result=compile_answer(json.dumps(draft),[original],value['evidence_index'])
    assert 'E999' in result['answer'] and '[E999]' not in result['answer']


def test_real_chat_briefing_uses_one_author_call_and_still_independently_reviews(env,monkeypatch):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n,task(n,title='准备申请材料'))
    chat=conversation(c);writer(monkeypatch)
    before=c.get('/api/tasks').json()
    def choose(messages,tools):
        schema=next(tool['function']['parameters']for tool in tools if tool['function']['name']=='workspace_read')
        assert 'reply'in schema['required']
        assert 'default'not in schema['properties']['reply']
        assert not any(tool['function']['name']=='workspace_briefing'for tool in tools)
        return answer('',[call('workspace_read',{'kind':'tasks','reply':'task_briefing','count':2})])
    model=Script([choose])
    env[0].state.agent_service.provider_factory=lambda *_:model
    reply=final(send(c,chat,'只读取当前待办，用文字说明先关注什么，不修改数据，不生成界面。'))
    assert reply['status']=='complete',reply['error']
    assert len(model.inputs)==1 and reply['grounding']['status']=='checked'
    assert reply['grounding']['agent_execution']['workspace_reply']=='task_briefing'
    assert '准备申请材料' in reply['content'] and '已保存待办' in reply['content']
    assert c.get('/api/tasks').json()==before


def test_review_rejection_cannot_publish_a_prepared_briefing(env,monkeypatch):
    c=account(env);chat=conversation(c);writer(monkeypatch,reject=True)
    model=Script([answer('',[call('workspace_read',{'kind':'tasks','reply':'task_briefing','count':0})])for _ in range(3)])
    env[0].state.agent_service.provider_factory=lambda *_:model
    reply=final(send(c,chat,'只用文字告诉我保存了多少待办，不修改。'))
    assert reply['status']=='failed' and not reply['genui']['validated']
    assert reply['grounding']['status']=='not_published'


def test_equally_ranked_tasks_are_disclosed_as_alternatives_instead_of_a_fictional_order():
    value,original=snapshot([record('A'),record('B'),record('C')])
    draft=prepare_briefing(value,2,datetime(2027,11,3,tzinfo=CST))
    rendered=compile_answer(json.dumps(draft),[original],value['evidence_index'])
    assert '「C」'in rendered['answer'] and '不足以判定谁更优先'in rendered['answer']
    assert len(draft['claims'][-1]['evidence_refs'])==2


def test_completed_task_with_new_change_is_visible_without_reopening_it_or_inventing_a_deadline_change():
    changed=record('completed-with-change',status='done',pending_changes=[{'field':'due_date'}],
                   handling_state={'kind':'closed','label':'已完成个人办理'})
    value,original=snapshot([changed,record('ordinary')])
    draft=prepare_briefing(value,1,datetime(2027,11,3,tzinfo=CST))
    compiled=compile_answer(json.dumps(draft),[original],value['evidence_index'])
    assert '本人已标记完成 1 条'in compiled['answer']
    assert '**completed-with-change**：本人已标记完成，仍有变动待核实'in compiled['answer']
    assert '记录中确认过的期限：2027-11-06 17:00'in compiled['answer']
    assert '不把它视为最新办理依据'not in compiled['answer']
    assert changed['status']=='done'


def test_imminent_confirmed_deadline_precedes_changes_and_old_overdue_records():
    urgent=record('urgent',data={'title':'urgent','due_date':'2027-11-03','due_time':'12:00','deadline_confirmed':True})
    old=record('old',data={'title':'old','due_date':'2027-09-01','deadline_confirmed':True})
    changed=record('changed',pending_changes=[{'field':'materials'}],handling_state={'kind':'changes','label':'核对变动影响'})
    value,_=snapshot([old,changed,urgent])
    draft=prepare_briefing(value,1,datetime(2027,11,3,10,tzinfo=CST))
    assert '**urgent**'in draft['answer'] and '**old**'not in draft['answer'] and '**changed**'not in draft['answer']


def test_prepared_briefing_cannot_mix_with_other_calls_or_be_submitted_by_a_child():
    from app.agent_runtime.chat import ChatRun
    from app.agent_runtime.types import AgentError
    run=object.__new__(ChatRun)
    calls=[call('workspace_read',{'kind':'tasks','reply':'task_briefing'}),call('workspace_capabilities')]
    with pytest.raises(AgentError,match='未执行这批工具'):
        run.validate_calls(calls)
    # The result is completion metadata, not another page of records.
    assert run.bound_tool_result('workspace_read',{'status':'prepared_for_review'},4096)=={'status':'prepared_for_review'}
    from app.agent_runtime.workspace import WorkspaceRead
    args=WorkspaceRead(kind='tasks',reply='task_briefing')
    run.access={'schedule':True}
    with pytest.raises(AgentError,match='子任务不能'):
        asyncio.run(run.execute_tool('workspace_read',args,child=True))
    run.access={'schedule':False}
    with pytest.raises(AgentError,match='不允许访问'):
        asyncio.run(run.execute_tool('workspace_read',args))


def test_other_accounts_never_leak_through_briefing(env,monkeypatch):
    c=account(env);other=account(env,'other');n=manual(other,notice(other))
    confirm(other,n,task(n,title='FOREIGN-SECRET-777'))
    chat=conversation(c);writer(monkeypatch)
    model=Script([answer('',[call('workspace_read',{'kind':'tasks','reply':'task_briefing','count':0})])])
    env[0].state.agent_service.provider_factory=lambda *_:model
    reply=final(send(c,chat,'只统计本人已保存待办，不修改。'))
    assert reply['status']=='complete' and '0 条'in reply['content']
    assert 'FOREIGN-SECRET-777'not in json.dumps(reply,ensure_ascii=False)


@pytest.mark.parametrize('text,expected',[
    ('最先应处理哪两件事，依据是什么',2),('请先关注3项待办',3),('请推荐前二十项',20),
    ('Give me the top 2 tasks',2),('我有两件事，先核对附件',None),
    ('先看两项，再推荐三项',None),('请按学院分别推荐前三项',None),
    ('不是两项，而是三项',None),('不要只看前两项，请分析全部',None),
    ('我上次要求列出两项，这次请看全部',None),
    ('旧要求是“请列出两项”，本次只统计数量',None),
    ('哪两件事先不用选，只告诉我数量',None),
])
def test_explicit_shortlist_count_is_bound_only_when_unambiguous(text,expected):
    assert requested_attention_count(text)==expected


def test_model_cannot_expand_the_explicit_two_item_request_to_six(env,monkeypatch):
    c=account(env)
    for name in ('first','second','third'):
        n=manual(c,notice(c));confirm(c,n,task(n,title=name))
    chat=conversation(c);writer(monkeypatch)
    def choose(messages,tools):
        schema=next(tool['function']['parameters']for tool in tools if tool['function']['name']=='workspace_read')
        assert schema['properties']['count']['const']==2
        return answer('',[call('workspace_read',{'kind':'tasks','reply':'task_briefing','count':6})])
    model=Script([choose]);env[0].state.agent_service.provider_factory=lambda *_:model
    reply=final(send(c,chat,'只看已保存记录，最先应处理哪两件事？用文字，不修改。'))
    assert reply['status']=='complete',reply['error']
    assert len(re.findall(r'(?m)^\d+\. ',reply['content']))==2
    assert {'field':'workspace_read.count','model_value':6,'effective_value':2,'reason':'latest_explicit_shortlist_count'}in reply['grounding']['agent_execution']['answer_normalizations']
