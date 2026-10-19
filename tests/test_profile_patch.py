from concurrent.futures import ThreadPoolExecutor

import pytest

from test_workflow import account, env


def profile(client):
    return client.get('/api/session').json()['user']['profile']


def patch(client, changes, expected):
    return client.patch('/api/profile', json={'changes': changes, 'expected': expected})


def test_independent_profile_sections_merge_without_lost_updates(env):
    client=account(env)
    initial=profile(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(patch,client,{'college':'测试学院'},{'college':initial['college']})
        b=pool.submit(patch,client,{'response_style':'direct'},{'response_style':initial['response_style']})
        assert a.result().status_code == b.result().status_code == 200
    saved=profile(client)
    assert saved['college']=='测试学院'
    assert saved['response_style']=='direct'
    assert saved['school']==initial['school']


def test_conflicting_field_rejects_entire_patch_and_supports_explicit_reconciliation(env):
    client=account(env)
    initial=profile(client)
    assert patch(client,{'college':'先保存学院'},{'college':initial['college']}).status_code==200
    result=patch(client,{'college':'后保存学院','semester':'新学期'},
                 {'college':initial['college'],'semester':initial['semester']})
    assert result.status_code==409
    detail=result.json()['detail']
    assert detail['code']=='profile_conflict' and detail['fields']==['college']
    assert profile(client)['semester']==initial['semester']
    assert detail['profile']['college']=='先保存学院'
    assert patch(client,{'college':'后保存学院','semester':'新学期'},
                 {'college':detail['profile']['college'],'semester':detail['profile']['semester']}).status_code==200


def test_parallel_same_field_has_exactly_one_winner(env):
    client=account(env)
    old=profile(client)['college']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(patch,client,{'college':value},{'college':old}) for value in ['学院甲','学院乙']]
        results=[f.result() for f in futures]
    assert sorted(r.status_code for r in results)==[200,409]
    winner=next(r.json()['profile']['college'] for r in results if r.status_code==200)
    assert profile(client)['college']==winner


def test_idempotent_repeat_empty_patch_and_explicit_clear(env):
    client=account(env)
    old=profile(client)
    for _ in range(2):
        assert patch(client,{'semester':'测试学期'},{'semester':old['semester']}).status_code==200
    assert patch(client,{},{}).json()['profile']['semester']=='测试学期'
    assert patch(client,{'semester':''},{'semester':'测试学期'}).json()['profile']['semester']==''


@pytest.mark.parametrize('changes,expected',[
    ({'college':'新值'},{}),
    ({},{'college':''}),
    ({'role':'admin'},{'role':'user'}),
    ({'college':'过'*81},{'college':''}),
    ({'semester_start':'2026-02-30'},{'semester_start':''}),
    ({'week_starts_on':9},{'week_starts_on':1}),
])
def test_patch_rejects_unchecked_unknown_or_invalid_values(env,changes,expected):
    client=account(env)
    old=profile(client)
    assert patch(client,changes,expected).status_code==422
    assert profile(client)==old


def test_patch_uses_authenticated_account_and_csrf(env):
    alice,bob=account(env,'alice'),account(env,'bob')
    assert patch(alice,{'college':'甲的学院'},{'college':''}).status_code==200
    assert profile(bob)['college']==''
    bob.headers.pop('X-CSRF-Token')
    assert patch(bob,{'college':'缺少校验'},{'college':''}).status_code==403
