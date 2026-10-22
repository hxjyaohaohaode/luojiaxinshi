"""Evidence boundaries use synthetic records and mocked providers, never paid APIs."""
import asyncio
import json
import time
import uuid

import pytest

from app import grounding, genui_ai, work_summary
from app.ai import AIError
from app.db import dumps, ident
from app.evidence_web import public_url, public_query, PageText
from test_workflow import env, account, notice
from test_workspace import conversation, material
from test_genui_transport import events, payload


def evidence():
    return [grounding.source('document', '报名通知', [{'locator':'第1段','text':'报名于2026年10月20日18:00截止。'}], 'notice')]


def answer():
    return {'answer':'报名于2026年10月20日18:00截止。[1]', 'citations':[{'source_id':'document','locator':'第1段','quote':'报名于2026年10月20日18:00截止。'}],
            'image_sources':[], 'claims':[{'kind':'fact','text':'报名于2026年10月20日18:00截止。','citation_indices':[1]}]}


def test_quotes_unregistered_urls_and_uncited_facts_fail_closed():
    grounding.check_result(answer(), evidence())
    for change in ('wrong_quote','wrong_source','empty_quote','invented_url','uncited','missing_number','broken_ui'):
        value=answer()
        if change=='wrong_quote':value['citations'][0]['quote']='22:00截止'
        if change=='wrong_source':value['citations'][0]['source_id']='other-owner'
        if change=='empty_quote':value['citations'][0]['quote']=' '
        if change=='invented_url':value['answer']+=' https://example.com/invented'
        if change=='uncited':value['claims'][0]['citation_indices']=[]
        if change=='missing_number':value['answer']+=' [2]'
        if change=='broken_ui':value['answer']+='\n```genui\n{"op":"begin","v":1}\n'
        with pytest.raises(ValueError):grounding.check_result(value,evidence())


def test_local_boolean_cannot_masquerade_as_persistent_save():
    value=answer();value['answer']+='\n```genui\n'+ '\n'.join(dumps(op) for op in [
        {'op':'begin','v':1},{'op':'state','set':{'saved':False}},
        {'op':'node','id':'save','type':'Button','props':{'label':'保存本回答进度'},'on':{'click':{'kind':'state','key':'saved','value':True}}},{'op':'end'}])+'\n```'
    with pytest.raises(ValueError,match='unsupported_persistent_save'):
        grounding.check_result(value,evidence())


def test_registered_evidence_references_restore_exact_quotes_without_model_transcription():
    sources=evidence();entries=genui_ai.evidence_index(sources)
    value=answer();value['citations']=[];value['citation_refs']=['E1']
    resolved=genui_ai.resolve_citations(value,entries)
    assert resolved['citations'][0]['quote']==sources[0]['sections'][0]['text']
    grounding.check_result(resolved,sources)
    with pytest.raises(ValueError,match='E999'):genui_ai.resolve_citations({'citations':[],'citation_refs':['E999']},entries)
    repeated=genui_ai.resolve_citations({'citations':[],'citation_refs':['E1','E1']},entries)
    assert len(repeated['citations'])==2 and repeated['citations'][0]==repeated['citations'][1]
    duplicated=answer();duplicated['citations']=repeated['citations'];duplicated['answer']+=' [2]';duplicated['claims'][0]['citation_indices']=[1,2]
    grounding.check_result(duplicated,sources)
    assert genui_ai.resolve_citations({'citations':answer()['citations'],'citation_refs':['E1']},entries)['citations']==answer()['citations']
    conflict=answer()['citations'];conflict[0]['quote']='虚构原句'
    with pytest.raises(ValueError):genui_ai.resolve_citations({'citations':conflict,'citation_refs':['E1']},entries)


