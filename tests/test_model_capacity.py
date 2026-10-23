"""Full-capacity cloud requests and real preflight boundaries; no paid calls."""
import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.ai import AIError
from app.agent_runtime.providers import Provider, completion_budget
from app.agent_runtime.context import compact, size
from app.media_input import input_budget


def test_full_capacity_defaults_and_environment_are_consistent(tmp_path, monkeypatch):
    for key in ('AI_CONTEXT_TOKENS','AI_OUTPUT_TOKENS','AGENT_CONTEXT_BYTES','NOTICE_INPUT_TOKENS'):
        monkeypatch.delenv(key,raising=False)
    direct=Settings(tmp_path)
    loaded=Settings.from_env()
    for cfg in (direct,loaded):
        assert cfg.ai_context_tokens == 1_000_000
        assert cfg.ai_output_tokens == completion_budget(cfg) == 131_072
        assert cfg.agent_context_bytes == 2_000_000
        assert cfg.notice_input_tokens == 868_928
        assert cfg.agent_oss_context_tokens == 32_768


@pytest.mark.parametrize('key,value',[('AI_CONTEXT_TOKENS','1000001'),('AI_OUTPUT_TOKENS','131073'),('AGENT_CONTEXT_BYTES','2000001')])
def test_capacity_does_not_claim_more_than_the_supported_model(key,value,monkeypatch):
    monkeypatch.setenv(key,value)
    with pytest.raises(ValueError):Settings.from_env()


def test_prompt_larger_than_previous_window_reaches_transport_unchanged(tmp_path,monkeypatch):
    cfg=Settings(tmp_path,ai_api_key='synthetic-secret')
    body='完整材料与精确数值。' * 16000 + '末尾校验：57931'
    current=[{'role':'user','content':body}]
    packed,stats=compact('只分析提供的材料',[],current,[],min(cfg.agent_context_bytes,(cfg.ai_context_tokens-cfg.ai_output_tokens)*2))
    assert stats['packed_bytes'] > 300_000 and packed[-1]['content'] == body
    seen=[]
    def respond(request):
        payload=json.loads(request.content);seen.append(payload)
        assert payload['thinking']=={'type':'enabled'}
        assert payload['max_completion_tokens']==131072
        assert payload['messages'][-1]['content']==body
        return httpx.Response(200,json={'model':cfg.ai_model,'choices':[{'finish_reason':'stop','message':{'content':'57931'}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(respond)))
    result,_=asyncio.run(Provider(cfg,'mimo').complete(packed,[]))
    assert result['content']=='57931' and len(seen)==1


def test_multimodal_preflight_reserves_the_full_output_window():
    source={'id':'a','name':'语音','kind':'mp3','content':b'synthetic','sections':[{'locator':'媒体信息','text':'{"seconds":160}'}]}
    # 1,000 audio tokens + text + 128K output; one further byte crosses the window.
    text_bytes=(1_000_000-131_072-1000)*2
    result=input_budget([source],1_000_000,text_bytes,output_tokens=131_072)
    assert result['estimated_media_tokens']==1000
    with pytest.raises(AIError):input_budget([source],1_000_000,text_bytes+1,output_tokens=131_072)


@pytest.mark.parametrize('finish',['length','repetition_truncation'])
def test_incomplete_model_reports_real_finish_and_usage_without_private_content(tmp_path,monkeypatch,finish):
    cfg=Settings(tmp_path,ai_api_key='synthetic-secret')
    original=httpx.AsyncClient
    response={'model':cfg.ai_model,'choices':[{'finish_reason':finish,'message':{'content':'PRIVATE PARTIAL','reasoning_content':'PRIVATE THOUGHT'}}],
              'usage':{'prompt_tokens':12,'completion_tokens':131072,'completion_tokens_details':{'reasoning_tokens':131000}}}
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda _:httpx.Response(200,json=response))))
    from app.agent_runtime.types import AgentError
    with pytest.raises(AgentError) as error:asyncio.run(Provider(cfg,'mimo').complete([{'role':'user','content':'test'}],[]))
    assert error.value.finish_reason==finish and error.value.usage['completion_tokens']==131072
    assert error.value.usage['provider_model']==cfg.ai_model and 'PRIVATE' not in str(error.value)
