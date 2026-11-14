"""Real HTTP pagination/index isolation, mutation and semantic-filter regressions."""
import json
import time

import pytest

from app.db import dumps,ident
from app.documents import text_source
from tests.test_workflow import env,account,notice,manual,confirm,task


def seed(env,client,count=131):
    uid=client.get('/api/session').json()['user']['id']; db=env[0].state.db
    ids=[]; now=int(time.time())
    with db.connect(write=True) as conn:
        for index in range(count):
            nid,sid=ident(),ident(); ids.append(nid)
            source=text_source(f'合成条目 {index}。申请材料中有课程编号-{index}。共同第二轮。')
            conn.execute('INSERT INTO notices(id,user_id,title,source_label,source_url,materials_complete,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (nid,uid,f'合成通知{index}','学院来源','',1,'seed:'+nid,now-index,now-index))
            conn.execute('INSERT INTO sources(id,notice_id,name,kind,content,sha256,status,sections,warning,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (sid,nid,'证据正文','text',None,source['sha256'],'ok',dumps(source['sections']),'',now))
    return uid,ids


def test_all_pages_cover_the_exact_inventory_with_bounded_bodies(env):
    c=account(env);_,ids=seed(env,c)
    seen=[]; cursor=''
    while True:
        response=c.get('/api/notices/page',params={'limit':50,'cursor':cursor})
        assert response.status_code==200,response.text
        page=response.json(); assert page['total']==len(ids)
        assert len(page['items'])<=50 and len(response.content)<500000
        assert all('draft' not in row and 'sources' not in row for row in page['items'])
        seen.extend(row['id'] for row in page['items'])
        if not page['has_more']:break
        cursor=page['next_cursor']; assert cursor
    assert seen==ids and len(set(seen))==131


def test_index_matches_body_title_short_chinese_and_literal_punctuation(env):
    c=account(env);_,ids=seed(env,c,4)
    for query,expected in [('课程编号-2。',[ids[2]]),('合成通知1',[ids[1]]),('材料',ids),('共同第二轮 课程编号-3。',[ids[3]])]:
        r=c.get('/api/notices/page',params={'q':query})
        assert r.status_code==200,r.text
        assert {row['id'] for row in r.json()['items']}==set(expected)
        if expected:assert r.json()['items'][0]['search_source']
    assert c.get('/api/notices/page',params={'q':'" OR "'}).status_code==200
    assert c.get('/api/notices/page',params={'q':'x'*201}).status_code==422


def test_index_tracks_source_revisions_archive_delete_and_transaction_rollback(env):
    c=account(env);_,ids=seed(env,c,2); db=env[0].state.db
    def search(term):return c.get('/api/notices/page',params={'q':term}).json()['total']
    with db.connect(write=True) as conn:
        conn.execute('UPDATE sources SET sections=? WHERE notice_id=?',(dumps([{'locator':'p1','text':'已更正新证据'}]),ids[0]))
    assert search('已更正新证据')==1 and search('课程编号-0。')==0
    try:
        with db.connect(write=True) as conn:
            conn.execute('UPDATE sources SET sections=? WHERE notice_id=?',(dumps([{'text':'回滚不得进入索引'}]),ids[0]))
            raise RuntimeError('rollback')
    except RuntimeError:pass
    assert search('回滚不得进入索引')==0 and search('已更正新证据')==1
    with db.connect(write=True) as conn:conn.execute('UPDATE sources SET active=0 WHERE notice_id=?',(ids[0],))
    assert search('已更正新证据')==0
    with db.connect(write=True) as conn:conn.execute('DELETE FROM notices WHERE id=?',(ids[1],))
    assert search('课程编号-1。')==0


def test_cursor_is_owner_filter_and_revision_bound(env):
    c=account(env);other=account(env,'other');_,ids=seed(env,c,4)
    cursor=c.get('/api/notices/page',params={'limit':2}).json()['next_cursor']
    assert other.get('/api/notices/page',params={'cursor':cursor}).status_code==422
    assert other.get('/api/notices/page',params={'q':'共同第二轮'}).json()['total']==0
    assert c.get('/api/notices/page',params={'cursor':cursor,'q':'共同第二轮'}).status_code==422
    assert c.get('/api/notices/page',params={'cursor':cursor[:-2]+'zz'}).status_code==422
    with env[0].state.db.connect(write=True) as conn:conn.execute('DELETE FROM notices WHERE id=?',(ids[-1],))
    changed=c.get('/api/notices/page',params={'cursor':cursor})
    assert changed.status_code==409 and changed.json()['detail']['code']=='list_changed'


def test_semantic_filters_are_applied_before_pagination_and_cache_invalidates(env):
    c=account(env);_,ids=seed(env,c,61)
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("INSERT INTO notice_dispositions(notice_id,disposition,note,updated_at) VALUES(?,?,?,?)",(ids[-1],'reference','仅保留资料',int(time.time())))
    params={'intent':'read','sort':'priority','limit':10}
    result=c.get('/api/notices/page',params=params)
    assert result.status_code==200,result.text
    assert [row['id'] for row in result.json()['items']]==[ids[-1]]
    with env[0].state.db.connect(write=True) as conn:
        conn.execute("UPDATE notice_dispositions SET disposition='closed' WHERE notice_id=?",(ids[-1],))
    assert c.get('/api/notices/page',params=params).json()['total']==0
    assert c.get('/api/notices/page',params={'intent':'closed'}).json()['total']==1


def test_task_semantics_dates_and_selected_ids_are_owner_scoped(env):
    c=account(env);n=manual(c,notice(c));tid=confirm(c,n,task(n,deadline_confirmed=False))
    result=c.get('/api/tasks/page',params={'status':'unverified','limit':1})
    assert result.status_code==200,result.text
    assert result.json()['total']==1 and result.json()['items'][0]['id']==tid
    assert result.json()['items'][0]['workflow'] and 'attachments' in result.json()['items'][0]
    assert c.get('/api/tasks/page',params={'day':'2027-10-20'}).json()['total']==1
    assert c.get('/api/tasks/page',params={'day':'2027-10-21'}).json()['total']==0
    assert c.get('/api/tasks/page',params={'status':'done'}).json()['total']==0
    assert c.get('/api/tasks/page',params={'ids':tid}).json()['total']==1
    assert c.get('/api/tasks/page',params={'ids':'foreign_id'}).json()['total']==0
    assert c.get('/api/tasks/page',params={'day':'2027-02-30'}).status_code==422


@pytest.mark.parametrize('limit',[0,101,-1])
def test_page_limits_cannot_turn_into_full_reads(env,limit):
    c=account(env)
    assert c.get('/api/notices/page',params={'limit':limit}).status_code==422
    assert c.get('/api/tasks/page',params={'limit':limit}).status_code==422
