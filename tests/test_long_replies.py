"""Long replies exercise the actual provider decoder, persistence and review gates."""
import asyncio
import json

import httpx
import pytest

from app import genui_ai, chat_ai, grounding, evidence_web
from app.ai import AIError
from test_workflow import env, account
from test_workspace import conversation
from test_genui_transport import events, payload
from test_grounding import answer, evidence
from app.genui import validate_expression


LONG = ('中文长回复与引用标记 [1]，保留引号“完整”、换行和 emoji 🌸。\n' * 1800) + '最后一段：完整结束。'


def test_model_authored_array_conditions_validate_with_bounded_grammar():
    validate_expression('contains(["全部","文学"],filter)')
    for expression in ['[1,]','[constructor]','[1][0]','['*100+'1'+']'*100]:
        with pytest.raises(ValueError):validate_expression(expression)


def test_long_provider_stream_reaches_history_without_cutoff(env, monkeypatch):
    env[1].ai_api_key='synthetic-only'
    raw=json.dumps({'answer':LONG,'citations':[],'image_sources':[],'claims':[]},ensure_ascii=False)
    assert 16000<len(LONG)<80000
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for start in range(0,len(raw),213):
                packet={'choices':[{'delta':{'content':raw[start:start+213]},'finish_reason':None}]}
                frame=('data: '+json.dumps(packet,ensure_ascii=False)+'\n\n').encode()
                # Arbitrary byte cuts include the middle of multibyte Chinese characters.
                for offset in range(0,len(frame),79):yield frame[offset:offset+79]
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    async def provider(request):
        body=json.loads(request.content)
        assert body['max_completion_tokens']==env[1].ai_output_tokens
        return httpx.Response(200,stream=Chunks())
    original=httpx.AsyncClient
    monkeypatch.setattr(genui_ai.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    c=account(env);chat=conversation(c)
    packets=events(c.post(f"/api/conversations/{chat['id']}/messages/stream",json=payload(chat)))
    assert ''.join(p['data']['text'] for p in packets if p['type']=='delta')==LONG
    message=packets[-1]['data']['conversation']['messages'][-1]
    assert message['status']=='complete' and message['genui']['raw']==LONG
    reloaded=c.get('/api/conversations/'+chat['id']).json()['messages'][-1]
    assert reloaded['content']==LONG and reloaded['genui']['raw']==LONG
    assert chat_ai.ChatAnswer.model_validate({'answer':LONG}).answer==LONG.strip()


def test_url_must_cite_its_actual_source_not_the_user_question():
    url='https://uc.whu.edu.cn/tzgg.htm'
    sources=evidence()+[grounding.source('web','通知公告',[{'locator':'标题','text':'通知公告'}],'web_page',url=url)]
    result=answer();result['answer']=f'[官方入口]({url}) [1]'
    with pytest.raises(ValueError,match='链接旁'):grounding.check_result(result,sources)
    result['citations'].append({'source_id':'web','locator':'标题','quote':'通知公告'})
    result['answer']=f'[官方入口]({url}) [2]'
    grounding.check_result(result,sources)
    result['answer']=f'[{url}]({url}) [2]'
    grounding.check_result(result,sources)
    assert grounding.urls_in('链接 (https://example.com/a(b)).')==['https://example.com/a(b)']


@pytest.mark.parametrize('supported',[True,False])
def test_review_format_repair_never_weakens_evidence_standard(env,monkeypatch,supported):
    calls=[]
    async def completion(settings,request):
        calls.append(json.loads(json.dumps(request)))
        content={'wrong':'format'} if len(calls)==1 else {'supported':supported,'issues':[] if supported else ['原文不支持此结论']}
        return {'content':json.dumps(content)},{'prompt_tokens':2,'completion_tokens':3}
    monkeypatch.setattr(grounding,'completion',completion)
    issues,usage,_=asyncio.run(grounding.verify(env[1],answer(),evidence(),'截止时间',{}))
    assert len(calls)==2 and usage=={'prompt_tokens':4,'completion_tokens':6}
    assert not issues if supported else issues==['原文不支持此结论']
    assert calls[1]['messages'][-2]=={'role':'assistant','content':json.dumps({'wrong':'format'})}
    assert '不要删除任务要求、猜测事实或伪造来源' in calls[1]['messages'][-1]['content']


def test_review_bad_format_still_fails_closed_after_bounded_retry(env,monkeypatch):
    calls=[]
    async def completion(*args):calls.append(1);return {'content':'not JSON'},{}
    monkeypatch.setattr(grounding,'completion',completion)
    with pytest.raises(AIError,match='格式仍未通过'):asyncio.run(grounding.verify(env[1],answer(),evidence(),'截止时间',{}))
    assert len(calls)==2


@pytest.mark.parametrize('finish,expected',[('length','包含思考内容'),('repetition_truncation','因重复而被截断'),(None,'未完整完成')])
def test_stage_termination_reports_actual_cause_without_leaking_provider_body(env,monkeypatch,finish,expected):
    async def provider(request):
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':'PRIVATE-UNVERIFIED-DRAFT'}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(evidence_web.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    with pytest.raises(AIError,match=expected) as caught:
        asyncio.run(evidence_web.completion(env[1],{'messages':[]}))
    assert 'PRIVATE-UNVERIFIED-DRAFT' not in str(caught.value)


def test_planner_retains_latest_steering_and_filters_only_public_query_outputs(env,monkeypatch):
    latest='补充：现在只查最新的学院报名入口，不再查往年的材料。'
    question=grounding.question_context([{'role':'user','content':'原来的背景说明。'*100},{'role':'user','content':latest}])
    async def completion(settings,request):
        assert latest in json.loads(request['messages'][1]['content'])['question']
        return {'content':json.dumps({'local_queries':['最新学院报名'],'public_queries':['武汉大学报名 联系人 foo@example.com 手机13800138000'],'web_reason':'最新补充要求联网'})},{}
    monkeypatch.setattr(grounding,'completion',completion)
    result,_=asyncio.run(grounding.plan(env[1],question,{}))
    assert result['public_queries'] and 'foo@example.com' not in result['public_queries'][0] and '13800138000' not in result['public_queries'][0]
def test_long_answer_preserves_more_than_24_distinct_exact_references():
    from app import genui_ai, grounding
    from app.chat_ai import ChatAnswer
    sources = [grounding.source('original', '完整公开材料',
               [{'locator': f'第{i}段', 'text': f'这是第{i}项原始材料中的独立事实。'} for i in range(40)], 'material')]
    entries = genui_ai.evidence_index(sources)
    raw = {'answer': '\n\n'.join(f'第{i+1}项事实 [{entry["ref"]}]。' for i, entry in enumerate(entries)),
           'citations': [], 'image_sources': [],
           'claims': [{'kind':'fact', 'text': f'第{i+1}项事实', 'citation_indices': [], 'evidence_refs': [entry['ref']]}
                      for i, entry in enumerate(entries)]}
    result = genui_ai.resolve_citations(raw, entries)
    assert len(result['citations']) == 40
    ChatAnswer.model_validate(result)
    grounding.check_result(result, sources)

def test_multi_stage_deadline_is_separate_from_http_idle_timeout(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv('AI_WORKFLOW_TIMEOUT_SECONDS', raising=False)
    monkeypatch.setenv('AI_TIMEOUT_SECONDS', '180')
    configured = Settings.from_env()
    assert configured.ai_workflow_timeout == 1800 and configured.ai_timeout == 180
    monkeypatch.setenv('AI_WORKFLOW_TIMEOUT_SECONDS', '60')
    assert Settings.from_env().ai_workflow_timeout == 60  # Explicit smaller budgets remain respected.
