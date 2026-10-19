import copy

import pytest

from test_workflow import env,account,notice,manual


def ready(env):
    c=account(env);n=manual(c,notice(c))
    p={'version':n['version'],'reviewed':True,'tasks':[{'title':'核对本人提交要求'}],
       'review_observation':{'method':'visible_idle_60s_v1','active_ms':61234,'editing_ms':15000}}
    return c,n,p


@pytest.mark.parametrize('field,value',[('active_ms',True),('active_ms',-1),('active_ms',28_800_001),
    ('active_ms','123'),('editing_ms',61235),('editing_ms',1.5),('method','verified_total'),('keystrokes','private text')])
def test_invalid_observation_rejected_atomically(env,field,value):
    c,n,p=ready(env);p['review_observation'][field]=value
    assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==422
    assert c.get('/api/tasks').json()==[]
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM confirmations').fetchone()[0]==0


def test_timing_is_optional_and_replays_cannot_rewrite_original_observation(env):
    c,n,p=ready(env);url='/api/notices/'+n['id']
    assert c.post(url+'/confirm',json=p).status_code==200
    first=c.get(url).json()['quality_receipt'];assert first['observation']==p['review_observation']
    p['review_observation']['active_ms']=100000
    assert c.post(url+'/confirm',json=p).json()['replayed']
    assert c.get(url).json()['quality_receipt']==first
    other=manual(c,notice(c,'另一个通知'))
    p.pop('review_observation');p['version']=other['version']
    assert c.post('/api/notices/'+other['id']+'/confirm',json=p).status_code==200
    assert 'observation' not in c.get('/api/notices/'+other['id']).json()['quality_receipt']


def test_observation_export_import_keeps_historical_scope_and_rejects_bad_values(env):
    c,n,p=ready(env);assert c.post('/api/notices/'+n['id']+'/confirm',json=p).status_code==200
    exported=c.get('/api/export').json()
    other=account(env,'observer-bob');assert other.get('/api/notices/'+n['id']).status_code==404
    bad=copy.deepcopy(exported);bad['notices'][0]['quality_receipt']['observation']['editing_ms']=999999
    assert other.post('/api/import',json={'data':bad}).status_code==422
    assert other.get('/api/notices').json()==[]
    preview=other.post('/api/import',json={'data':exported});assert preview.status_code==200,preview.text
    imported=other.post('/api/import',json={'data':exported,'confirm':True,'digest':preview.json()['digest']})
    assert imported.status_code==200,imported.text
    record=other.get('/api/export').json()['notices'][0]['quality_receipt']
    assert record['imported'] and record['observation']==p['review_observation']
