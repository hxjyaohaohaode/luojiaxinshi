"""Protocol regressions; the separate live acceptance uses real MiMo vision."""
import asyncio
import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from app import grounding, genui_ai
from app.config import Settings
from app.visual_evidence import IMAGE_LOCATOR, IMAGE_NOTE, register_images, review_content, display_citations
from test_workflow import env, account
from test_workspace import conversation


def image():
    buf = io.BytesIO()
    Image.new('RGB', (16, 12), 'red').save(buf, format='PNG')
    return {'id': 'photo', 'name': 'untrusted-file-name.png', 'kind': 'png', 'content': buf.getvalue(),
            'status': 'image', 'warning': '', 'sections': []}


def answer():
    return {'answer': '图中有红色区域，属于图片观察，需对照原图。[1]',
            'citations': [{'source_id': 'photo', 'locator': IMAGE_LOCATOR, 'quote': IMAGE_NOTE}],
            'image_sources': ['photo'], 'claims': [{'kind': 'fact', 'text': '图中有红色区域。', 'citation_indices': [1]}]}


def test_coverage_and_independent_review_receive_the_same_original_pixels(monkeypatch):
    sources = register_images([image()]); requests = []
    async def check(settings, request, schema, label, validate=None):
        requests.append(request)
        return ({'supported': True, 'issues': []} if label == '独立核验' else {'items': []}), {}
    monkeypatch.setattr(grounding, 'structured_check', check)
    settings = Settings(data_dir=Path('.'), ai_model='mimo-v2.6-pro')
    asyncio.run(grounding.assess_coverage(settings, '只描述原图', sources, {}))
    assert asyncio.run(grounding.verify(settings, answer(), sources, '只描述原图', {}))[0] == []
    for request in requests:
        content = request['messages'][1]['content']
        pixels = next(p['image_url']['url'] for p in content if p['type'] == 'image_url')
        assert base64.b64decode(pixels.split(',', 1)[1]) == image()['content']
        assert '不是图片文字或 OCR 原文' in content[0]['text']
        assert '不得依据文件名' in request['messages'][0]['content']
    authored = genui_ai.payload(settings, sources, [{'role':'user','content':'原图'}], {'_grounding_context': {'coverage_check': {}}}, 3)
    assert next(p['image_url']['url'] for p in authored['messages'][1]['content'] if p['type']=='image_url') == pixels
    assert 'content' not in grounding.snapshots(sources)[0]


def test_image_identity_reference_is_not_an_ocr_quote_and_cannot_survive_without_pixels():
    sources = register_images([image()])
    assert register_images(sources)[0]['sections'] == sources[0]['sections']
    assert genui_ai.evidence_index(sources)[0]['quote'] == IMAGE_NOTE
    assert display_citations(answer()) == answer()['citations']
    for damaged in ({**sources[0], 'content': None}, {**sources[0], 'status': 'failed'}):
        with pytest.raises(ValueError, match='原图'):
            grounding.check_result(answer(), [damaged])
    value = answer(); value['image_sources'] = []
    with pytest.raises(ValueError, match='image_sources'):
        grounding.check_result(value, sources)


def test_only_explicitly_attached_images_enter_the_limited_message_scope(env):
    client = account(env); chat = conversation(client); uid = client.get('/api/session').json()['user']['id']
    messages = [{'role': 'user', 'content': '只用本条消息和上传的图片，不检索资料库或日程。'}]
    sources, report = grounding.retrieve(env[0].state.db, uid, chat['id'], [image()], messages, {}, ['图片'])
    assert any(s['id'] == 'photo' and s['content'] == image()['content'] and s['visual_evidence'] for s in sources)
    assert report['local_scope'] == 'message'
    assert all(report['scanned'][key] == 0 for key in ('tasks', 'arrangements', 'notices'))
    forbidden = [{'role':'user','content':'只用官网，不读取任何附件或上传材料。'}]
    selected, _ = grounding.retrieve(env[0].state.db, uid, chat['id'], [image()], forbidden, {}, ['图片'])
    assert not any(s['id'] == 'photo' for s in selected)


def test_failed_or_unavailable_image_is_never_sent_to_a_reviewer():
    for record in ({**image(), 'content': None}, {**image(), 'status': 'failed'}):
        assert review_content('no pixels', [record]) == 'no pixels'
        assert not register_images([record])[0].get('visual_evidence')
