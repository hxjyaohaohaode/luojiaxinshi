import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app import ai
from app.visual_evidence import IMAGE_LOCATOR, IMAGE_NOTE
from test_workflow import env, account, notice, task


def png(color='white'):
    out = io.BytesIO()
    Image.new('RGB', (64, 64), color).save(out, format='PNG')
    return out.getvalue()


@pytest.mark.parametrize('review_enabled',[False,True])
def test_image_only_notice_reaches_model_and_keeps_visual_dates_unconfirmed(env, monkeypatch,review_enabled):
    c = account(env); env[1].ai_api_key = 'synthetic-test-key'
    env[1].notice_semantic_review=review_enabled;seen=[]
    image = png()
    n = notice(c, text='', files=[('files', ('notice.png', image, 'image/png'))])
    sid = n['sources'][0]['id']
    evidence = {'source_id': sid, 'locator': IMAGE_LOCATOR, 'quote': IMAGE_NOTE}
    raw = {'title': '虚构图片通知', 'summary': '模拟图片识别', 'applicability': 'needs_review', 'applicability_reason': '需要核实',
           'facts': {k: {'value': '', 'evidence': []} for k in ai.FACT_KEYS},
           'tasks': [task(n, evidence=[evidence], deadline_evidence=[evidence])], 'warnings': []}
    original = httpx.Client
    def provider(request):
        body = json.loads(request.content)
        seen.append(body)
        parts = body['messages'][1]['content']
        encoded = next(p['image_url']['url'] for p in parts if p['type'] == 'image_url')
        assert base64.b64decode(encoded.split(',')[1]) == image
        assert sid in parts[0]['text']
        result=raw
        if len(seen)==2:
            projected=json.loads(parts[0]['text']);ref=projected['sources'][0]['sections'][-1]['ref']
            result={'source_checks':[{'source_index':0,'requirements_summary':'图片观察存在截止日期，请本人核实。','evidence_refs':[ref],'coverage':'covered'}],
                'checked_task_indices':[0],'issues':[]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}], 'usage': {}})
    monkeypatch.setattr(ai.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
    r = c.post('/api/notices/'+n['id']+'/generate', json={'version': n['version'], 'allow_external_processing': True})
    assert r.status_code == 200, r.text
    draft = r.json()['draft'];step = draft['tasks'][0]
    assert len(seen)==(2 if review_enabled else 1)
    assert draft['quality']['status']==('passed' if review_enabled else 'not_run')
    assert step['due_date'] == '2027-10-20' and not step['deadline_confirmed']
    assert any('图片观察' in u for u in step['uncertainties'])
    assert c.get('/api/tasks').json() == []
    assert all('content' not in s for s in r.json()['sources'])
    bad = {**step, 'deadline_confirmed': True}
    assert c.post('/api/notices/'+n['id']+'/confirm', json={'version': r.json()['version'], 'reviewed': True, 'tasks': [bad]}).status_code == 422


def test_all_images_are_counted_no_silent_truncation(env, monkeypatch):
    c = account(env); env[1].ai_api_key = 'synthetic'
    env[1].notice_semantic_review=False
    files = [('files', (f'notice-{i}.png', png(color), 'image/png')) for i, color in enumerate(['white', 'red', 'green', 'blue', 'yellow'])]
    n = notice(c, text='', files=files)
    original=httpx.Client;seen=[]
    def provider(request):
        body=json.loads(request.content);seen.append(body)
        pictures=[p for p in body['messages'][1]['content'] if p['type']=='image_url']
        assert len(pictures)==5
        assert {base64.b64decode(p['image_url']['url'].split(',')[1])for p in pictures}=={png(color)for color in ['white','red','green','blue','yellow']}
        raw={'title':'五张合成图片','summary':'仅用于完整输入验收','applicability':'needs_review','applicability_reason':'需核对实际内容',
             'facts':{k:{'value':'','evidence':[]}for k in ai.FACT_KEYS},'tasks':[],'warnings':[]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw)}}],'usage':{}})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(provider),**kwargs))
    r = c.post('/api/notices/'+n['id']+'/generate', json={'version': n['version'], 'allow_external_processing': True})
    assert r.status_code==200,r.text
    assert len(seen)==1
    # All images count towards the real input budget. Reject before the provider
    # when the budget is too small, rather than silently dropping image five.
    env[1].notice_input_tokens=128
    other=notice(c,text='',files=files)
    blocked=c.post('/api/notices/'+other['id']+'/generate',json={'version':other['version'],'allow_external_processing':True})
    assert blocked.status_code==422 and '预算' in blocked.text and len(seen)==1


def test_images_cannot_fabricate_verbatim_quotes():
    import pytest
    sources = [{'id': 'image1', 'kind': 'png', 'status': 'review', 'sections': []}]
    with pytest.raises(ValueError):
        ai.check_evidence([{'source_id': 'image1', 'locator': IMAGE_LOCATOR, 'quote': '2030年10月20日截止'}], sources)
