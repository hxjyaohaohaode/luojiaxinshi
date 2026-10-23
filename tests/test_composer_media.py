"""Real multipart, SQLite and media transport boundaries; synthetic content only."""
from concurrent.futures import ThreadPoolExecutor
import base64
import json
import pytest

from app import grounding
from app.ai import AIError
from app.media_input import inspect_media,input_budget
from app.material_files import library_file
from app.visual_evidence import register_images,review_content
from test_workflow import env,account
from test_workspace import conversation,send as ordinary_send
from test_agent_chat import enabled,send,final
from test_agent_authoring import forbid_writer,draft
from test_agent_runtime import Script
from media_fixtures import png,wav,mp4

def test_requested_image_markdown_and_word_formats_with_chinese_names(env):
    import io,zipfile
    from PIL import Image
    client=account(env);chat=conversation(client)
    jpeg=io.BytesIO();Image.open(io.BytesIO(png())).save(jpeg,format='JPEG')
    word=io.BytesIO()
    with zipfile.ZipFile(word,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>请准备报名表</w:t></w:r></w:p></w:body></w:document>')
    files=[('截图（第一版）.PNG',png()),('照片 2.JPG',jpeg.getvalue()),('准备事项.md','# 准备事项\n请准备报名表'.encode()),('课程通知（新）.docx',word.getvalue())]
    for name,raw in files:
        response=upload(client,chat,name,raw)
        assert response.status_code==200,response.text
        chat=response.json();source=next(s for s in chat['sources'] if s['name']==name)
        assert source['status']!='failed',(name,source['warning'])
        if name.endswith(('.md','.docx')):assert any('报名表' in s['text'] for s in source['sections'])
    assert len(chat['sources'])==4

def upload(client,chat,name,data):
    return client.post('/api/conversations/'+chat['id']+'/sources',
        data={'version':chat['version'],'append_only':'true'},files={'files':(name,data)})

def test_parallel_uploads_keep_all_items_and_retry_is_idempotent(env):
    client=account(env);chat=conversation(client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        replies=list(pool.map(lambda i:upload(client,chat,f'材料{i}.txt',f'内容{i}'.encode()),range(9)))
    assert all(r.status_code==200 for r in replies), [(r.status_code,r.text[:300]) for r in replies if r.status_code!=200]
    ids=[r.json()['uploaded_source_ids'][0] for r in replies]
    assert len(set(ids))==9
    actual=client.get('/api/conversations/'+chat['id']).json()
    assert len(actual['sources'])==9
    again=upload(client,chat,'材料0.txt','内容0'.encode()).json()
    assert again['uploaded_source_ids']==[ids[0]] and again['added_count']==0
    assert client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version'],'body':'旧版本'}).status_code==409
    other=account(env,'other')
    assert upload(other,chat,'别人的.txt',b'x').status_code==404

def test_message_attachments_survive_reload_and_reject_foreign_sources(env,monkeypatch):
    client=account(env);chat=conversation(client);forbid_writer(monkeypatch)
    env[0].state.agent_service.provider_factory=lambda *_:Script([draft('已收到。')])
    chat=upload(client,chat,'附件.txt',b'example').json();sid=chat['uploaded_source_ids'][0]
    packets=send(client,chat,'核对附件',source_ids=[sid])
    assert final(packets)['status']=='complete'
    actual=client.get('/api/conversations/'+chat['id']).json()
    assert actual['messages'][0]['attachments'][0]['id']==sid
    assert actual['messages'][-1]['attachments']==[]
    other=upload(client,conversation(client),'other.txt',b'other').json()
    response=client.post('/api/conversations/'+chat['id']+'/messages',
        json={'version':actual['version'],'content':'bad','request_id':'wrong-source','source_ids':[other['sources'][0]['id']],'allow_external_processing':True})
    assert response.status_code in (404,422),response.text
    assert len(client.get('/api/conversations/'+chat['id']).json()['messages'])==2
    branched=client.post('/api/conversations/'+chat['id']+'/messages/'+actual['messages'][-1]['id']+'/branch',
        json={'version':actual['version'],'request_id':'attachment-branch-test'}).json()
    copy=branched['messages'][0]['attachments'][0]
    assert copy['id']!=sid and copy['id']==branched['sources'][0]['id']
    assert copy['name']=='附件.txt'


def test_long_document_does_not_evict_required_media_metadata(env):
    from app.conversation_tools import model_sources
    text={'id':'long-text','sections':[{'locator':'正文','text':'要求'*10000}]}
    media=library_file('clip.mp4',mp4())
    with env[0].state.db.connect() as conn:
        sources=model_sources(conn,[text,media],'要求')
    assert any(p['locator']=='媒体信息' for p in sources[1]['sections'])
    assert input_budget(sources,32768)['media']==1

def test_six_images_reach_agent_and_reviewer_without_extra_writer_or_durable_base64(env,monkeypatch):
    client=account(env);chat=conversation(client);forbid_writer(monkeypatch);originals=[]
    for index in range(6):
        originals.append(png(index));chat=upload(client,chat,f'图片{index}.png',originals[-1]).json()
    reviewed=[]
    async def review(settings,result,sources,*args):
        reviewed.extend(review_content('',sources))
        return [],{},grounding.check_result(result,sources)
    monkeypatch.setattr(grounding,'verify',review)
    model=Script([draft('已检查这批工程图片。',image_sources=[s['id'] for s in chat['sources']])])
    env[0].state.agent_service.provider_factory=lambda *_:model
    result=final(send(client,chat,'仅检查这些图片，不联网'))
    assert result['status']=='complete',result['error']
    images=[p['image_url']['url'] for m in model.inputs[0][0] if isinstance(m['content'],list) for p in m['content'] if p['type']=='image_url']
    reviewed_images=[p['image_url']['url'] for p in reviewed if p['type']=='image_url']
    assert len(images)==6 and images==reviewed_images
    assert {base64.b64decode(url.split(',')[1]) for url in images}==set(originals)
    with env[0].state.db.connect() as conn:
        assert not any('data:image' in row[0] for row in conn.execute('SELECT body FROM agent_messages'))
    assert result['grounding']['agent_execution']['answer_in_loop']

@pytest.mark.parametrize('kind,create',[('wav',wav),('mp4',mp4)])
def test_real_media_is_inspected_and_native_bytes_are_preserved(kind,create):
    raw=create();source=library_file('工程.'+kind,raw)
    assert source['status']!='failed',source['warning']
    assert json.loads(source['sections'][0]['text'])['seconds']>0
    source=register_images([source])[0]
    parts=review_content('核对', [source]);part=parts[-1]
    url=part['input_audio']['data'] if kind=='wav' else part['video_url']['url']
    assert base64.b64decode(url.split(',')[1])==raw
    assert input_budget([source],32768)['media']==1
    with pytest.raises(AIError,match='超过'):input_budget([source],100)

def test_corrupt_media_cannot_be_claimed_as_read():
    with pytest.raises(ValueError):inspect_media(b'RIFF'+b'fake'*20,'wav')
    source=library_file('坏视频.mp4',b'0000ftyp'+b'fake'*20)
    assert source['status']=='failed'
    assert review_content('未读取',[source])=='未读取'

def test_image_review_always_enables_thinking(env):
    source=register_images([library_file('image.png',png())])[0]
    result={'answer':'工程样例','claims':[],'image_sources':[source['id']]}
    assert grounding.review_options(env[1],result,[source])['thinking']['type']=='enabled'
    result['claims']=[{'kind':'inference','text':'音频没有语音内容，无法从中提取任务要求。'}]
    assert grounding.review_options(env[1],result,[source])['thinking']['type']=='enabled'
    result['claims']=[{'kind':'inference','text':'假设截止为明年，计算剩余时间。'}]
    assert grounding.review_options(env[1],result,[source])['thinking']['type']=='enabled'
