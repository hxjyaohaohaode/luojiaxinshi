"""Acceptance cases for material folders and real reply revision semantics."""
import io
import json
import uuid
import zipfile
from PIL import Image
from fastapi.testclient import TestClient
from app import chat_ai,genui_ai
from app.ai import AIError
from test_workflow import env,account,ORIGIN
from test_workspace import conversation,material,send

def upload(c,chat,name,body,path=None):
    data={'version':chat['version']}
    if path:data['paths']=json.dumps([path])
    response=c.post(f"/api/conversations/{chat['id']}/sources",data=data,files={'files':(name,body)})
    assert response.status_code==200,response.text
    return response.json()

def search(c,**fields):
    response=c.post('/api/workspace-search',data=fields);assert response.status_code==200,response.text;return response.json()

def test_folder_paths_full_preview_and_late_text_retrieval(env,monkeypatch):
    c=account(env);chat=conversation(c);body=('普通段落。\n'*2500)+'最后一页含唯一关键词：植物地理研讨。'
    chat=upload(c,chat,'requirements.txt',body.encode(),'2026秋季/学院/requirements.txt');source=chat['sources'][0]
    assert source['path']=='2026秋季/学院/requirements.txt';assert source['full_chars']>10000
    result=search(c,scope='materials',conversation_id=chat['id'],query='植物地理研讨');assert [s['id'] for s in result['items']]==[source['id']]
    preview=c.get(f"/api/conversations/{chat['id']}/sources/{source['id']}/preview?q=植物地理研讨").json();assert '植物地理研讨' in preview['sections'][0]['text']
    env[1].ai_api_key='fixture';seen=[]
    def reply(settings,sources,messages,profile):
        seen.extend(sources);return {'answer':'夹具回复','citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',reply);send(c,chat,'植物地理研讨有什么要求？')
    assert any('植物地理研讨' in s['text'] for source in seen for s in source['sections'])
    assert sum(len(s['text']) for source in seen for s in source['sections'])<=10000
    assert c.get(f"/api/conversations/{chat['id']}/sources/{source['id']}/download").content==body.encode()

def test_zip_hierarchy_duplicate_names_and_path_traversal_are_atomic(env):
    c=account(env);chat=conversation(c);archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('甲/通知.txt','报名申请');z.writestr('乙/通知.txt','报名申请')
    chat=upload(c,chat,'开学.zip',archive.getvalue());assert len(chat['sources'])==2
    assert {s['path'] for s in chat['sources']}=={'开学/甲/通知.txt','开学/乙/通知.txt'}
    bad=io.BytesIO()
    with zipfile.ZipFile(bad,'w') as z:z.writestr('../outside.txt','not extracted')
    response=c.post(f"/api/conversations/{chat['id']}/sources",data={'version':chat['version']},files={'files':('bad.zip',bad.getvalue())});assert response.status_code==422
    assert len(c.get('/api/conversations/'+chat['id']).json()['sources'])==2
    duplicate=upload(c,chat,'开学.zip',archive.getvalue());assert duplicate['added_count']==0;assert duplicate['duplicate_count']==2

def test_presentation_and_html_are_read_as_data_not_executed(env):
    c=account(env);chat=conversation(c);archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('ppt/slides/slide1.xml','<slide xmlns:a="urn:text"><a:t>演示材料关键要求</a:t></slide>')
        z.writestr('ppt/slides/slide2.xml','<slide xmlns:a="urn:text"><a:t>第二页报名表</a:t></slide>')
    chat=upload(c,chat,'说明.pptx',archive.getvalue());assert len(chat['sources'][0]['sections'])==2
    chat=upload(c,chat,'来源.html',b'<p>Visible requirement</p><script>malicious()</script>')
    assert 'malicious' not in chat['sources'][-1]['sections'][0]['text']
    response=c.get(f"/api/conversations/{chat['id']}/sources/{chat['sources'][-1]['id']}/download?preview=true");assert 'attachment' in response.headers['content-disposition'];assert response.headers['x-frame-options']=='DENY'

def test_history_reference_queries_and_owner_boundaries(env):
    c=account(env);other=account(env,'other');chat=material(c,conversation(c),'材料独有名称：土壤分析报名。');chat,_=send(c,chat,'一个普通的标题')
    found=search(c,scope='history',query='土壤分析');assert [x['id'] for x in found['items']]==[chat['id']]
    response=c.post('/api/workspace-search',data={'scope':'history'},files={'file':('query.md','土壤分析'.encode())});assert response.status_code==200;assert response.json()['items'][0]['id']==chat['id']
    assert not search(other,scope='history',query='土壤分析')['items']
    assert other.post('/api/workspace-search',data={'scope':'materials','conversation_id':chat['id']}).status_code==404
    assert other.get(f"/api/conversations/{chat['id']}/sources/{chat['sources'][0]['id']}/preview").status_code==404

