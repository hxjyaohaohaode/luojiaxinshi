import asyncio
from fastapi import HTTPException
from app import source_sync,notice_automation
from tests.test_workflow import env,account
from tests.test_notice_automation import incoming,permit,generator

def test_retry_backoff_is_durable_bounded_and_recovers_after_success():
    cfg={'interval_minutes':30}
    assert source_sync.retry_delay({},cfg,pending=True,failed=False)==60
    assert source_sync.retry_delay({},cfg,pending=False,failed=False)==1800
    assert source_sync.retry_delay({},cfg,pending=False,failed=True)==1800
    assert source_sync.retry_delay({'error':'failed','next_poll':2800,'checked_at':1000},cfg,pending=True,failed=True)==3600
    assert source_sync.retry_delay({'error':'failed','next_poll':999999,'checked_at':1000},cfg,pending=True,failed=True)==14400
    assert source_sync.retry_delay({'error':'failed'},cfg,pending=False,failed=False)==1800

def test_slow_sources_do_not_hold_an_already_free_slot(monkeypatch):
    async def scenario():
        release=asyncio.Event();started=[];active=0;maximum=0
        async def sync(db,sid):
            nonlocal active,maximum
            started.append(sid);active+=1;maximum=max(maximum,active)
            try:
                if sid=='slow':await release.wait()
                else:await asyncio.sleep(0)
                if sid=='changed':raise HTTPException(404,'removed test source')
                if sid=='third':release.set()
            finally:active-=1
        monkeypatch.setattr(source_sync,'sync_source',sync)
        await asyncio.wait_for(source_sync.poll_batch(None,[{'source_id':s} for s in ['slow','fast','changed','third']]),1)
        assert started==['slow','fast','changed','third']
        assert maximum==2 and active==0
    asyncio.run(scenario())

def test_unexpected_failure_cancels_and_awaits_sibling_pollers(monkeypatch):
    async def scenario():
        cleaned=[]
        async def sync(db,sid):
            if sid=='broken':await asyncio.sleep(0);raise RuntimeError('synthetic storage failure')
            try:await asyncio.sleep(10)
            finally:cleaned.append(sid)
        monkeypatch.setattr(source_sync,'sync_source',sync)
        try:await source_sync.poll_batch(None,[{'source_id':s} for s in ['slow','broken']])
        except ExceptionGroup:pass
        else:raise AssertionError('Expected the storage failure')
        assert cleaned==['slow']
    asyncio.run(scenario())

def test_automation_admission_is_fair_between_users(env,monkeypatch):
    a=account(env);b=account(env,'other');calls=[]
    first,_,uid_a=incoming(env,a,key='a-one');second,_,_=incoming(env,a,key='a-two');third,_,uid_b=incoming(env,b,key='b-one')
    permit(a);permit(b);generator(env,monkeypatch,calls)
    db=env[0].state.db
    with db.connect(write=True) as conn:
        conn.execute('UPDATE notices SET created_at=created_at-60 WHERE user_id=?',(uid_a,))
    notice_automation.run_once(env[0],db,env[1]);notice_automation.run_once(env[0],db,env[1])
    assert len(calls)==2 and {item[2] for item in calls}=={uid_a,uid_b}
