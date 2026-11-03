"""Real parser/renderer checks; model calls are captured, never paid here."""
import asyncio
import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject

from app import genui_ai, grounding
from app.ai import AIError, check_evidence, prepare_notice_input
from app.config import Settings
from app.documents import file_source
from app.pdf_visual import PAGE_MARKER, pending_pages, visual_locator, visual_note
from app.visual_evidence import image_sources, register_images, review_content
from test_workflow import env


def scanned_pdf(pages=1, annotation=False):
    pictures=[]
    for page in range(pages):
        picture=Image.new('RGB',(500,700),'white');draw=ImageDraw.Draw(picture)
        draw.text((30,30),f'SYNTHETIC PAGE {page+1}: deadline 2026-11-06 17:00',fill='black')
        pictures.append(picture)
    output=BytesIO();pictures[0].save(output,format='PDF',save_all=True,append_images=pictures[1:],resolution=72)
    for picture in pictures:picture.close()
    if not annotation:return output.getvalue()
    writer=PdfWriter();writer.append(BytesIO(output.getvalue()))
    square=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Square'),
        NameObject('/Rect'):ArrayObject([FloatObject(value)for value in (150,150,200,200)]),
        NameObject('/C'):ArrayObject([FloatObject(value)for value in (1,0,0)]),
        NameObject('/IC'):ArrayObject([FloatObject(value)for value in (1,0,0)])})
    writer.add_annotation(page_number=0,annotation=square)
    amended=BytesIO();writer.write(amended);return amended.getvalue()


def test_scanned_pdf_retains_original_and_renders_the_complete_page_with_annotations():
    raw=scanned_pdf(annotation=True);source=file_source('synthetic-scan.pdf',raw)
    assert source['status']=='review' and source['content']==raw
    assert pending_pages(source)==[1] and all('2026-11-06' not in section['text']for section in source['sections'])
    images=image_sources([source]);assert len(images)==1 and images[0]['id']==source['id']
    assert images[0]['kind']=='jpg' and images[0]['_pdf_page']==1
    with Image.open(BytesIO(images[0]['content'])) as image:
        # This red square is a PDF annotation, absent from the embedded bitmap.
        r,g,b=image.getpixel((int(175*image.width/500),int((700-175)*image.height/700)))
        assert r>180 and g<90 and b<90
    normalized=register_images([source])
    assert normalized[0]['content']==raw and normalized[0]['kind']=='pdf'
    assert not any(PAGE_MARKER.fullmatch(s['locator'])for s in normalized[0]['sections'])
    assert normalized[0]['sections'][-1]=={'locator':visual_locator(1),'text':visual_note(1)}
    assert register_images(normalized)[0]['sections']==normalized[0]['sections']
    check_evidence([{'source_id':source['id'],'locator':visual_locator(1),'quote':visual_note(1)}],normalized)
    with pytest.raises(ValueError,match='引用位置'):
        check_evidence([{'source_id':source['id'],'locator':visual_locator(2),'quote':visual_note(2)}],normalized)


def test_pdf_author_and_independent_reviewer_receive_identical_pages_and_explicit_page_citations(monkeypatch):
    source=file_source('synthetic-two-pages.pdf',scanned_pdf(2));sources=register_images([source])
    result={'answer':'测试文档第2页有演示日期，须对照原PDF核对。[1]',
            'citations':[{'source_id':source['id'],'locator':visual_locator(2),'quote':visual_note(2)}],
            'image_sources':[source['id']],'claims':[{'kind':'fact','text':'第2页有演示日期','citation_indices':[1]}]}
    requests=[]
    async def check(settings,request,*args,**kwargs):
        requests.append(request);return {'supported':True,'issues':[]},{}
    monkeypatch.setattr(grounding,'structured_check',check)
    settings=Settings(data_dir=Path('.'))
    assert asyncio.run(grounding.verify(settings,result,sources,'只看第2页',{}))[0]==[]
    author=genui_ai.payload(settings,sources,[{'role':'user','content':'只看第2页'}],{'_grounding_context':{}},3)
    def pixels(request):return [p['image_url']['url']for p in request['messages'][1]['content']if p['type']=='image_url']
    assert pixels(author)==pixels(requests[0]) and len(pixels(author))==2
    assert all(base64.b64decode(value.split(',',1)[1]).startswith(b'\xff\xd8')for value in pixels(author))
    texts=[p['text']for p in requests[0]['messages'][1]['content']if p['type']=='text']
    assert any('原 PDF 第 2 页' in text for text in texts)
    assert 'content' not in grounding.snapshots(sources)[0]


