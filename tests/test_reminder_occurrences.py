from datetime import datetime, timedelta
from app.insights import CST, build_reminders


def arrangement(id='course', **changes):
    data={'title':'合成课程','start_date':'2026-10-27','end_date':'2026-10-27',
          'start_time':'08:00','end_time':'11:40','repeat':'none','location':'合成教室'}
    data.update(changes)
    return {'id':id,'version':1,'data':data}


def test_long_courses_remain_visible_until_the_actual_end_not_one_hour_after_start():
    record=arrangement()
    result=build_reminders([],[],[record],datetime(2026,10,27,10,30,tzinfo=CST))
    item=result['items'][0]
    assert item['phase']=='ongoing' and item['level']=='attention'
    assert '08:00–11:40' in item['text'] and '进行中' in item['text']
    assert item['ends_at']=='2026-10-27T11:40:00+08:00'
    assert not build_reminders([],[],[record],datetime(2026,10,27,11,40,tzinfo=CST))['items']


def test_short_finished_courses_are_removed_and_unknown_ends_are_not_fabricated():
    now=datetime(2026,10,27,8,45,tzinfo=CST)
    assert not build_reminders([],[],[arrangement(end_time='08:30')],now)['items']
    unknown=arrangement(end_time=None)
    item=build_reminders([],[],[unknown],now)['items'][0]
    assert item['ends_at'] is None and '09:00' not in item['text']
    assert not build_reminders([],[],[unknown],now+timedelta(minutes=15))['items']


def test_overnight_and_weekly_overnight_occurrences_are_not_lost_at_midnight():
    record=arrangement(start_date='2026-10-26',end_date='2026-10-27',start_time='23:30',end_time='01:20')
    now=datetime(2026,10,27,0,30,tzinfo=CST)
    one=build_reminders([],[],[record],now)['items'][0]
    assert one['phase']=='ongoing' and '今天 01:20' in one['text']
    record['data'].update(repeat='weekly',repeat_until='2026-11-30')
    two=build_reminders([],[],[record],now+timedelta(days=7))['items'][0]
    assert two['phase']=='ongoing' and one['id']!=two['id']


def test_phase_wording_does_not_reset_read_identity_and_all_day_end_is_exclusive():
    record=arrangement()
    before=build_reminders([],[],[record],datetime(2026,10,27,7,30,tzinfo=CST))['items'][0]
    during=build_reminders([],[],[record],datetime(2026,10,27,10,30,tzinfo=CST))['items'][0]
    assert before['id']==during['id']
    all_day=arrangement(start_date='2026-10-26',end_date='2026-10-27',start_time=None,end_time=None)
    assert build_reminders([],[],[all_day],datetime(2026,10,27,23,59,tzinfo=CST))['items']
    assert not build_reminders([],[],[all_day],datetime(2026,10,28,0,0,tzinfo=CST))['items']


def test_all_upcoming_reminders_are_scheduled_not_just_the_first_twenty():
    now=datetime(2026,10,27,8,tzinfo=CST)
    records=[arrangement(str(index),start_time='09:00') for index in range(27)]
    result=build_reminders([],[],records,now)
    assert len(result['upcoming'])==27
    assert len({item['arrangement_id'] for item in result['upcoming']})==27
