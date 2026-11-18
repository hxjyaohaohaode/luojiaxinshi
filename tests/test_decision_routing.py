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

def test_two_decisions_share_one_private_projection_and_fail_independently(monkeypatch):
    import httpx
    def answer(name, options):
        return {'type':'choice','choice':name,'probabilities':{option:int(option==name) for option in options}}
    answers={'workflow':answer('workspace',routing.WORKFLOWS),'approach':answer('time_plan',routing.APPROACHES)}
    requests=[]
    async def post(self,url,**kwargs):
        requests.append(kwargs['json'])
        return httpx.Response(200,request=httpx.Request('POST',url),json={'answers':answers})
    monkeypatch.setattr(httpx.AsyncClient,'post',post)
    monkeypatch.setattr(routing,'COOLDOWN_UNTIL',0)
    result=asyncio.run(routing.decide('dummy','请检查日程冲突。通知全文：我的姓名是张明',{'schedule':True},direct=False,allow_external=True))
    assert result['workflow']=='workspace' and result['approach']=='time_plan' and result['approach_via']=='openrouter'
    assert len(requests)==1 and set(requests[0]['questions'])=={'workflow','approach'} and '张明' not in json.dumps(requests,ensure_ascii=False)
    del answers['workflow']
    partial=asyncio.run(routing.decide('dummy','请核对课表',{'schedule':True},direct=False,allow_external=True))
    assert partial['via']=='local_uncertain' and partial['approach_via']=='openrouter'
    denied=asyncio.run(routing.decide('dummy','请核对课表',{'schedule':False},direct=False,allow_external=False))
    assert len(requests)==2 and denied['approach_via']=='local'


def test_volunteered_preferences_use_the_owned_memory_route_only_for_actual_self_reports():
    stated='我长期用中文写报告，所有项目都习惯先看结论再看依据。请用纯文字简短回复，不联网。'
    assert routing.local_route(stated,False)=='memory'
    assert routing.volunteered_preference(stated)
    for value in ('同学说我习惯先看结论。','示例：\n我习惯先看结论。','我习惯先看结论，但仅本次。',
                  '我习惯先看结论。不要记住。','“我习惯先看结论”。','我习惯先看结论吗？'):
        assert not routing.volunteered_preference(value)
    assert routing.local_route('我习惯先看结论。请查我的日历。',False)=='workspace'
