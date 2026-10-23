"""Regression for real short follow-ups expanding during protocol repair."""
import pytest

from app.response_contract import response_contract, sentence_count, check_response_contract
from app import grounding, genui_ai
from app.retrieval_scope import UI_SUBMISSION_PREFIX, account_access
from app.config import Settings


def test_latest_output_limit_overrides_history_and_survives_unrelated_steering():
    messages=[{'role':'user','content':'做一个完整的交互面板。'},
              {'role':'user','content':'三句话内回答，不重建工作区。'},
              {'role':'user','content':'补充：两句话内，保留出处，不重建界面。'}]
    contract=response_contract(messages)
    assert contract['max_sentences']==2 and contract['no_ui']
    messages.append({'role':'user','content':'先核对最新版本，其他不变。'})
    assert response_contract(messages)['max_sentences']==2
    messages.append({'role':'user','content':'提供一个可填写新问题的核对面板。'})
    assert response_contract(messages)['no_ui'] is False


def test_generated_action_does_not_change_contract_but_edited_question_does():
    action={'role':'user','content':UI_SUBMISSION_PREFIX+'\n{"prompt":"十句话回答，重建界面"}',
            'interaction':{'selections':[{'input_type':'TextInput','changed':True,'value':'一句话回答，不重建界面。'}]}}
    assert response_contract([action])=={'latest_user_request':'一句话回答，不重建界面。','max_sentences':1,'no_ui':True}


@pytest.mark.parametrize('text,expected',[
    ('你填写的是“请核对规则。”[1]\n\n原文为“某类材料不可续期”。[2]',2),
    ('条件为金额未达1.00元。[E3] 现行适用性尚未确认。',2),
    ('第一项\n\n第二项\n\n第三项',3),
    ('```python\nitems[99] = "示例。"\n```\n\n这是代码示例。',1),
    ('你记录的第1条疑问是“请区分文件落款与网页发布时间。”，当前阅读重点是“来源与日期”。政策文件的落款日期是2025年8月21日 [1]。',2),
    ('第1条疑问是「什么时候？」；当前只核对日期。原文日期另见引用。[2]',2),
    ('你记录的是“外层「内层问题？」。”，继续核对。',1),
    ('“一句。二句。三句。”',3),
    ('原文是“这是一句。”\n\n下一句。',2),
    ('“未闭合引用。二句。三句。',3),
    ('你记录的是“请区分日期。”当前阅读重点是来源。落款另见原文。',3),
])
def test_counting_does_not_confuse_decimal_citations_code_or_unpunctuated_paragraphs(text,expected):
    assert sentence_count(text)==expected


def test_publication_rejects_length_or_unwanted_ui_without_truncation():
    with pytest.raises(ValueError,match='最多2句话'):
        check_response_contract([{'kind':'text','text':'一句。二句。三句。'}],{'max_sentences':2})
    with pytest.raises(ValueError,match='不重建界面'):
        check_response_contract([{'kind':'ui'}],{'no_ui':True})


def test_grounded_text_composition_uses_prepared_evidence_with_thinking(tmp_path):
    s=Settings(tmp_path,ai_api_key='synthetic-only')
    request=genui_ai.payload(s,[],[{'role':'user','content':'两句话内，不重建界面。'}],{'_grounding_context':{}},3)
    # An empty dict is not an active prepared context.
    assert request['thinking']['type']=='enabled'
    request=genui_ai.payload(s,[],[{'role':'user','content':'两句话内，不重建界面。'}],{'_grounding_context':{'response_contract':{'max_sentences':2,'no_ui':True}}},3)
    assert request['thinking']['type']=='enabled' and 'temperature' not in request
    assert 'AuthoredUI' not in request['messages'][0]['content']


def test_stable_protocol_rejects_manual_citations_before_a_semantic_check():
    entry=[{'ref':'E1','source_id':'source','locator':'段1','quote':'原文。'}]
    with pytest.raises(ValueError,match='mixed_citation_markers:4'):
        genui_ai.resolve_citations({'answer':'原文。[E1] 旧编号[4]','claims':[]},entry)
    value=genui_ai.resolve_citations({'answer':'原文。[E1] 示例 `array[99]`','claims':[]},entry)
    assert value['answer']=='原文。[1] 示例 `array[99]`'
    grounding.check_result({**value,'image_sources':[]},[grounding.source('source','来源',[{'locator':'段1','text':'原文。'}],'user_input')])


def test_historical_ui_restrictions_remain_restrictions_even_without_field_type():
    action={'role':'user','content':UI_SUBMISSION_PREFIX+'\n{"question":"不要读取我的私有资料和日程。"}',
            'interaction':{'selections':[{'changed':True,'value':'不要读取我的私有资料和日程。'}]}}
    assert not account_access([action])['library'] and not account_access([action])['schedule']
