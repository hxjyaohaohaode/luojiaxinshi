"""Length stops stay unpublished and only get a bounded, authorized stage retry."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app import grounding, evidence_web
from app.ai import AIError, AIBudgetError
from app.config import Settings


def request(tokens=5000):
    return {'model':'mimo-v2.6-pro','thinking':{'type':'enabled'},'max_completion_tokens':tokens,
            'messages':[{'role':'user','content':'controlled QA'}]}


def test_length_stop_has_typed_usage_and_never_exposes_the_partial_body(monkeypatch):
    original = httpx.AsyncClient
    def respond(req):
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':'PRIVATE PARTIAL BODY','reasoning_content':'PRIVATE REASONING'}}],
                                      'usage':{'prompt_tokens':20,'completion_tokens':5000}})
    monkeypatch.setattr(evidence_web.httpx,'AsyncClient',lambda **kw:original(**{**kw,'transport':httpx.MockTransport(respond)}))
    with pytest.raises(AIBudgetError) as error:
        asyncio.run(evidence_web.completion(Settings(data_dir=Path('.')),request()))
    assert error.value.usage['completion_tokens']==5000 and 'PRIVATE' not in str(error.value)


def test_stage_expands_once_without_retrieving_again_or_disabling_thinking(monkeypatch):
    seen=[]
    async def complete(settings,payload):
        seen.append(payload['max_completion_tokens'])
        assert payload['thinking']=={'type':'enabled'} and 'temperature' not in payload
        if len(seen)==1:raise AIBudgetError('length',usage={'prompt_tokens':10,'completion_tokens':5000})
        return {'content':json.dumps({'supported':True,'issues':[]})},{'prompt_tokens':12,'completion_tokens':40}
    monkeypatch.setattr(grounding,'completion',complete)
    initial=request();result,usage=asyncio.run(grounding.structured_check(Settings(data_dir=Path('.')),initial,grounding.Review,'审查'))
    assert seen==[5000,32768] and initial['max_completion_tokens']==5000
    assert result['supported'] and usage=={'prompt_tokens':22,'completion_tokens':5040}


@pytest.mark.parametrize('error',[AIError('credential invalid'),AIBudgetError('length at ceiling')])
def test_authentication_and_ceiling_errors_are_not_retried(monkeypatch,error):
    seen=[]
    async def complete(*args):seen.append(True);raise error
    monkeypatch.setattr(grounding,'completion',complete)
    with pytest.raises(type(error)):
        asyncio.run(grounding.structured_check(Settings(data_dir=Path('.')),request(32768),grounding.Review,'审查'))
    assert len(seen)==1


def test_format_and_budget_repairs_have_independent_finite_limits(monkeypatch):
    seen=[]
    async def complete(settings,payload):
        seen.append(payload['max_completion_tokens'])
        if len(seen)==1:return {'content':'invalid JSON'},{'prompt_tokens':1,'completion_tokens':2}
        if len(seen)==2:raise AIBudgetError('length',usage={'prompt_tokens':3,'completion_tokens':5000})
        return {'content':'{"supported":true,"issues":[]}'},{'prompt_tokens':4,'completion_tokens':5}
    monkeypatch.setattr(grounding,'completion',complete)
    result,usage=asyncio.run(grounding.structured_check(Settings(data_dir=Path('.')),request(),grounding.Review,'审查'))
    assert seen==[5000,5000,32768] and result['supported']
    assert usage=={'prompt_tokens':8,'completion_tokens':5007}
