import pytest

from app import ai, notice_calendar
from app.documents import text_source
from app.notice_ingest import ingest_notice
from tests.test_notice_automation import incoming, permit
from tests.test_workflow import env, account, manual, confirm, task, raw_ai


@pytest.mark.parametrize('mode,quality,manually_changed,expected', [
    ('off','passed',False,None),
    ('review','passed',False,'proposed'),
    ('verified_auto','not_run',False,'proposed'),
    ('verified_auto','passed',False,'applied'),
    ('allow_sync','not_run',False,'applied'),
    ('allow_sync','needs_review',False,'proposed'),
    ('allow_sync','passed',True,'proposed'),
])
def test_official_revision_from_generation_to_personal_calendar(env,monkeypatch,mode,quality,manually_changed,expected):
    app,settings=env
    c=account(env)
    nid,sid,uid=incoming(env,c)
    n=manual(c,c.get('/api/notices/'+nid).json())
    tid=confirm(c,n,data=task(n,title='核对申请表',due_date=None,due_time=None,deadline_confirmed=False,deadline_text='',
                              notes='手写备注',planned_at='2027-05-01T09:00:00+08:00',materials=['报名表']))
    t=c.get('/api/tasks').json()[0]
    if manually_changed:
        saved=c.put('/api/tasks/'+tid,json={'version':t['version'],'status':t['status'],'reason':'本人手动核实地点','data':{**t['data'],'location':'自己核对的地点'}})
        assert saved.status_code==200,saved.text
    permit(c,calendar_mode=mode)
    url='https://school.example.edu.cn/info/1.htm'
    quote='正式更正：核对申请表截止到2027年5月3日16:00，地点改至教学楼305，另补签字页。'
    source=text_source(quote)
    source['origin']={'url':url,'retrieved_at':1800000000,'attachments':[]}
    with app.state.db.connect(write=True) as conn:
        received=ingest_notice(conn,uid,sources=[source],title='收到的通知 1',source_label='学院官网',source_url=url,external_key='website:'+sid+':'+url)
        assert received['updated']
    n=c.get('/api/notices/'+nid).json()
    source=next(s for s in n['sources'] if s['active'])
    proof={'source_id':source['id'],'locator':source['sections'][0]['locator'],'quote':quote}
    def generate(*args):
        draft=raw_ai(n)
        draft['quality']={'status':quality,'issues':[],'checked_tasks':1}
        draft['tasks']=[task(n,title='核对申请表',due_date='2027-05-03',due_time='16:00',deadline_text=quote,location='教学楼305',
                             materials=['签字页'],evidence=[proof],deadline_evidence=[proof],origin='ai')]
        return draft,{'input_tokens':5,'output_tokens':5}
    monkeypatch.setattr(ai,'generate',generate)
    settings.ai_api_key='fixture'
    from app.notice_automation import run_once
    assert run_once(app,app.state.db,settings)['state']=='succeeded'
    current=c.get('/api/tasks').json()[0]
    receipts=c.get('/api/notice-automation').json()['calendar_receipts']
    assert (receipts[0]['outcome'] if receipts else None)==expected,receipts
    assert current['status']==t['status'] and current['data']['notes']=='手写备注'
    assert current['data']['planned_at']==t['data']['planned_at']
    if expected=='applied':
        assert current['data']['due_date']=='2027-05-03' and current['data']['due_time']=='16:00'
        assert current['data']['materials']==['报名表','签字页'] and current['data']['location']=='教学楼305'
        assert current['data']['deadline_confirmed']
    else:
        assert current['data']['due_date'] is None
    with app.state.db.connect(write=True) as conn:
        app.state.db.sync_notice_calendar(conn,uid,nid)
        assert len(notice_calendar.last_receipts(conn,uid))==len(receipts)


def test_unquoted_dates_and_materials_cannot_be_promoted():
    proof={'source_id':'web','locator':'p1','quote':'2027年5月1日16:00，仅交申请表。'}
    old={'materials':['申请表'],'due_date':'2027-05-01','due_time':'16:00'}
    new={'due_date':'2027-05-02','due_time':'16:00','evidence':[proof],'deadline_evidence':[proof],'materials':['身份证'],'location':'礼堂'}
    assert notice_calendar.correction(old,new,{('web','p1'):proof['quote']},None)==({},[])
