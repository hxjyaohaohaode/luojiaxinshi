"""Recruitment and presentations retain their real scope and source details."""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app import source_sync, whu_careers
from app.official_sources import get_preset


JOB_ID = 'fef494926e184598999bbcf67c3ec3fd'
FAIR_ID = 'ab3adf7cd5334c3dbc013181f1c75507'
JOB_URL = 'https://xsjy.whu.edu.cn/f/recruitmentinfo/show?recruitmentId=' + JOB_ID
FAIR_URL = 'https://xsjy.whu.edu.cn/f/recruitmentFair/show?recruitmentFairId=' + FAIR_ID


def job_row(**changes):
    return {'id': JOB_ID, 'title': '测试单位校园招聘', 'url': '/f/recruitmentinfo/show?recruitmentId='+JOB_ID,
            'positionType': '1', 'isFrontShow': '1', 'startTime': '2026-11-14 10:04:29', **changes}


def fair_row(**changes):
    return {'id': FAIR_ID, 'title': '测试单位宣讲会', 'url': '/f/recruitmentFair/show?recruitmentFairId='+FAIR_ID,
            'startTime': '2026-11-16 14:30:00', 'endTime': '2026-11-16 17:00:00', 'isExpired': '0', **changes}


def fetch(preset_id):
    preset = get_preset(preset_id)
    config = {'mode': 'html', 'url': preset['url'], 'preset_id': preset_id,
              'article_path_prefix': preset['article_path_prefix']}
    return asyncio.run(source_sync.fetch_index(config))


