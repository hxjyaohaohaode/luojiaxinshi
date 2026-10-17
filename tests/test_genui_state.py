"""Interactions preserve editable intent and immutable evidence across turns."""
import asyncio
from copy import deepcopy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import genui_ai,grounding
from app.genui import parse_message
from app.genui_state import validate_snapshots, context_text
from test_workflow import env,account
from test_workspace import conversation
from test_genui_transport import events,payload


OPS=[{'op':'begin','v':1},
     {'op':'state','set':{'audience':None,'draft':'','hours':2,'source':{'deadline':'2026-10-20'},'practice':{'index':0,'answer':None}}},
     {'op':'node','id':'audience','type':'Choice','props':{'label':'阅读身份','bind':'audience','options':[{'value':'resident','label':'住校'},{'value':'commuter','label':'走读'}]}},
     {'op':'node','id':'draft','type':'TextInput','props':{'label':'你的草稿','bind':'draft','maxLength':500}},
     {'op':'node','id':'time','type':'Slider','props':{'label':'准备时长','bind':'hours','min':0,'max':8,'step':.5}},
     {'op':'node','id':'answer','type':'Choice','props':{'label':'判断','bind':'practice.answer','options':[{'value':'a','label':'甲'},{'value':'b','label':'乙'}]}},
     {'op':'node','id':'next','type':'Button','props':{'label':'下一情境'},'on':{'click':{'kind':'state','key':'practice','value':{'index':1,'answer':None}}}},
     {'op':'node','id':'form','type':'Form','props':{'label':'补充信息','fields':[{'name':'question','label':'追问','type':'text'},{'name':'level','label':'阅读深度','type':'select','options':[{'value':'short','label':'简短'},{'value':'long','label':'深入'}]}]}},
     {'op':'end'}]
RAW='```genui\n'+'\n'.join(json.dumps(op,ensure_ascii=False) for op in OPS)+'\n```'


def parts():return parse_message(RAW)
def snap():return {'0':{'state':deepcopy(parts()[0]['spec']['state']),'view':{}}}


def test_nullable_choice_and_nested_reset_save_without_changing_source_records():
    value=snap();value['0']['state'].update(audience='commuter',hours=3.5,practice={'index':1,'answer':'b'})
    assert validate_snapshots(value,parts())==value
    for path,value_at_path in [('source',{'deadline':'2026-10-21'}),('practice',{'index':99,'answer':'b'}),('hours',3.1),('audience','invented')]:
        value=snap();value['0']['state'][path]=value_at_path
        with pytest.raises(ValueError):validate_snapshots(value,parts())


def test_missing_bindings_report_all_control_ids_and_paths_for_one_repair():
    ops=deepcopy(OPS);del ops[1]['set']['audience'];del ops[1]['set']['draft']
    p=parse_message('```genui\n'+'\n'.join(json.dumps(op) for op in ops)+'\n```')
    value={'0':{'state':deepcopy(p[0]['spec']['state']),'view':{}}}
    with pytest.raises(ValueError) as error:validate_snapshots(value,p)
    text=str(error.value)
    assert '"node":"audience"' in text and '"path":"audience"' in text
    assert '"node":"draft"' in text and '"path":"draft"' in text


@pytest.mark.parametrize('view',[{'form':{'fields':{'unknown':'x'}}},{'form':{'fields':{'level':'99'}}},{'form':{'fields':{'question':False}}},{'missing':{}}])
def test_form_state_and_unknown_nodes_cannot_bypass_snapshot_contract(view):
    value=snap();value['0']['view']=view
    with pytest.raises(ValueError):validate_snapshots(value,parts())


def test_local_checklist_view_only_accepts_its_declared_items():
    ops=[{'op':'begin','v':1},{'op':'node','id':'checks','type':'Checklist','props':{'label':'自查','items':[{'id':'a','label':'核对原文'}]}},{'op':'end'}]
    p=parse_message('```genui\n'+'\n'.join(json.dumps(op) for op in ops)+'\n```')
    value={'0':{'state':{},'view':{'checks':{'checked':['a']}}}}
    validate_snapshots(value,p)
    value['0']['view']['checks']['checked']=['other-record']
    with pytest.raises(ValueError):validate_snapshots(value,p)