def test_link_repair_identifies_exact_page_and_rejects_user_url_as_page_evidence():
    url='https://library.example.edu.cn/renewal.html'
    sources=[grounding.source('user-input','用户要求',[{'locator':'要求','text':'请读取 '+url}],'user_input'),
        {**grounding.source('official-page','续借规则原文',[{'locator':'网页段落1','text':'续借期从续借当日起计算。'}],'web_page'),'url':url}]
    value={'answer':'[打开原文]('+url+')[1]','citations':[{'source_id':'user-input','locator':'要求','quote':'请读取 '+url}],'claims':[]}
    with pytest.raises(ValueError) as failure:grounding.check_result(value,sources)
    detail=json.loads(str(failure.value).partition('依据：')[2])
    assert detail['url']==url and detail['cited_source_ids']==['user-input']
    assert detail['expected_web_sources']==[{'source_id':'official-page','name':'续借规则原文'}]
    value['citations']=[{'source_id':'official-page','locator':'网页段落1','quote':'续借期从续借当日起计算。'}]
    grounding.check_result(value,sources)


def test_stable_references_keep_text_ui_claims_and_original_quotes_aligned_after_reordering():
    entries=[{'ref':'E1','source_id':'a','locator':'原段1','quote':'规则甲的原文含字面标记[E99]。'},
        {'ref':'E2','source_id':'b','locator':'原段2','quote':'规则乙原文。'}]
    def draft():return {'answer':'规则甲。[E1]','ui':{'state':{'detail':'规则乙。[E2]'},'nodes':[{'id':'body','type':'Prose','props':{'text':'规则乙。[E2]'}}]},
        'citations':[],'citation_refs':[],'claims':[{'kind':'fact','text':'规则乙。','evidence_refs':['E2'],'citation_indices':[]}]}
    value=genui_ai.resolve_citations(draft(),entries)
    assert value['answer']=='规则甲。[1]' and value['ui']['state']['detail']=='规则乙。[2]'
    assert value['ui']['nodes'][0]['props']['text']=='规则乙。[2]' and value['claims'][0]['citation_indices']==[2]
    assert value['citations'][0]['quote']==entries[0]['quote'] and 'evidence_refs' not in value['claims'][0]
    revised=draft();revised['answer']='先看规则乙。[E2] 再看规则甲。[E1]'
    value=genui_ai.resolve_citations(revised,entries)
    assert [c['source_id'] for c in value['citations']]==['b','a']
    assert value['ui']['state']['detail']=='规则乙。[1]' and value['claims'][0]['citation_indices']==[1]
    invalid=draft();invalid['ui']['state']['detail']='不存在的依据[E999]'
    with pytest.raises(ValueError,match='E999'):genui_ai.resolve_citations(invalid,entries)
    mixed=draft();mixed['claims'][0]['citation_indices']=[2]
    with pytest.raises(ValueError,match='mixed_citation_protocols'):genui_ai.resolve_citations(mixed,entries)


def test_post_compile_repair_retains_native_ui_object_and_reference_mapping(env,monkeypatch):
    import httpx
    real_stream=genui_ai.stream_reply
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only'
    monkeypatch.setattr(genui_ai,'stream_reply',real_stream)
    async def verify(settings,result,sources,question,context):return [],{},grounding.check_result(result,sources)
    monkeypatch.setattr(grounding,'verify',verify)
    base={**answer(),'citations':[],'citation_refs':['E1'],'ui':{'state':{'question':''},'nodes':[
        {'id':'body','type':'Section','props':{'title':'原文核对'},'children':['question']},
        {'id':'question','type':'TextInput','props':{'label':'疑问','bind':'question'}}]}}
    seen=[];client=httpx.AsyncClient
    def transport(request):
        seen.append(json.loads(request.content));value=json.loads(json.dumps(base))
        if len(seen)==1:value['ui']['nodes'][0]['props']['children']=['question']
        raw=json.dumps(value,ensure_ascii=False)
        body='data: '+json.dumps({'choices':[{'delta':{'content':raw},'finish_reason':'stop'}]})+'\n\n'
        return httpx.Response(200,content=body)
    monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kwargs:client(transport=httpx.MockTransport(transport),**kwargs))
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='complete' and len(seen)==2
    previous=next(m['content'] for m in seen[1]['messages'] if m['role']=='assistant' and '从未向用户发布' in m['content'])
    native=json.loads(previous.split('\n',1)[1])
    assert native['citation_refs']==['E1'] and native['citations']==[]
    assert native['ui']['nodes'][0]['props']['children']==['question'] and '```genui' not in native['answer']
    assert '"display_number_to_ref":[{"number":1,"ref":"E1"}]' in seen[1]['messages'][-1]['content']
    assert 'repair_draft' not in json.dumps(packets) and message['genui']['validated']


