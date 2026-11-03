"""Real storage/transaction checks; model/network boundaries are isolated fixtures."""
import json
import asyncio
import uuid

import pytest

from app import campus_imports as imports
from app.db import Database
from app.usage_limits import UsageLimits
from test_workflow import env, account


def course(**changes):
    return {'title':'【工程测试】地理学','weekday':1,'weeks':'1-6(单)','periods':'第 1-2 节',
            'start_time':'08:00','end_time':'09:35','location':'测试教室','notes':'', 'evidence':'地理学 1-6(单)', **changes}


def body(**changes):
    return {'kind':'courses','request_id':uuid.uuid4().hex,'reviewed':True,'semester_start':'2026-09-07','courses':[course()],**changes}


@pytest.mark.parametrize(('text','expected'), [('第1-6周（单）',[1,3,5]),('1-6(双)',[2,4,6]),('1-3,5,8-9',[1,2,3,5,8,9]),('1、3、5',[1,3,5])])
def test_explicit_week_numbers_ranges_and_parity(text,expected):
    assert imports.parse_weeks(text)==expected


@pytest.mark.parametrize('text',['','全学期','1-41','8-2','0,1','1-4;5','2(单)','1-8(单),10'])
def test_ambiguous_week_numbers_are_rejected(text):
    with pytest.raises(ValueError):imports.parse_weeks(text)


def test_courses_save_real_calendar_dates_idempotently_with_owner_isolation(env):
    c=account(env);other=account(env,'bob');payload=body()
    result=c.post('/api/campus-imports/commit',json=payload);assert result.status_code==200,result.text
    assert result.json()['created']==3
    records=c.get('/api/arrangements').json()
    assert sorted(x['data']['start_date'] for x in records)==['2026-09-07','2026-09-21','2026-10-05']
    assert {x['data']['start_time'] for x in records}=={'08:00'}
    assert all(x['data']['category']=='course' for x in records)
    assert c.post('/api/campus-imports/commit',json=payload).json()==result.json()
    assert c.get('/api/campus-imports/receipts/'+payload['request_id']).json()==result.json()
    assert other.get('/api/campus-imports/receipts/'+payload['request_id']).json()=={'state':'missing'}
    assert other.get('/api/arrangements').json()==[]
    changed=body(request_id=payload['request_id'],courses=[course(title='另一门课程')])
    assert c.post('/api/campus-imports/commit',json=changed).status_code==409
    assert c.post('/api/campus-imports/commit',json=body()).json()['created']==0
    assert len(c.get('/api/arrangements').json())==3


def test_even_weeks_and_weekday_use_civil_beijing_dates_across_year(env):
    c=account(env)
    r=c.post('/api/campus-imports/commit',json=body(semester_start='2026-12-28',courses=[course(weekday=7,weeks='1-4(双)')]))
    assert r.status_code==200,r.text
    assert sorted(x['data']['start_date'] for x in c.get('/api/arrangements').json())==['2027-01-10','2027-01-24']


@pytest.mark.parametrize('change',[{'reviewed':False},{'semester_start':'2026-09-08'},{'courses':[course(start_time=None,end_time=None)]},
    {'courses':[course(weeks='全学期')]},{'courses':[course(end_time='07:00')]},{'courses':[course(weekday=None)]},
    {'accounts':[{'name':'类型不符'}]}])
def test_incomplete_or_unreviewed_courses_do_not_partially_write(env,change):
    c=account(env);r=c.post('/api/campus-imports/commit',json=body(**change));assert r.status_code==422,r.text
    assert c.get('/api/arrangements').json()==[]


def test_capacity_failure_is_atomic_and_does_not_consume_import_receipt(env):
    c=account(env);env[0].state.db.usage_limits=UsageLimits(arrangements=2);payload=body()
    assert c.post('/api/campus-imports/commit',json=payload).status_code==413
    assert c.get('/api/arrangements').json()==[]
    assert c.get('/api/campus-imports/receipts/'+payload['request_id']).json()['state']=='missing'
    env[0].state.db.usage_limits=UsageLimits()
    assert c.post('/api/campus-imports/commit',json=payload).json()['created']==3


def test_account_import_retains_identity_without_enabling_unavailable_channels(env):
    c=account(env);other=account(env,'bob')
    payload={'kind':'accounts','request_id':uuid.uuid4().hex,'reviewed':True,
             'accounts':[{'name':'同名公众号','wechat_id':'gh_fixture_one'},{'name':'同名公众号','wechat_id':'gh_fixture_two'}]}
    r=c.post('/api/campus-imports/commit',json=payload);assert r.status_code==200,r.text
    assert r.json()['created']==2
    assert {x['data']['wechat_id'] for x in c.get('/api/source-catalog').json()}=={'gh_fixture_one','gh_fixture_two'}
    assert all(not s['enabled'] and s['state']=='manual' for s in c.get('/api/source-subscriptions').json())
    assert other.get('/api/source-catalog').json()==[]
    assert c.post('/api/campus-imports/commit',json=payload).json()==r.json()
    payload['request_id']=uuid.uuid4().hex
    assert c.post('/api/campus-imports/commit',json=payload).json()['created']==0
    payload['request_id']=uuid.uuid4().hex;payload['accounts']=[{'name':'同名公众号'}]
    assert c.post('/api/campus-imports/commit',json=payload).json()['created']==0


