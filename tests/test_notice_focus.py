from app.notice_lifecycle import focus_projection
from app.proactive_policy import assess
import pytest

def draft():
    return {'quality':{'status':'passed'},'summary':'有据活动时间','tasks':[{'scope':'personal','title':'参加讲座',
        'scheduled':{'start_date':'2026-11-03','start_time':'16:00','kind':'event','evidence':[{'quote':'时间：2026年11月3日16:00'}]}}]}

def test_current_evidence_has_one_shared_key_time_for_list_and_detail():
    value=focus_projection({},draft(),current=True,now=1793600000)
    assert value['key_time']['date']=='2026-11-03' and value['key_time']['time']=='16:00'
    assert assess({'draft':draft()},current_draft=True,now=1793600000)['focus']==value

@pytest.mark.parametrize('quality',[None,'corrupt',{'status':'needs_review'},{'status':'unavailable'}])
def test_unreviewed_or_malformed_quality_never_creates_a_key_fact(quality):
    d=draft();d['quality']=quality
    assert focus_projection({},d,current=True)['key_time'] is None

def test_stale_and_unsupported_dates_cannot_create_a_key_time():
    d=draft();assert focus_projection({},d,current=False)['key_time'] is None
    d['tasks'][0]['scheduled']['evidence']=[{'quote':'时间：11月3日16:00'}]
    assert focus_projection({'published_at':'2026-11-01'},d,current=True)['key_time'] is None
    d=draft();d['tasks'][0]['scheduled']['start_time']='17:00'
    assert focus_projection({},d,current=True)['key_time'] is None