def test_composition_model_never_replaces_pro_evidence_verification(env,monkeypatch):
    settings=env[1]
    request=genui_ai.payload(settings,evidence(),[{'role':'user','content':'整理交互界面'}],{'_grounding_context':{}},1)
    # An empty context does not claim that evidence preparation has run.
    assert request['model']=='mimo-v2.6-pro'
    request=genui_ai.payload(settings,evidence(),[{'role':'user','content':'整理交互界面'}],{'_grounding_context':{'status':'checking'}},1)
    assert request['model']=='mimo-v2.6-pro' and request['thinking']=={'type':'disabled'} and request['temperature']==0.2
    assert request['messages'][0]['content'].count('"enum":["E1"]')>=1
    seen=[]
    async def complete(settings,payload,**kwargs):
        seen.append(payload);return {'content':dumps({'supported':True,'issues':[]})},{}
    monkeypatch.setattr(grounding,'completion',complete)
    issues,_,_=asyncio.run(grounding.verify(settings,answer(),evidence(),'核对原文',{}))
    assert not issues and seen[0]['model']=='mimo-v2.6-pro'
    assert seen[0]['thinking']=={'type':'disabled'}
    assert seen[0]['max_completion_tokens']==min(settings.ai_output_tokens,2048) and seen[0]['temperature']==0.2
    assert json.loads(seen[0]['messages'][1]['content'])['program_checks']
    assert json.loads(seen[0]['messages'][1]['content'])['citation_display_map']==[{'display_number':1,**answer()['citations'][0]}]
    audited=json.loads(seen[0]['messages'][1]['content'])
    assert 'citations' not in audited['answer_to_audit']
    assert audited['answer_to_audit']['answer']==answer()['answer'] and audited['answer_to_audit']['claims']==answer()['claims']
    assert audited['evidence'][0]['sections']==evidence()[0]['sections']  # Full context and exact spans still reach Pro.
    settings.ai_composition_model='mimo-v2.6-flash'
    optional=genui_ai.payload(settings,evidence(),[{'role':'user','content':'整理交互界面'}],{'_grounding_context':{'status':'checking'}},1)
    assert optional['model']=='mimo-v2.6-flash' and optional['thinking']=={'type':'disabled'} and optional['temperature']==0.2


def test_repair_receives_the_rejected_ui_without_publishing_it(env,monkeypatch):
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only';attempts=[];seen=[]
    async def stream(settings,sources,messages,profile,tier):
        seen.append(messages)
        yield {'type':'complete','result':answer(),'usage':{}}
    async def verify(*args):
        attempts.append(True);return (['需要修正引用'] if len(attempts)==1 else []),{},[]
    monkeypatch.setattr(genui_ai,'stream_reply',stream);monkeypatch.setattr(grounding,'verify',verify)
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    assert len(seen)==2 and any(m['role']=='assistant' and '从未向用户发布' in m['content'] and answer()['answer'] in m['content'] for m in seen[1])
    assert ''.join(p['data']['text'] for p in packets if p['type']=='delta')==answer()['answer']


def test_format_repair_receives_provider_json_without_exposing_it(env,monkeypatch):
    from app.ai import ReplyValidationError
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only';seen=[]
    raw='{"answer":"UNPUBLISHED-DRAFT","citation_refs":["E999"]}'
    async def stream(settings,sources,messages,profile,tier):
        seen.append(messages)
        if len(seen)==1:raise ReplyValidationError('未登记的引用 E999',draft=raw)
        assert any(m['role']=='assistant' and raw in m['content'] for m in messages)
        yield {'type':'complete','result':answer(),'usage':{}}
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    assert len(seen)==2
    published=''.join(p['data']['text'] for p in packets if p['type']=='delta')
    assert published==answer()['answer'] and 'UNPUBLISHED-DRAFT' not in published