def test_notice_input_keeps_all_six_pages_and_rejects_insufficient_context_before_a_model_call():
    source=file_source('six-pages.pdf',scanned_pdf(6))
    notice={'source_label':'合成测试','published_at':None,'materials_complete':True}
    normalized,system,text=prepare_notice_input(Settings(data_dir=Path('.')),notice,[source],{})
    assert len([part for part in review_content(text,normalized)if part['type']=='image_url'])==6
    with pytest.raises(AIError,match='预算'):
        prepare_notice_input(Settings(data_dir=Path('.'),ai_context_tokens=4096,ai_output_tokens=1024,notice_input_tokens=3072),notice,[source],{})


def test_pdf_render_cache_is_bound_to_file_bytes_and_page_number(monkeypatch):
    source=file_source('cache-bound.pdf',scanned_pdf())
    first=review_content('第一次核对',[source])
    def forbidden(*args,**kwargs):raise AssertionError('Cached pages must not be rerendered on each model stage')
    monkeypatch.setattr('app.pdf_visual.subprocess.run',forbidden)
    assert review_content('第二次核对',register_images([source]))[1:]==first[1:]


def test_agent_read_source_loads_library_pdf_pages_by_owner_and_keeps_pixels_out_of_history(env,monkeypatch):
    from test_workflow import account
    from test_workspace import conversation
    from test_agent_chat import writer,send,final,complete
    from test_agent_runtime import Script,answer,call
    settings=env[1];settings.agent_enabled=settings.ai_grounding=True;settings.ai_api_key='synthetic-no-network'
    client=account(env);archive=conversation(client)
    uploaded=client.post('/api/conversations/'+archive['id']+'/sources',data={'version':archive['version']},
        files={'files':('synthetic-library.pdf',scanned_pdf(6),'application/pdf')})
    assert uploaded.status_code==200,uploaded.text
    source=uploaded.json()['sources'][0];chat=conversation(client);seen=[];writer(monkeypatch,seen=seen)
    model=Script([answer('',[call('campus_search',{'query':'synthetic-library.pdf','scopes':['library']})]),
                  answer('',[call('read_source',{'source_id':source['id'],'locator':'第 2 页（图像待核对）'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    message=final(send(client,chat,'请从我的资料库读取 synthetic-library.pdf 的第2页原图，不使用本轮附件，不联网，不修改记录。'))
    assert message['status']=='complete',message['error']
    images=[part for m in model.inputs[2][0]if m['role']=='user' and isinstance(m['content'],list)
            for part in m['content']if part.get('type')=='image_url']
    assert len(images)==6
    materials=[s for s in seen[-1]['sources']if s['id']==source['id']]
    assert materials and materials[0]['visual_evidence'] and len(image_sources(materials))==6
    with env[0].state.db.connect() as conn:
        durable='\n'.join(row['body']for row in conn.execute('SELECT body FROM agent_messages'))
    assert 'data:image' not in durable and 'base64,' not in durable


def test_agent_cannot_open_another_accounts_pdf_by_guessing_the_source_id(env,monkeypatch):
    from test_workflow import account
    from test_workspace import conversation
    from test_agent_chat import writer,send,final,complete
    from test_agent_runtime import Script,answer,call
    settings=env[1];settings.agent_enabled=settings.ai_grounding=True;settings.ai_api_key='synthetic-no-network'
    foreign=account(env,'pdf-other-owner');archive=conversation(foreign)
    uploaded=foreign.post('/api/conversations/'+archive['id']+'/sources',data={'version':archive['version']},
        files={'files':('foreign-private.pdf',scanned_pdf(),'application/pdf')}).json()
    client=account(env);chat=conversation(client);writer(monkeypatch)
    model=Script([answer('',[call('read_source',{'source_id':uploaded['sources'][0]['id'],'locator':'第 1 页（图像待核对）'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    message=final(send(client,chat,'只读我的资料库，不联网。'))
    assert message['status']=='complete',message['error']
    assert not any(part.get('type')=='image_url'for messages,_ in model.inputs for m in messages
                   if isinstance(m.get('content'),list)for part in m['content'])


def test_pdf_deleted_while_opening_cannot_be_sent_as_current_pixels(env,monkeypatch):
    from test_workflow import account
    from test_workspace import conversation
    from test_agent_chat import writer,send,complete
    from test_agent_runtime import Script,answer,call
    from app import visual_evidence
    settings=env[1];settings.agent_enabled=settings.ai_grounding=True;settings.ai_api_key='synthetic-no-network'
    client=account(env);archive=conversation(client)
    uploaded=client.post('/api/conversations/'+archive['id']+'/sources',data={'version':archive['version']},
        files={'files':('changing.pdf',scanned_pdf(),'application/pdf')}).json()
    sid=uploaded['sources'][0]['id'];chat=conversation(client);writer(monkeypatch)
    original=visual_evidence.register_images;deleted=[]
    def register(sources):
        if not deleted and any(s.get('id')==sid and s.get('kind')=='pdf' and s.get('content') for s in sources):
            with env[0].state.db.connect(write=True) as conn:conn.execute('DELETE FROM conversation_sources WHERE id=?',(sid,))
            deleted.append(sid)
        return original(sources)
    monkeypatch.setattr(visual_evidence,'register_images',register)
    async def forbidden(*args,**kwargs):raise AssertionError('No real model fallback may run in this test')
    monkeypatch.setattr(grounding,'plan',forbidden);monkeypatch.setattr(grounding,'completion',forbidden)
    model=Script([answer('',[call('campus_search',{'query':'changing.pdf','scopes':['library']})]),
                  answer('',[call('read_source',{'source_id':sid,'locator':'第 1 页（图像待核对）'})]),complete()])
    env[0].state.agent_service.provider_factory=lambda *_:model
    send(client,chat,'从我的资料库读取 changing.pdf，不联网。')
    assert deleted==[sid]
    assert not any(part.get('type')=='image_url'for messages,_ in model.inputs for m in messages
                   if isinstance(m.get('content'),list)for part in m['content'])


def test_notice_pdf_original_preview_keeps_owner_boundary_and_original_bytes(env):
    from test_workflow import account
    client=account(env);raw=scanned_pdf()
    created=client.post('/api/notices',data={'title':'合成PDF原件核验','body':'工程演示，不是真实通知。','source_label':'虚构发布方'},
                        files={'files':('original.pdf',raw,'application/pdf')})
    assert created.status_code==200,created.text
    notice=created.json();source=next(s for s in notice['sources']if s['kind']=='pdf')
    path=f"/api/notices/{notice['id']}/sources/{source['id']}/download"
    preview=client.get(path+'?preview=true')
    assert preview.content==raw and preview.headers['content-type']=='application/pdf'
    assert preview.headers['content-disposition'].startswith('inline')
    assert client.get(path).headers['content-disposition'].startswith('attachment')
    assert account(env,'pdf-preview-other').get(path+'?preview=true').status_code==404


def test_browser_pdf_pages_cover_the_whole_document_and_require_the_owner(env):
    from test_workflow import account
    from test_workspace import conversation
    client=account(env);chat=conversation(client)
    uploaded=client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},
        files={'files':('six-pages.pdf',scanned_pdf(6),'application/pdf')}).json()
    sid=uploaded['sources'][0]['id'];path=f"/api/conversations/{chat['id']}/sources/{sid}"
    result=client.get(path+'/pdf-preview');assert result.status_code==200,result.text
    assert result.json()['page_count']==6 and [p['page']for p in result.json()['pages']]==list(range(1,7))
    last=result.json()['pages'][-1]['url'];image=client.get(last)
    assert image.status_code==200 and image.content.startswith(b'\xff\xd8')
    assert image.headers['content-type']=='image/jpeg' and image.headers['cache-control']=='no-store'
    for page in (0,7,51):assert client.get(path+'/pdf-pages/'+str(page)).status_code==404
    other=account(env,'pdf-page-other')
    assert other.get(path+'/pdf-preview').status_code==404 and other.get(last).status_code==404


def test_pdf_page_preview_does_not_publish_a_source_removed_during_render(env,monkeypatch):
    from test_workflow import account
    from test_workspace import conversation
    from app import pdf_visual
    client=account(env);chat=conversation(client)
    uploaded=client.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},
        files={'files':('removed-during-render.pdf',scanned_pdf(),'application/pdf')}).json()
    sid=uploaded['sources'][0]['id'];original=pdf_visual.render_pages
    def removed(source,**kwargs):
        with env[0].state.db.connect(write=True) as conn:conn.execute('DELETE FROM conversation_sources WHERE id=?',(sid,))
        return original(source,**kwargs)
    monkeypatch.setattr(pdf_visual,'render_pages',removed)
    result=client.get(f"/api/conversations/{chat['id']}/sources/{sid}/pdf-pages/1")
    assert result.status_code==404 and result.headers['content-type'].startswith('application/json')
