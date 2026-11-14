"""Only changed owners are replanned; time and dispatch remain independently checked."""
from app.notification_coordination import coordinate
from tests.test_workflow import env,account,notice


def test_stable_accounts_skip_replanning_other_owner_writes_do_not_invalidate(env):
    c=account(env);other=account(env,'other');db=env[0].state.db
    uid=c.get('/api/session').json()['user']['id'];calls=[]
    def replan(conn,owner,now):calls.append((owner,now))
    assert coordinate(db,uid,'push',1000,replan)
    assert not coordinate(db,uid,'push',1015,replan)
    notice(other)
    assert not coordinate(db,uid,'push',1030,replan)
    notice(c)
    assert coordinate(db,uid,'push',1031,replan)
    assert not coordinate(db,uid,'push',1045,replan)
    assert coordinate(db,uid,'push',1091,replan)
    assert len(calls)==3


def test_channels_have_independent_checkpoints_and_failed_reconciliation_never_advances(env):
    import pytest
    c=account(env);db=env[0].state.db;uid=c.get('/api/session').json()['user']['id']
    def fail(conn,owner,now):raise RuntimeError('synthetic interrupted planner')
    with pytest.raises(RuntimeError):coordinate(db,uid,'email',1000,fail)
    assert coordinate(db,uid,'email',1001,lambda *args:None)
    assert coordinate(db,uid,'push',1001,lambda *args:None)
    assert not coordinate(db,uid,'email',1002,lambda *args:None)
    # A wall-clock rollback cannot indefinitely suppress the temporal fallback.
    assert coordinate(db,uid,'email',999,lambda *args:None)