def test_independent_protocol_repairs_converge_without_retrieving_again(env,monkeypatch):
    from app.ai import ReplyValidationError
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only';calls=[];retrieved=[]
    async def stream(settings,sources,messages,profile,tier):
        calls.append(messages)
        if len(calls)<4:raise ReplyValidationError('具体协议错误 '+str(len(calls)),draft='{"answer":"UNPUBLISHED-'+str(len(calls))+'"}')
        yield {'type':'complete','result':answer(),'usage':{}}
    def retrieve(*args):retrieved.append(True);return evidence(),{'scanned':{},'selected_sources':1}
    monkeypatch.setattr(genui_ai,'stream_reply',stream);monkeypatch.setattr(grounding,'retrieve',retrieve)
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    result=packets[-1]['data']['conversation']['messages'][-1]
    assert len(calls)==4 and len(retrieved)==1 and result['status']=='complete'
    assert result['grounding']['attempts']==4 and len(result['grounding']['repair_history'])==3
    assert ''.join(p['data']['text'] for p in packets if p['type']=='delta')==answer()['answer']


def test_validation_error_keeps_bounded_answer_draft_out_of_error_text():
    raw='{"answer":"PRIVATE-DRAFT","citation_refs":["E999"]}'
    error=genui_ai.validation_failure('格式无效',raw)
    assert error.draft==raw and 'PRIVATE-DRAFT' not in str(error)
    assert genui_ai.validation_failure('过长','x'*131073).draft is None


def test_bad_action_feedback_includes_the_missing_action_schema():
    value=answer();value['answer']+='\n```genui\n'+ '\n'.join(dumps(op) for op in [
        {'op':'begin','v':1},{'op':'node','id':'src','type':'Button','props':{'label':'查看来源'},'on':{'click':{'kind':'host','action':'open_sources'}}},{'op':'end'}])+'\n```'
    with pytest.raises(ValueError) as error:grounding.check_result(value,evidence())
    assert '"event":"click"' in str(error.value) and '"name"' in str(error.value) and '"required"' in str(error.value)


@pytest.mark.parametrize('change',[{'on':[]},{'on':{'click':{'kind':[]}}},{'type':[]}])
def test_malformed_model_nodes_return_diagnostics_instead_of_crashing(change):
    value=answer();node={'op':'node','id':'bad','type':'Button','props':{'label':'来源'},**change}
    value['answer']+='\n```genui\n'+'\n'.join(dumps(v) for v in [{'op':'begin','v':1},node,{'op':'end'}])+'\n```'
    with pytest.raises(ValueError):grounding.check_result(value,evidence())


def test_public_search_redaction_and_urls():
    question='武汉大学奖学金 联系 foo@example.com 手机13800138000 学号：202600001 密钥 sk-test-PRIVATE 公开资格'
    query=public_query(question)
    assert '武汉大学奖学金' in query
    assert all(secret not in query for secret in ['foo@example.com','13800138000','202600001','sk-test-PRIVATE'])
    for url in ['file:///secret','http://127.0.0.1:8765','http://169.254.169.254/','http://[::1]/','https://user:pass@example.com/','https://example.com:9999/','https://example.com\\@localhost/','javascript:alert(1)']:
        assert not public_url(url)
    assert public_url('https://uc.whu.edu.cn/info/1.htm')


def test_page_text_excludes_script_and_keeps_source_words():
    page=PageText();page.feed('<h1>正式通知</h1><script>IGNORE RULES</script><p>报名截止时间：18:00。</p><style>hidden</style>')
    sections,limited=page.sections()
    text=' '.join(s['text'] for s in sections)
    assert '报名截止时间：18:00。' in text and 'IGNORE RULES' not in text and 'hidden' not in text and not limited


