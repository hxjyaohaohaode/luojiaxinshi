import asyncio
import json

from app import decision_routing as routing
from app.agent_runtime.continuity import explicit_topics
from app.memory_learning import classify, direct_quote
from app.memory_lifecycle import admit


def test_routing_projection_is_closed_and_negative_side_effects_do_not_select_workspace():
    prompt='请核实材料，申请人张明，学号123456，https://private.invalid/abc。不要写入待办或日历。\n附件原文：申请人叫小蓝。'
    state=routing.routing_state(prompt,{'web':False,'attachments':True,'history':'PRIVATE'})
    payload=json.dumps(state,ensure_ascii=False)
    assert all(value not in payload for value in ('张明','123456','private','history','小蓝','待办','日历'))
    assert state['capabilities']['attachments'] and not state['capabilities']['web']
    assert routing.local_route(prompt,False)=='research'
    assert routing.local_route('明天帮我创建日程',False)=='workspace'
    assert not routing.safe_direct('今年学校奖学金是什么？',has_context=False,has_materials=False)


def test_offline_route_uncertain_choice_and_positive_independent_question():
    result=asyncio.run(routing.decide('unused','解释什么是中位数',{},direct=True,allow_external=False))
    assert result['workflow']=='direct' and result['via']=='local'
    probs=dict.fromkeys(routing.WORKFLOWS,0);probs.update(direct=.53,research=.47)
    assert routing.choice({'workflow':{'type':'choice','choice':'direct','probabilities':probs}}) is None


def test_checklist_and_explicit_preference_do_not_learn_quoted_examples():
    assert explicit_topics('帮我查：\n1. 我的申请资格是什么？\n2. 截止日期是什么？')==['我的申请资格是什么？','截止日期是什么？']
    assert len(explicit_topics('\n'.join(f'{index}. 核对第{index}个要求' for index in range(1,26))))==25
    text='今后请用英文回答。'
    assert direct_quote(text,text) and classify(text)=='preference' and admit(text,'preference')=='long_term'
    assert not direct_quote('我的专业是化学。','示例：我的专业是化学。')
    assert not direct_quote('我的专业是化学。','通知原文：\n请看下文。\n我的专业是化学。'.replace(chr(10),chr(10)))