def test_visual_keyword_search_uses_real_adapter_and_is_ephemeral(env,monkeypatch):
    c=account(env);chat=material(c,conversation(c),'地学实验申请。');env[1].ai_api_key='fixture';seen=[]
    def reply(settings,sources,messages,profile):seen.append(sources);return {'answer':'地学 实验','citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',reply);image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
    response=c.post('/api/workspace-search',data={'scope':'materials','conversation_id':chat['id']},files={'file':('query.png',image.getvalue())});assert response.status_code==200,response.text
    assert '视觉' in response.json()['method'];assert response.json()['items'][0]['id']==chat['sources'][0]['id'];assert seen[0][0]['content']==image.getvalue()
    assert len(c.get('/api/conversations/'+chat['id']).json()['sources'])==1

def test_reference_limits_and_ownership_are_checked_before_model_call(env,monkeypatch):
    c=account(env);other=account(env,'outsider');chat=conversation(c);env[1].ai_api_key='fixture';calls=[]
    monkeypatch.setattr(chat_ai,'reply',lambda *args:calls.append(args))
    image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
    response=other.post('/api/workspace-search',data={'scope':'materials','conversation_id':chat['id']},files={'file':('query.png',image.getvalue())})
    assert response.status_code==404;assert not calls
    response=c.post('/api/workspace-search',data={'scope':'history'},files={'file':('large.txt',b'a'*(5*1024*1024+1))})
    assert response.status_code==413;assert not calls

def test_full_material_cannot_silently_promote_a_truncated_excerpt(env):
    c=account(env);chat=upload(c,conversation(c),'通知全文.txt',('正文内容。\n'*2200).encode())
    response=c.post(f"/api/conversations/{chat['id']}/promote",json={'version':chat['version'],'title':'完整通知','source_ids':[chat['sources'][0]['id']]})
    assert response.status_code==413;assert '截取' in response.text

def test_all_document_images_and_tiff_pages_remain_accessible(env):
    c=account(env);chat=conversation(c);image=io.BytesIO();Image.new('RGB',(8,8),'green').save(image,format='PNG');archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('ppt/slides/slide1.xml','<slide xmlns:a="urn:text"><a:t>图文材料</a:t></slide>')
        for i in range(61):z.writestr(f'ppt/media/image{i}.png',image.getvalue())
    chat=upload(c,chat,'多图说明.pptx',archive.getvalue());sid=chat['sources'][-1]['id'];base=f"/api/conversations/{chat['id']}/sources/{sid}"
    page=c.get(base+'/preview?page=4').json();assert page['resource_count']==61;assert page['pages']==4;assert len(page['resources'])==1
    assert c.get(page['resources'][0]['url']).content==image.getvalue()
    tiff=io.BytesIO();Image.new('RGB',(8,8),'red').save(tiff,format='TIFF',save_all=True,append_images=[Image.new('RGB',(8,8),'blue')])
    chat=upload(c,chat,'两页.tiff',tiff.getvalue());base=f"/api/conversations/{chat['id']}/sources/{chat['sources'][-1]['id']}"
    assert c.get(base+'/preview').json()['frames']==2
    page=c.get(base+'/download?preview=true&frame=1');assert page.status_code==200
    assert Image.open(io.BytesIO(page.content)).getpixel((0,0))[:3]==(0,0,255)
    assert c.get(base+'/download?preview=true&frame=2').status_code==422

def test_regeneration_excludes_all_previous_versions_and_later_turns(env,monkeypatch):
    c=account(env);chat=conversation(c);env[1].ai_api_key='fixture';contexts=[]
    def reply(settings,sources,messages,profile):contexts.append([m['content'] for m in messages]);return {'answer':'version-'+str(len(contexts)),'citations':[],'image_sources':[]},{}
    monkeypatch.setattr(chat_ai,'reply',reply);chat,_=send(c,chat,'原始问题');old=chat['messages'][-1]['id'];chat,_=send(c,chat,'后续问题')
    chat,_=send(c,chat,'',regenerate_message_id=old);assert contexts[-1]==['原始问题']
    first=chat['messages'][1];assert first['content']=='version-3';assert len(first['versions'])==2
    assert [m['role'] for m in chat['messages']]==['user','assistant','user','assistant']
    chat,_=send(c,chat,'',regenerate_message_id=first['id']);assert contexts[-1]==['原始问题'];assert len(chat['messages'][1]['versions'])==3
    select=c.post(f"/api/conversations/{chat['id']}/messages/{old}/select",json={'version':chat['version']});assert select.status_code==200
    chat=select.json();chat,_=send(c,chat,'新的追问');assert contexts[-1]==['原始问题','version-1','后续问题','version-2','新的追问']