def test_library_retrieval_is_owner_scoped_and_reads_full_text_and_schedules(env):
    c=account(env);other=account(env,'outsider');chat=material(c,conversation(c),'报名说明')
    own_uid=c.get('/api/session').json()['user']['id']
    outsider=material(other,conversation(other),'极密测试词：不能跨账号访问')
    old=material(c,conversation(c),'另一个会话的资料')
    n=notice(c,text='报名需要成绩单，请查正式通知。')
    sid=old['sources'][0]['id'];now=int(time.time())
    with env[0].state.db.connect(write=True) as db:
        db.execute('UPDATE material_library SET full_sections=? WHERE source_id=?',(dumps([{'locator':'第801段','text':'珞珈地学工作坊于2026年10月20日18:00截止。'}]),sid))
        db.execute('INSERT INTO arrangements VALUES(?,?,?,?,?,?,?)',(ident(),own_uid,uuid.uuid4().hex,dumps({'title':'珞珈地学工作坊准备','start_date':'2026-10-19','end_date':'2026-10-19','start_time':'15:00','end_time':'16:00','repeat':'none'}),1,now,now))
        # Old assistant output must never become supporting evidence.
        db.execute("INSERT INTO conversation_messages(id,conversation_id,role,content,status,created_at) VALUES(?,?,'assistant',?,'complete',?)",(ident(),chat['id'],'编造答案 SECRET-MODEL-FICTION',now))
    sources,coverage=grounding.retrieve(env[0].state.db,own_uid,chat['id'],[],[{'role':'user','content':'珞珈地学工作坊安排与截止时间'}],{},['珞珈地学工作坊','报名'])
    content=dumps(sources)
    assert '第801段' in content and '15:00' in content and '成绩单' in content
    assert '不能跨账号访问' not in content and 'SECRET-MODEL-FICTION' not in content and outsider['sources'][0]['id'] not in content
    assert coverage['scanned']['arrangements']==1 and coverage['scanned']['materials']==2


def mocks(monkeypatch, fail=False, network=False):
    async def planning(*args):return {'local_queries':['报名'],'public_queries':['武汉大学报名'] if network else [],'web_reason':'只整理材料'},{}
    async def coverage(*args):return {'items':[{'requirement':'报名时间','status':'supported','source_ids':['document'],'gap':''}], 'personal_fit':'未提供额外个人条件','conflicts':[], 'followup_local':[], 'followup_public':[]},{}
    async def summary(*args):return '正在按实际检索结果整理当前阶段的工作摘要。',{}
    monkeypatch.setattr(grounding,'assess_coverage',coverage)
    assert not hasattr(work_summary,'summarize')
    monkeypatch.setattr(grounding,'plan',planning)
    monkeypatch.setattr(grounding,'retrieve',lambda *args:(evidence(),{'scanned':{},'selected_sources':1}))
    async def searching(*args):raise AIError('网络不可用')
    monkeypatch.setattr(grounding,'search',searching)
    async def stream(*args):
        result=answer()
        yield {'type':'delta','text':result['answer']}
        yield {'type':'complete','result':result,'usage':{'input_tokens':1,'output_tokens':2}}
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    async def review(settings,result,sources,question,context):
        assert 'citations' in result
        if network:assert context['web']['status']=='unavailable'
        return (['结论没有足够证据'] if fail else []),{},['测试核验']
    monkeypatch.setattr(grounding,'verify',review)


