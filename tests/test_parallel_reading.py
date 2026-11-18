import asyncio
from types import SimpleNamespace

import pytest
from app.agent_runtime.team import assignments,gather_evidence,verified_report
from app.agent_runtime.runtime import Run
from app.agent_runtime.types import AgentError
from app.decision_routing import preference
from tests.test_workflow import env,account
from tests.test_workspace import conversation


def test_independent_readers_overlap_and_failed_reader_cannot_publish_an_unassigned_quote(monkeypatch):
    async def exercise():
        docs=[{'id':key,'name':key,'evidence_kind':'material','sections':[{'text':key}]} for key in ('notice','correction','forward')]
        gate=asyncio.Event()
        occupied,peak=0,0
        seen=[]
        async def read(question, entries):
            nonlocal occupied,peak
            occupied+=1;peak=max(peak,occupied)
            seen.append([e['source_id'] for e in entries])
            if occupied==3:gate.set()
            await asyncio.wait_for(gate.wait(),3)
            await asyncio.sleep(.01)
            occupied-=1
            e=entries[0]
            text='different source' if e['source_id']=='forward' else e['quote']
            return {'findings':[{'ref':e['ref'],'quote':text}],'gaps':[]},{}
        run=object.__new__(Run)
        run.agents={};run.observed_agents=set();run.workflow='research';run.calls=0;run.usage=dict(model_calls=0,prompt_tokens=0,completion_tokens=0)
        run.focused_visual=False;run.records={r['id']:r for r in docs};run.uid='test';run.db=None
        run.provider=SimpleNamespace(read_evidence=read);run.settings=SimpleNamespace(ai_timeout=50,ai_daily_limit=12,ai_summary_model='test')
        run.service=SimpleNamespace(model_slots=asyncio.Semaphore(4));run.guard=lambda:None;run.emit=lambda *a:None
        run.evidence_entries=[{'source_id':d['id'],'ref':f'E{i}','quote':d['id'],'locator':'正文'} for i,d in enumerate(docs,1)]
        monkeypatch.setattr('app.agent_runtime.team.rate_limit',lambda *a:None)
        await gather_evidence(run,'核对三份通知的要求',docs)
        assert peak==3 and all(len(s)==1 for s in seen)
        assert sorted(r['status'] for r in run.team_report['assignments'])==['completed','completed','failed']
        assert len(run.pending_agent_results())==3
    # No owner, provider credential, database mutation or external network needed for the barrier.
    asyncio.run(exercise())


def test_small_tasks_and_explicit_no_delegation_do_not_fan_out():
    assert not assignments('解释平均数',[],'direct')
    assert not assignments('不要创建子任务，核对通知',[{'id':'n','name':'原文'}]*2,'research')
    with pytest.raises(AgentError):
        verified_report({'findings':[{'ref':'E2','quote':'wrong'}],'gaps':[]},[{'ref':'E1','source_id':'n','locator':'正文','quote':'true'}])


def test_route_preference_is_owned_versioned_and_persisted(env):
    c=account(env);chat=conversation(c);url='/api/conversations/'+chat['id']+'/decision-routing'
    assert chat['decision_preference']=={'enabled':None,'version':0}
    assert c.put(url,json={'enabled':False,'version':0}).json()=={'enabled':False,'version':1}
    assert c.put(url,json={'enabled':True,'version':0}).status_code==409
    assert c.get('/api/conversations/'+chat['id']).json()['decision_preference']['enabled'] is False
    with env[0].state.db.connect() as conn:assert preference(conn,chat['id'])['enabled'] is False
