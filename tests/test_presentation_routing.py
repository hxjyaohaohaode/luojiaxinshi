"""Presentation work is proportional to the request; evidence review stays intact."""
import pytest
from app import genui_ai,grounding
from app.config import Settings


@pytest.mark.parametrize('tier,choice,no_ui,expected',[
    (1,'text',False,3),(1,'compact',False,1),(1,'interactive',False,1),
    (1,'auto',False,1),(2,'interactive',False,2),(3,'compact',False,3),
    (3,'interactive',False,3),(1,'interactive',True,3),(2,'compact',True,3),
])
def test_planner_can_simplify_without_exceeding_host_capabilities(tier,choice,no_ui,expected):
    assert genui_ai.presentation_tier(tier,choice,no_ui=no_ui)==expected


def test_coverage_aware_composition_avoids_a_second_thinking_pass_but_keeps_the_evidence_protocol(tmp_path):
    settings=Settings(tmp_path)
    messages=[{'role':'user','content':'显示我记录的安排'}]
    profile={'_grounding_context':{'route':'focused_text','coverage_check':{'items':[]}}}
    for tier in (1,2):
        request=genui_ai.payload(settings,[],messages,profile,tier)
        assert request['thinking']=={'type':'disabled'}
        assert request['response_format']=={'type':'json_object'}
        assert 'claims' in request['messages'][0]['content']
        assert '独立' in request['messages'][0]['content']
    # Text that also performs the evidence-coverage analysis retains reasoning.
    assert genui_ai.payload(settings,[],messages,profile,3)['thinking']=={'type':'enabled'}
    # Ungrounded direct generation retains its existing reasoning behavior.
    assert genui_ai.payload(settings,[],messages,{},1)['thinking']=={'type':'enabled'}


def test_missing_presentation_is_backward_compatible_and_unknown_modes_are_rejected():
    assert grounding.QueryPlan(web_reason='无需联网').presentation=='auto'
    with pytest.raises(ValueError):grounding.QueryPlan(web_reason='无需联网',presentation='execute_arbitrary_html')


def test_stream_telemetry_reports_the_thinking_mode_actually_sent(tmp_path,monkeypatch):
    import asyncio
    from app.harness import Trace,CURRENT
    async def fixture(*args):yield {'type':'complete','usage':{}}
    monkeypatch.setattr(genui_ai,'_stream_reply',fixture)
    settings=Settings(tmp_path)
    for profile in ({},{'_grounding_context':{'route':'focused_text'}},{'_grounding_context':{'status':'checking'}}):
        for tier in (1,2,3):
            trace=Trace();token=CURRENT.set(trace)
            try:
                async def run():
                    async for _ in genui_ai.stream_reply(settings,[],[],profile,tier):pass
                asyncio.run(run())
            finally:CURRENT.reset(token)
            assert trace.snapshot()['calls'][0]['thinking']==genui_ai.payload(settings,[],[],profile,tier)['thinking']['type']