def test_strict_stream_buffers_draft_and_persists_grounding_across_reload_and_branch(env,monkeypatch):
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only'
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    types=[p['type'] for p in packets]
    verify_index=next(i for i,p in enumerate(packets) if p['type']=='phase' and p['data']['phase']=='verifying')
    assert types.index('delta')>verify_index
    final=packets[-1]['data']['conversation'];message=final['messages'][-1]
    assert message['status']=='complete' and message['grounding']['status']=='checked'
    assert [s['stage'] for s in message['grounding']['steps']]==['planning','retrieving','coverage','writing','verifying']
    assert all(s['state']=='complete' for s in message['grounding']['steps'])
    assert message['evidence_sources'][0]['id']=='document' and 'sections' not in message['evidence_sources'][0]
    assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]['grounding']==message['grounding']
    branch=c.post(f"/api/conversations/{chat['id']}/messages/{message['id']}/branch",json={'version':final['version']})
    assert branch.status_code==200,branch.text
    assert branch.json()['messages'][-1]['grounding']['status']=='checked'


def test_two_failed_reviews_never_deliver_or_store_draft(env,monkeypatch):
    mocks(monkeypatch,fail=True);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only'
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    assert not any(p['type']=='delta' for p in packets)
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='failed' and message['content']=='' and message['genui']['raw']==''
    assert message['grounding']['status']=='not_published' and '拦截' in message['error']
    assert len([item for item in message['grounding']['repair_history'] if item['kind']=='semantic'])==2


def test_web_failure_is_explicit_and_plain_endpoint_uses_same_review(env,monkeypatch):
    mocks(monkeypatch,network=True);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only'
    c=account(env);chat=conversation(c)
    response=c.post(f"/api/conversations/{chat['id']}/messages",json=payload(chat))
    assert response.status_code==200,response.text
    message=response.json()['messages'][-1]
    assert message['status']=='complete' and message['grounding']['web']['status']=='unavailable'


def test_strict_composition_uses_bounded_evidence_and_preserves_analysis_contract(env):
    request=genui_ai.payload(env[1],evidence(),[{'role':'user','content':'核对报名时间'}],{'_grounding_context':{'web':{'status':'unavailable'}}},1)
    assert request['model']=='mimo-v2.6-pro' and request['thinking']=={'type':'disabled'} and request['max_completion_tokens']>=16000
    assert 'claims' in request['messages'][0]['content'] and '智能 UI 与正文执行相同证据规则' in request['messages'][0]['content']
    assert 'unavailable' in request['messages'][1]['content'][0]['text']
    from app.chat_ai import DIRECT_CITATIONS
    assert DIRECT_CITATIONS not in request['messages'][0]['content']
    assert 'claims.evidence_refs' in request['messages'][0]['content']
    assert '不输出旧引用字段' in request['messages'][0]['content']
    assert '未经学校核验' in request['messages'][0]['content']


def test_indexed_prompt_does_not_mutate_legacy_citation_schema():
    from app.genui_prompt import system_prompt
    from app.chat_ai import DIRECT_CITATIONS
    schema=genui_ai.UIAnswer.model_json_schema()
    system_prompt(1,schema,indexed_evidence=True)
    assert schema['properties']['citations']['maxItems']==genui_ai.MAX_CITATIONS==120
    assert DIRECT_CITATIONS in system_prompt(1,schema)