def test_recruitment_reads_original_announcement_and_structured_positions(monkeypatch):
    calls = []
    detail = {'url': '/f/recruitmentinfo/show?recruitmentId='+JOB_ID, 'title': '测试单位校园招聘',
              'isFrontShow': '1', 'positionType': '1', 'corporationName': '测试单位',
              'startTime': '2026-11-14 10:04:29', 'endTime': '2027-01-31 00:00:00',
              'content': '<p>招聘说明，请核对原文。</p>', 'fileURL': '/files/报名表.docx',
              'recruitmentPositionList': [{'positionName': '软件工程师', 'studentType': '本科,硕士',
                  'demandNumber': '3', 'majorName': '计算机科学', 'cityName': '武汉市',
                  'salaryMonth': '8000-10000', 'positionDescription': '<p>负责软件研发。</p>'}]}
    def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith('/recruitmentinfoList.html'):
            return httpx.Response(200, text='<html>招聘信息</html>')
        assert request.headers.get('cache-control') == 'no-store' and 'cookie' not in request.headers
        if request.url.path.endswith('/ajax_frontRecruitinfo'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'count': 2, 'list': [
                job_row(), job_row(id='wrong', url='https://other.example/private')]}})
        if request.url.path.endswith('/ajax_show'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'recruitmentinfo': detail}})
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(whu_careers, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    entries = fetch('whu-employment-jobs')
    assert list(entries) == [{'url': JOB_URL, 'title': '测试单位校园招聘', 'published_at': None}]
    assert len(entries.rejected) == 1
    source, title = asyncio.run(whu_careers.read_career_article(JOB_URL))
    text = '\n'.join(section['text'] for section in source['sections'])
    assert title == '测试单位校园招聘' and '职位：软件工程师' in text and '工作地点：武汉市' in text
    assert '学历：本科,硕士' in text and '月薪：8000-10000' in text and '负责软件研发' in text
    assert source['origin']['published_at'] is None  # The site's label is only “日期”.
    assert source['origin']['source_display_date'] == '2026-11-14 10:04:29'
    assert len(source['origin']['attachments']) == 1 and '报名表.docx' in source['origin']['attachments'][0]
    assert not any('other.example' in url for url in calls)


def test_presentations_keep_event_time_location_separate_from_publication_date(monkeypatch):
    detail = {'id': FAIR_ID, 'url': '/f/recruitmentFair/show?recruitmentFairId='+FAIR_ID,
              'title': '测试单位宣讲会', 'isFrontShow': '1', 'corporationName': '测试单位',
              'startTime': '2026-11-16 14:30:00', 'endTime': '2026-11-16 17:00:00',
              'fieldExport': '就业中心自强厅（301）', 'updateDate': '2026-11-05 11:18:56',
              'content': '<p>欢迎现场参加。</p>', 'recruitmentFairPositionList': []}
    def handler(request):
        if request.url.path.endswith('/recruitmentFairList.html'):
            return httpx.Response(200, text='<html>宣讲会</html>')
        if request.url.path.endswith('/ajax_frontRecruitfair'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'count': 2, 'list': [
                fair_row(), fair_row(id='b'*32, url='/f/recruitmentFair/show?recruitmentFairId='+'b'*32, isExpired='1')]}})
        if request.url.path.endswith('/ajax_show'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'recruitmentFair': detail}})
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(whu_careers, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    entries = fetch('whu-employment-fairs')
    assert len(entries) == 1 and entries[0]['url'] == FAIR_URL and entries[0]['published_at'] is None
    assert entries.snapshot['ended_events_skipped'] == 1
    source, _ = asyncio.run(whu_careers.read_career_article(FAIR_URL))
    origin = source['origin']
    assert origin['published_at'] == '2026-11-05'
    assert origin['event_start'] == '2026-11-16 14:30:00' and origin['event_end'] == '2026-11-16 17:00:00'
    assert origin['event_location'] == '就业中心自强厅（301）'
    text = '\n'.join(section['text'] for section in source['sections'])
    assert '举办开始时间：2026-11-16 14:30:00' in text and '举办地点：就业中心自强厅（301）' in text


def test_empty_fair_listing_is_valid_and_wrong_scope_or_oversize_stays_explicit(monkeypatch):
    assert whu_careers.career_identity(JOB_URL+'&next=') is None
    assert whu_careers.career_identity(JOB_URL.replace('xsjy.whu.edu.cn', 'other.example')) is None
    assert whu_careers.career_identity('https://xsjy.whu.edu.cn/frontpage/whu/html/recruitmentinfoForm.html?positionDetailId='+JOB_ID) == ('job', JOB_ID)
    assert whu_careers.career_identity('https://xsjy.whu.edu.cn/frontpage/whu/html/recruitmentFairForm.html?id='+FAIR_ID) == ('fair', FAIR_ID)
    def handler(request):
        if request.url.path.endswith('/recruitmentFairList.html'):
            return httpx.Response(200, text='<html>宣讲会</html>')
        if request.url.path.endswith('/ajax_frontRecruitfair'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'count': 0, 'list': []}})
        if request.url.path.endswith('/ajax_show'):
            return httpx.Response(200, json={'state': 1, 'jessionid': '', 'object': {'recruitmentinfo': {
                'url': '/f/recruitmentinfo/show?recruitmentId='+JOB_ID, 'title': '大型招聘',
                'isFrontShow': '1', 'content': '<p>'+'长'*11000+'</p>', 'recruitmentPositionList': []}}})
        raise AssertionError('Unexpected request')
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(whu_careers, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    entries = fetch('whu-employment-fairs')
    assert entries == [] and entries.empty_confirmed
    source, _ = asyncio.run(whu_careers.read_career_article(JOB_URL))
    assert source['status'] == 'review' and any('未完整接收' in warning for warning in source['origin']['warnings'])


def test_wrong_position_type_is_rejected(monkeypatch):
    def handler(request):
        if request.url.path.endswith('/recruitmentinfoList.html'):
            return httpx.Response(200, text='<html>实习信息</html>')
        return httpx.Response(200, json={'state': 1, 'jessionid': '',
            'object': {'count': 1, 'list': [job_row(positionType='1')]}})
    monkeypatch.setattr(source_sync, 'PublicHTTPTransport', lambda: httpx.MockTransport(handler))
    entries = fetch('whu-employment-internships')
    assert not entries and not entries.empty_confirmed and len(entries.rejected) == 1