def test_preview_requires_explicit_ai_consent_and_config_and_never_commits(env,monkeypatch):
    c=account(env)
    files=[('files',('课表.csv','课程,周次\n地理学,1-6(单)'.encode(),'text/csv'))]
    assert c.post('/api/campus-imports/preview',data={'kind':'courses'},files=files).status_code==422
    assert c.post('/api/campus-imports/preview',data={'kind':'courses','allow_external_processing':'true'},files=files).status_code==503
    env[1].ai_api_key='isolated-not-a-real-provider-key'
    async def recognize(settings,kind,sources):
        assert kind=='courses' and sources[0]['kind']=='csv'
        assert any('地理学' in x['text'] for x in sources[0]['sections'])
        return {'rows':[course()],'warnings':['工程夹具，非真实模型验收']}
    monkeypatch.setattr(imports,'recognize',recognize)
    r=c.post('/api/campus-imports/preview',data={'kind':'courses','allow_external_processing':'true'},files=files)
    assert r.status_code==200,r.text
    assert len(r.json()['rows'])==1 and 'content' not in json.dumps(r.json())
    assert c.get('/api/arrangements').json()==[]
    assert c.get('/api/source-catalog').json()==[]
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM conversation_sources').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM campus_import_receipts').fetchone()[0]==0


def test_lookup_needs_own_action_and_surfaces_search_boundary_without_subscription(env,monkeypatch):
    c=account(env);env[1].ai_api_key='isolated-not-a-real-provider-key'
    async def lookup(settings,payload):
        assert payload.name=='测试公众号'
        return {'items':[],'presets':[],'status':'no_evidence','note':'未找到可验证来源'}
    monkeypatch.setattr(imports,'lookup',lookup)
    assert c.post('/api/campus-imports/lookup',json={'name':'测试公众号'}).status_code==422
    r=c.post('/api/campus-imports/lookup',json={'name':'测试公众号','allow_external_search':True})
    assert r.status_code==200 and r.json()['status']=='no_evidence'
    assert c.get('/api/source-subscriptions').json()==[]


def test_future_import_schema_refused_without_migration(env):
    db=env[0].state.db
    with db.connect(write=True) as conn:conn.execute("UPDATE meta SET value='99' WHERE key='campus_import_schema_version'")
    with pytest.raises(RuntimeError,match='校园导入'):Database(db.path)
    with db.connect() as conn:assert conn.execute("SELECT value FROM meta WHERE key='campus_import_schema_version'").fetchone()[0]=='99'


def test_text_evidence_compares_original_tabs_instead_of_json_escape_sequences(env,monkeypatch):
    from app.documents import file_source
    calls=[]
    async def completion(settings,payload):
        calls.append(payload)
        return {'content':json.dumps({'rows':[course(evidence='地理学 1-6(单)')],'warnings':[]},ensure_ascii=False)},{}
    monkeypatch.setattr('app.grounding.completion',completion)
    source=file_source('fixture.csv','地理学,1-6(单)\n'.encode())
    result=asyncio.run(imports.recognize(env[1],'courses',[source]))
    assert result['rows'][0]['evidence']=='地理学 1-6(单)'
    assert len(calls)==1


def test_import_receipts_survive_valid_restore_and_are_removed_with_their_owner(env,tmp_path):
    from app.backups import restore_database
    from test_workflow import PASSWORD
    c=account(env);payload=body();assert c.post('/api/campus-imports/commit',json=payload).status_code==200
    source=tmp_path/'snapshot.sqlite3';env[0].state.db.backup(source)
    destination=tmp_path/'restored'/'campus.sqlite3';restore_database(source,destination)
    restored=Database(destination)
    with restored.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM campus_import_receipts').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM arrangements').fetchone()[0]==3
    assert c.post('/api/account/delete',json={'password':PASSWORD,'confirm':'注销账号'}).status_code==200
    with env[0].state.db.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM campus_import_receipts').fetchone()[0]==0


def test_lookup_rejects_other_universities_and_offers_explicit_institution_presets(env,monkeypatch):
    name='武汉大学资源与环境科学学院';queries=[]
    async def search(settings,values):
        queries.extend(values)
        return [
            {'name':name,'url':'https://cee.njfu.edu.cn/other','sections':[{'text':name}],'evidence_kind':'web_page'},
            {'name':'不相关的武大事项','url':'https://www.sgg.whu.edu.cn/unrelated','sections':[{'text':'其他院系内容'}],'evidence_kind':'web_page'},
            {'name':name,'url':'https://sres.whu.edu.cn/xxgk/tzgg.htm','sections':[{'text':name+'通知公告'}],'evidence_kind':'web_page'}
        ],{'status':'searched'},{}
    monkeypatch.setattr('app.evidence_web.search',search)
    result=asyncio.run(imports.lookup(env[1],imports.Lookup(name=name,institution='武汉大学')))
    assert 'site:whu.edu.cn' in queries[0]
    assert [item['url'] for item in result['items']]==['https://sres.whu.edu.cn/xxgk/tzgg.htm']
    assert 'whu-sres-notices' in {p['id'] for p in result['presets']}
    assert result['status']=='searched'


def test_empty_search_never_claims_publisher_access_or_invents_account_identity(env,monkeypatch):
    async def search(settings,values):return [],{'status':'unavailable'},{}
    monkeypatch.setattr('app.evidence_web.search',search)
    result=asyncio.run(imports.lookup(env[1],imports.Lookup(name='身份未知的同名账号')))
    assert result['items']==[] and result['presets']==[] and result['status']=='unavailable'