def test_coverage_followup_respects_material_only_and_is_bounded(env,monkeypatch):
    mocks(monkeypatch);env[1].ai_grounding=True;env[1].ai_api_key='synthetic-only';calls=[]
    async def coverage(*args):
        calls.append('audit');return {'items':[],'personal_fit':'','conflicts':[],'followup_local':['例外要求'],'followup_public':['武汉大学新通知']},{}
    def retrieve(*args):calls.append('retrieve');return evidence(),{'scanned':{},'selected_sources':1}
    async def search(*args):raise AssertionError('限定材料时不得联网')
    monkeypatch.setattr(grounding,'assess_coverage',coverage);monkeypatch.setattr(grounding,'retrieve',retrieve);monkeypatch.setattr(grounding,'search',search)
    c=account(env);chat=conversation(c)
    message=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat,content='只根据材料核对报名时间')))[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='complete' and calls==['retrieve','audit','retrieve']
    assert message['grounding']['coverage_check']['followup_performed']


def test_coverage_rejects_invented_source_id(env,monkeypatch):
    async def complete(*args,**kwargs):
        return {'content':dumps({'items':[{'requirement':'截止时间','status':'supported','source_ids':['invented'],'gap':''}], 'personal_fit':'未知','conflicts':[],'followup_local':[],'followup_public':[]})},{}
    monkeypatch.setattr(grounding,'completion',complete)
    with pytest.raises(AIError):asyncio.run(grounding.assess_coverage(env[1],'截止时间',evidence(),{}))


def test_coverage_format_repair_has_previous_json_and_explicit_constraints(env,monkeypatch):
    previous={'items':[{'requirement':'报名时间','status':'shared','source_ids':['document'],'gap':''}], 'personal_fit':'未知','conflicts':[], 'followup_local':[], 'followup_public':[], '_note':'不允许的字段'}
    corrected={**previous,'items':[{**previous['items'][0],'status':'supported'}]};corrected.pop('_note')
    calls=[]
    async def complete(settings,request):
        calls.append(json.loads(json.dumps(request)))
        return {'content':dumps(previous if len(calls)==1 else corrected)},{}
    monkeypatch.setattr(grounding,'completion',complete)
    checked,_=asyncio.run(grounding.assess_coverage(env[1],'报名时间',evidence(),{}))
    assert checked['items'][0]['source_ids']==['document'] and len(calls)==2
    assert calls[1]['messages'][-2]['role']=='assistant'
    assert 'shared' in calls[1]['messages'][-2]['content']
    repair=calls[1]['messages'][-1]['content']
    assert '_note' in repair and 'supported|partial|missing' in repair


def test_steering_context_retains_prior_request_and_latest_web_scope():
    messages=[{'role':'user','content':'只根据材料，按每天2小时共3天试算。'},{'role':'user','content':'改为4天，其他不变。'}]
    context=grounding.question_context(messages)
    assert '每天2小时' in context and '改为4天' in context and grounding.web_restricted(messages)
    messages.append({'role':'user','content':'现在请联网查官网。'})
    assert not grounding.web_restricted(messages)


def test_current_message_scope_excludes_library_profile_old_messages_and_keeps_steering():
    messages=[{'role':'user','content':'无关旧材料 SECRET-OLD'}, {'role':'user','content':'请只用本条提供的虚构材料：北区服务为两周试点。'}, {'role':'assistant','content':'旧助手文字不能作为证据'}, {'role':'user','content':'补充：重点比较观点与事实。'}]
    assert grounding.message_scope_start(messages)==1
    sources,report=grounding.retrieve(None,'owner','conversation',[],messages,{'school':'SECRET-PROFILE'},['试点'])
    text=dumps(sources);assert '两周试点' in text and '比较观点与事实' in text
    assert 'SECRET-OLD' not in text and 'SECRET-PROFILE' not in text and '旧助手文字' not in text
    assert report['local_scope']=='message' and report['scanned']['materials']==0 and report['scanned']['arrangements']==0
    messages.append({'role':'user','content':'现在请检索我的资料库与日程。'})
    assert grounding.message_scope_start(messages) is None


def test_scoped_workflow_removes_personal_facts_from_generation_inputs(env,monkeypatch):
    client=account(env);chat=conversation(client);owner=client.get('/api/session').json()['user']['id']
    mocks(monkeypatch);env[1].ai_api_key='synthetic-only';seen=[]
    monkeypatch.setattr(grounding,'save_report',lambda *args:None)
    async def stream(settings,sources,messages,profile,tier):
        seen.append((messages,profile));yield {'type':'complete','result':answer(),'usage':{}}
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    messages=[{'role':'user','content':'不要用的旧消息'}, {'role':'user','content':'只依据本条提供的材料说明，其他信息不引用。'}]
    async def run():return [e async for e in grounding.events(env[1],env[0].state.db,owner,chat['id'],'m',[],messages,{'school':'SECRET-PROFILE','response_style':'direct'},1)]
    packets=asyncio.run(run());assert packets[-1]['type']=='complete'
    assert len(seen[0][0])==1 and 'school' not in seen[0][1] and seen[0][1]['response_style']=='direct'