def test_collection_descendant_view_has_stable_restorable_identity():
    ops=[{'op':'begin','v':1},{'op':'node','id':'list','type':'Collection','props':{'items':[{'id':'a'}],'keyField':'id'},'children':['section']},
         {'op':'node','id':'section','type':'Section','children':['tabs']},{'op':'node','id':'tabs','type':'Tabs','props':{'labels':['甲','乙']},'children':['a','b']},
         {'op':'node','id':'a','type':'Markdown','props':{'text':'甲'}},{'op':'node','id':'b','type':'Markdown','props':{'text':'乙'}},{'op':'end'}]
    p=parse_message('```genui\n'+'\n'.join(json.dumps(op) for op in ops)+'\n```')
    value={'0':{'state':{},'view':{'list:string%3Aa:tabs':{'selected':1}}}}
    validate_snapshots(value,p)
    value['0']['view']['list:string%3Aa:tabs']['selected']=9
    with pytest.raises(ValueError):validate_snapshots(value,p)


def test_collection_item_inputs_only_change_the_declared_field_of_the_correct_record():
    ops=[{'op':'begin','v':1},{'op':'state','set':{'rows':[{'id':'a','source':'原文甲','note':''},{'id':'b','source':'原文乙','note':''}]}},
         {'op':'node','id':'rows','type':'Collection','props':{'bind':'rows','items':{'$bind':'rows'},'keyField':'id'},'children':['note']},
         {'op':'node','id':'note','type':'TextInput','props':{'label':'我的批注','bind':'item.note'}},{'op':'end'}]
    p=parse_message('```genui\n'+'\n'.join(json.dumps(op) for op in ops)+'\n```')
    assert not p[0]['spec']['errors']
    value={'0':{'state':deepcopy(p[0]['spec']['state']),'view':{}}};value['0']['state']['rows'][1]['note']='只修改乙的批注'
    validate_snapshots(value,p)
    value['0']['state']['rows'][1]['source']='改写原文'
    with pytest.raises(ValueError,match='readonly'):validate_snapshots(value,p)


def test_publication_checks_reject_missing_bindings_before_a_broken_widget_reaches_the_user():
    result={'answer':RAW,'citations':[],'image_sources':[],'claims':[]}
    grounding.check_result(result,[])
    changed=deepcopy(OPS);changed[2]['props']['bind']='missing'
    result['answer']='```genui\n'+'\n'.join(json.dumps(op) for op in changed)+'\n```'
    with pytest.raises(ValueError,match='状态绑定'):grounding.check_result(result,[])


def test_ui_submission_flows_through_history_model_context_reload_and_branch(env,monkeypatch):
    captured=[]
    async def model(settings,sources,messages,profile,tier):
        captured.append(messages)
        raw=RAW if len(captured)==1 else '按你选择的走读视角继续。'
        yield {'type':'delta','text':raw}
        yield {'type':'complete','result':{'answer':raw,'citations':[],'image_sources':[]}}
    monkeypatch.setattr(genui_ai,'stream_reply',model)
    c=account(env);chat=conversation(c)
    first=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation']
    origin=first['messages'][-1]['id']
    context={'v':1,'message_id':origin,'snapshot_version':0,'blocks':{'0':{'inputs':{'audience':'commuter','draft':'只写已确认的部分','practice':{'index':1,'answer':'b'},'practice.answer':'b'},'view':{'form':{'fields':{'question':'哪个条件没有证据？','level':'1'}}}}}}
    body=payload(first,content='按当前选择继续，不联网。',ui_context=context)
    result=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=body))[-1]['data']['conversation']
    user=result['messages'][-2];assert user['content']=='按当前选择继续，不联网。'
    interaction=user['interaction'];assert interaction['message_id']==origin
    assert interaction['checkpoint']=={'status':'saved','version':1}
    assert any(s['value']=='commuter' and s['changed'] for s in interaction['selections'])
    assert any(s['value']=='long' for s in interaction['selections'])
    contextual=context_text(captured[-1][-1]);assert 'commuter' in contextual and '不是官方证据' in contextual
    assert 'commuter' in grounding.question_context(captured[-1]) and grounding.web_restricted(captured[-1])
    provider=genui_ai.payload(env[1],[],captured[-1],{},1)
    assert '只写已确认的部分' in provider['messages'][-1]['content']
    reloaded=c.get('/api/conversations/'+chat['id']).json();assert reloaded['messages'][-2]['interaction']==interaction
    saved_origin=reloaded['messages'][1]['genui'];assert saved_origin['snapshot_version']==1 and saved_origin['snapshots']['0']['state']['draft']=='只写已确认的部分'
    replay=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=body));assert replay[0]['data']['replayed']
    assert c.get('/api/conversations/'+chat['id']).json()['messages'][1]['genui']['snapshot_version']==1
    branch=c.post(f"/api/conversations/{chat['id']}/messages/{result['messages'][-1]['id']}/branch",json={'version':result['version']})
    assert branch.status_code==200,branch.text
    copied=branch.json();copied_user=copied['messages'][-2]
    assert copied_user['interaction']['message_id']==copied['messages'][1]['id']!=origin
    assert copied_user['interaction']['selections']==interaction['selections']
    other=account(env,'other');other_chat=conversation(other)
    invalid=payload(other_chat,content='继续',ui_context=context)
    denied=other.post(f"/api/conversations/{other_chat['id']}/messages/stream",json=invalid)
    assert denied.status_code==422 and len(captured)==2
    assert not other.get('/api/conversations/'+other_chat['id']).json()['messages']
    invalid=payload(reloaded,content='继续',ui_context={**context,'blocks':{'0':{'inputs':{'source.deadline':'invented'},'view':{}}}})
    assert c.post(f"/api/conversations/{chat['id']}/messages/stream",json=invalid).status_code==422


