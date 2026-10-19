"""A valid quote must support the same date/time pair, including day boundaries."""
import pytest

from app.ai import FACT_KEYS,validate_extraction
from app.documents import text_source


def extract(quotes,day,clock,published=None):
    sources=[text_source(q) for q in quotes]
    evidence=[{'source_id':s['id'],'locator':s['sections'][0]['locator'],'quote':s['sections'][0]['text']} for s in sources]
    raw={'title':'期限边界测试','summary':'明确校验日期与时刻','applicability':'needs_review','applicability_reason':'本人核对',
         'facts':{k:{} for k in FACT_KEYS},'tasks':[{'title':'提交申请','due_date':day,'due_time':clock,'deadline_text':quotes[0],
             'evidence':evidence,'deadline_evidence':evidence}],'warnings':[]}
    return validate_extraction(raw,sources,published)['tasks'][0]


@pytest.mark.parametrize('original,normalized',[
    ('2026-10-19','2026-10-20'),('2026-12-31','2027-01-01'),
    ('2028-02-28','2028-02-29'),('2027-02-28','2027-03-01'),
])
def test_explicit_24_hour_cutoff_keeps_next_day_midnight(original,normalized):
    t=extract([f'请于{original} 24:00前提交申请。'],normalized,'00:00')
    assert (t['due_date'],t['due_time'])==(normalized,'00:00')
    assert not t['deadline_confirmed']


def test_provider_24_hour_representation_is_normalized_only_when_evidenced():
    t=extract(['请于2026年10月19日24:00前提交。'],'2026-10-19','24:00')
    assert (t['due_date'],t['due_time'])==('2026-10-20','00:00')


@pytest.mark.parametrize('quotes',[
    ['2026年10月20日17:00前提交，2026年10月21日12:00由学院审核。'],
    ['2026年10月20日17:00前提交。','2026年10月21日12:00由学院审核。'],
    ['2026年10月20日提交，10月21日12:00由学院审核。'],
])
def test_clock_from_another_date_cannot_complete_the_selected_deadline(quotes):
    assert extract(quotes,'2026-10-20','12:00')['due_time'] is None


def test_relative_date_uses_publication_day_in_shanghai():
    t=extract(['请于明天17:00前提交。'],'2026-10-04','17:00','2026-10-02T17:30:00Z')
    assert (t['due_date'],t['due_time'])==('2026-10-04','17:00')
    assert extract(['请于明天17:00前提交。'],'2026-10-03','17:00','2026-10-02T17:30:00Z')['due_date'] is None


@pytest.mark.parametrize('word,day',[('收到材料次日','2026-10-03'),('缴费当天','2026-10-02'),('审批通过的次日','2026-10-03')])
def test_unknown_event_anchor_cannot_be_replaced_with_publication(word,day):
    t=extract([f'请于{word}提交申请。'],day,None,'2026-10-02T17:30:00+08:00')
    assert t['due_date'] is None


def test_afternoon_hour_cannot_be_mistaken_for_early_morning():
    assert extract(['2026年10月20日下午2:30截止。'],'2026-10-20','02:30')['due_time'] is None
    assert extract(['2026年10月20日下午2:30截止。'],'2026-10-20','14:30')['due_time']=='14:30'


def test_date_without_clock_still_does_not_invent_end_of_day():
    t=extract(['2026年10月20日截止。'],'2026-10-20','23:59')
    assert t['due_date']=='2026-10-20' and t['due_time'] is None


def test_unknown_year_is_not_inferred_from_publication():
    assert extract(['10月20日17:00截止。'],'2026-10-20','17:00','2026-10-02T17:30:00+08:00')['due_date'] is None


def test_midnight_is_not_moved_to_the_wrong_day():
    t=extract(['请于2026年10月19日24:00前提交。'],'2026-10-19','00:00')
    assert t['due_time'] is None
    t=extract(['请于2026年10月20日00:00前提交。'],'2026-10-20','00:00')
    assert (t['due_date'],t['due_time'])==('2026-10-20','00:00')


def test_unproven_24_hour_notation_is_rejected():
    with pytest.raises(ValueError):extract(['请于2026年10月19日17:00前提交。'],'2026-10-19','24:00')


def test_omitted_date_or_clock_remains_unknown_but_is_explicitly_flagged():
    task=extract(['本人请于2026年10月19日24:00前提交。'],None,None)
    assert task['due_date'] is None and task['due_time'] is None and not task['deadline_confirmed']
    assert any('未填写对应截止日期' in text for text in task['uncertainties'])
    task=extract(['本人请于2026年10月19日17:00前提交。'],'2026-10-19',None)
    assert task['due_time'] is None and any('未填写截止时刻' in text for text in task['uncertainties'])


@pytest.mark.parametrize('published',[None,'2026-10-02T13:38:00'])
def test_relative_date_needs_timezone_aware_publication(published):
    assert extract(['明天17:00前提交。'],'2026-10-03','17:00',published)['due_date'] is None
