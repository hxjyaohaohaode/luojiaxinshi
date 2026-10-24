from tests.test_account_and_insights import client, register, notice_with_task


def finish(c,tid):
    t=next(t for t in c.get('/api/tasks').json() if t['id']==tid)
    response=c.put('/api/tasks/'+tid,json={'version':t['version'],'data':t['data'],'status':'done','reason':'本人核实完成'})
    assert response.status_code==200,response.text


def test_insight_dimensions_follow_actual_archives_and_current_materials(tmp_path):
    _,c=client(tmp_path);register(c)
    n=c.post('/api/notices',data={'title':'参考资料','body':'本通知仅存档参考'}).json()
    saved=c.put('/api/notices/'+n['id']+'/disposition',json={'version':n['version'],'disposition':'reference'})
    assert saved.status_code==200
    data=c.get('/api/insights').json()
    archive=next(row for row in data['dimensions']['notices'] if row['key']=='reference')
    assert archive['ids']==[n['id']] and archive['count']==1
    assert data['notices']['waiting']==0
    text=next(row for row in data['dimensions']['intake'] if row['key']=='text')
    assert text['ids']==[n['id']]
    for rows in data['dimensions'].values():
        for row in rows:assert row['count']==len(row['ids'])


def test_personal_trend_and_origins_exclude_other_people_tasks(tmp_path):
    _,c=client(tmp_path);register(c)
    _,personal=notice_with_task(c,'本人事项',origin='manual')
    _,other=notice_with_task(c,'他人事项',scope='other',origin='ai')
    finish(c,personal);finish(c,other)
    data=c.get('/api/insights').json()
    assert data['tasks']['total']==data['tasks']['done']==data['tasks']['manual']==1
    assert data['tasks']['from_ai']==0
    assert sum(w['done'] for w in data['trend'])==1
    assert all(other not in row['ids'] for key,rows in data['dimensions'].items() if key in {'tasks','timing','progress'} for row in rows)


def test_declined_and_activity_work_are_counted_in_their_actual_dimensions(tmp_path):
    _,c=client(tmp_path);register(c)
    _,tid=notice_with_task(c,'活动安排',scheduled={'kind':'event','start_date':'2027-10-25','start_time':'10:00'})
    data=c.get('/api/insights').json()
    assert next(row for row in data['dimensions']['timing'] if row['key']=='event')['ids']==[tid]
    assert next(row for row in data['dimensions']['timing'] if row['key']=='unverified')['ids']==[tid]
    t=c.get('/api/tasks/'+tid+'/workflow').json()['task']
    response=c.put('/api/tasks/'+tid+'/workflow',json={'version':t['workflow']['version'],'task_version':t['version'],
        'data':{**t['workflow']['data'],'action_kind':'optional','participation':'declined'}})
    assert response.status_code==200,response.text
    data=c.get('/api/insights').json()
    assert data['tasks']['pending']==0
    assert next(row for row in data['dimensions']['tasks'] if row['key']=='excluded')['ids']==[tid]
    assert next(row for row in data['dimensions']['timing'] if row['key']=='event')['count']==0