def test_submitted_selections_do_not_overwrite_a_newer_snapshot_from_another_tab(env,monkeypatch):
    async def model(*args):
        yield {'type':'delta','text':RAW};yield {'type':'complete','result':{'answer':RAW,'citations':[],'image_sources':[]}}
    monkeypatch.setattr(genui_ai,'stream_reply',model)
    c=account(env);chat=conversation(c)
    first=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation'];origin=first['messages'][-1]['id']
    newer=snap();newer['0']['state']['draft']='另一个页面保存的草稿'
    assert c.put(f"/api/conversations/{chat['id']}/messages/{origin}/ui-state",json={'version':0,'snapshots':newer}).status_code==200
    context={'v':1,'message_id':origin,'snapshot_version':0,'blocks':{'0':{'inputs':{'draft':'这一页刚刚提交的草稿'},'view':{}}}}
    final=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(first,content='按这次提交的草稿分析',ui_context=context)))[-1]['data']['conversation']
    assert final['messages'][-2]['interaction']['checkpoint']['status']=='conflict'
    assert final['messages'][-2]['interaction']['selections'][0]['value']=='这一页刚刚提交的草稿'
    assert final['messages'][1]['genui']['snapshots']['0']['state']['draft']=='另一个页面保存的草稿'


def test_invalid_interaction_does_not_cancel_an_in_progress_reply(env,monkeypatch):
    calls=[];started=threading.Event()
    async def model(*args):
        calls.append(1)
        if len(calls)==1:
            yield {'type':'delta','text':RAW};yield {'type':'complete','result':{'answer':RAW,'citations':[],'image_sources':[]}}
        else:
            started.set();await asyncio.sleep(20)
    monkeypatch.setattr(genui_ai,'stream_reply',model)
    c=account(env);chat=conversation(c)
    first=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))[-1]['data']['conversation']
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(c.post,f"/api/conversations/{chat['id']}/messages/stream",json=payload(first,content='继续思考'))
        assert started.wait(5);live=c.get('/api/conversations/'+chat['id']).json()
        invalid={'v':1,'message_id':first['messages'][-1]['id'],'blocks':{'0':{'inputs':{'source.deadline':'改写原文'},'view':{}}}}
        denied=c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(live,content='补充',steer_message_id=live['messages'][-1]['id'],ui_context=invalid))
        assert denied.status_code==422 and c.get('/api/conversations/'+chat['id']).json()['processing']
        assert c.post('/api/conversations/'+chat['id']+'/cancel',json={'version':live['version']}).status_code==200
        pending.result(timeout=5)
    assert len(calls)==2