def test_stream_revision_failure_preserves_completed_version(env,monkeypatch):
    c=account(env);chat=conversation(c);env[1].ai_api_key='fixture'
    monkeypatch.setattr(chat_ai,'reply',lambda *args:({'answer':'旧答案必须排除','citations':[],'image_sources':[]},{}));chat,_=send(c,chat,'原始问题');old=chat['messages'][-1]['id'];seen=[]
    async def stream(settings,sources,messages,profile,tier):
        seen.extend(m['content'] for m in messages);yield {'type':'delta','text':'部分新回答'};raise AIError('工程失败夹具')
    monkeypatch.setattr(genui_ai,'stream_reply',stream)
    response=c.post(f"/api/conversations/{chat['id']}/messages/stream",json={'version':chat['version'],'content':'','regenerate_message_id':old,'request_id':uuid.uuid4().hex,'allow_external_processing':True});assert response.status_code==200
    assert seen==['原始问题'];restored=c.get('/api/conversations/'+chat['id']).json();assert restored['messages'][-1]['id']==old;assert restored['messages'][-1]['versions'][-1]['status']=='failed'

def test_reactions_branch_and_revocable_snapshot_share(env,monkeypatch):
    c=account(env);other=account(env,'bob');chat=material(c,conversation(c));env[1].ai_api_key='fixture'
    monkeypatch.setattr(chat_ai,'reply',lambda *args:({'answer':'**保存的回答**','citations':[],'image_sources':[]},{}));chat,_=send(c,chat);mid=chat['messages'][-1]['id'];path=f"/api/conversations/{chat['id']}/messages/{mid}"
    assert c.post(path+'/reaction',json={'value':1}).json()['value']==1
    assert c.get('/api/conversations/'+chat['id']).json()['messages'][-1]['reaction']==1
    assert other.post(path+'/reaction',json={'value':-1}).status_code==404
    branch=c.post(path+'/branch',json={'version':chat['version']});assert branch.status_code==200,branch.text
    child=branch.json();assert child['id']!=chat['id'];assert [m['content'] for m in child['messages']]==[m['content'] for m in chat['messages']]
    assert child['sources'][0]['id']!=chat['sources'][0]['id'];assert child['sources'][0]['path']==chat['sources'][0]['path']
    share=c.post(path+'/share',json={'body':'当前选择：10；分享快照'}).json();anonymous=TestClient(env[0],base_url=ORIGIN)
    assert anonymous.get('/api/shared-replies/'+share['token']).json()['body']=='当前选择：10；分享快照'
    assert anonymous.get('/api/conversations/'+chat['id']).status_code==401
    assert other.delete(f"/api/conversations/{chat['id']}/shares/{share['token']}").status_code==404
    assert c.delete(f"/api/conversations/{chat['id']}/shares/{share['token']}").status_code==200
    assert anonymous.get('/api/shared-replies/'+share['token']).status_code==404


def test_branch_rebases_material_links_but_preserves_literal_ids_and_exact_quotes(env,monkeypatch):
    from app.db import dumps
    c=account(env);chat=material(c,conversation(c));env[1].ai_api_key='synthetic-only'
    cid=chat['id'];sid=chat['sources'][0]['id'];quote='原文记录编号 '+sid+'，须保持逐字一致。'
    sections=[{'locator':'第1段','text':quote}]
    with env[0].state.db.connect(write=True) as conn:
        conn.execute('UPDATE conversation_sources SET sections=? WHERE id=?',(dumps(sections),sid))
        conn.execute('UPDATE material_library SET full_sections=? WHERE source_id=?',(dumps(sections),sid))
    body=f'记录编号 `{sid}`。 [原件](/api/conversations/{cid}/sources/{sid}/download)'
    monkeypatch.setattr(chat_ai,'reply',lambda *args:({'answer':body,'citations':[{'source_id':sid,'locator':'第1段','quote':quote}],'image_sources':[]},{}))
    chat,_=send(c,chat);mid=chat['messages'][-1]['id']
    child=c.post(f'/api/conversations/{cid}/messages/{mid}/branch',json={'version':chat['version']}).json()
    fresh=child['sources'][0]['id'];new_url=f"/api/conversations/{child['id']}/sources/{fresh}/download"
    assert new_url in child['messages'][-1]['content']
    assert f'`{sid}`' in child['messages'][-1]['content']
    assert child['messages'][-1]['citations'][0]=={'source_id':fresh,'locator':'第1段','quote':quote}
    assert not child['model_consent']
    assert c.request('DELETE',f'/api/conversations/{cid}',json={'version':chat['version']}).status_code==200
    assert c.get(new_url).status_code==200
