"""Reused publisher URLs must not overwrite another academic/batch round."""
from app.documents import text_source
from app.notice_ingest import ingest_notice
from tests.test_workflow import account, env, manual, confirm, task


def test_reused_external_url_keeps_rounds_tasks_and_late_old_versions_separate(env):
    client=account(env);uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    def receive(title,body,observed,published):
        with db.connect(write=True) as conn:
            return ingest_notice(conn,uid,title=title,sources=[text_source(body)],source_url='https://school.example.edu.cn/info/current',
                external_key='website:reused',observed_at=observed,published_at=published)
    first=receive('2026年第一轮奖学金申报','旧年度申请材料',100,'2026-10-01T08:00:00+08:00')
    n=manual(client,client.get('/api/notices/'+first['notice_id']).json())
    tid=confirm(client,n,task(n,due_date=None,due_time=None,deadline_text='',deadline_confirmed=False))
    second=receive('2027年第一轮奖学金申报','新年度申请材料',200,'2027-10-01T08:00:00+08:00')
    assert second['created'] and second['round_separated'] and second['notice_id']!=first['notice_id']
    correction=receive('2027年第一轮奖学金申报更正','新年度材料更正',250,'2027-10-02T08:00:00+08:00')
    assert correction['updated'] and correction['notice_id']==second['notice_id']
    late=receive('2026年第一轮奖学金申报补充','旧年度补充资料',150,'2026-10-02T08:00:00+08:00')
    assert late['updated'] and late['notice_id']==first['notice_id']
    replay=receive('2026年第一轮奖学金申报','旧年度申请材料',120,'2026-10-01T08:00:00+08:00')
    assert replay['stale'] and replay['notice_id']==first['notice_id']
    old=client.get('/api/notices/'+first['notice_id']).json();new=client.get('/api/notices/'+second['notice_id']).json()
    assert [t['id'] for t in old['tasks']]==[tid]
    assert new['title']=='2027年第一轮奖学金申报更正'
    assert not new['tasks']


def test_identical_template_different_batch_and_supplementary_intake_do_not_merge(env):
    client=account(env);uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    result=[]
    with db.connect(write=True) as conn:
        for at,title in enumerate(['2027年项目报名','2027年项目第二轮报名','2027年项目补录'],100):
            result.append(ingest_notice(conn,uid,title=title,sources=[text_source('提交申请表')],external_key='website:one-url',observed_at=at))
    assert len({r['notice_id'] for r in result})==3


def test_same_named_business_year_correction_published_next_year_keeps_identity(env):
    client=account(env);uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    with db.connect(write=True) as conn:
        first=ingest_notice(conn,uid,title='2026年奖学金申请',sources=[text_source('原要求')],external_key='website:cross-calendar',published_at='2026-12-30T08:00:00+08:00',observed_at=100)
        second=ingest_notice(conn,uid,title='2026年奖学金申请更正',sources=[text_source('更正要求')],external_key='website:cross-calendar',published_at='2027-01-02T08:00:00+08:00',observed_at=200)
    assert second['notice_id']==first['notice_id'] and second['updated']


def test_explicit_publication_revision_can_correct_its_year_without_splitting(env):
    client=account(env);uid=client.get('/api/session').json()['user']['id'];db=env[0].state.db
    with db.connect(write=True) as conn:
        first=ingest_notice(conn,uid,title='2026年通知',sources=[text_source('原正文')],external_key='campus-publication:stable',observed_at=100,separate_rounds=False)
        second=ingest_notice(conn,uid,title='2027年通知',sources=[text_source('年份纠错')],external_key='campus-publication:stable',observed_at=200,separate_rounds=False)
    assert second['notice_id']==first['notice_id'] and second['updated']
