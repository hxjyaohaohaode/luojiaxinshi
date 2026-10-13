import pytest
from app.chat_media import chat_file_source,resource_index,video_response
from app.genui_ai import payload
from app.genui import validate_node
from test_workflow import env,account
from test_workspace import conversation

# Header fixtures validate boundary handling, not codec playability.
MP4=b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isommp41'+b'payload'*30


def test_private_video_range_and_resource_authorization(env):
    a,b=account(env),account(env,'other');chat=conversation(a)
    r=a.post('/api/conversations/'+chat['id']+'/sources',data={'version':chat['version']},files={'files':('sample.mp4',MP4,'video/mp4')})
    assert r.status_code==200,r.text
    source=r.json()['sources'][0];resources=resource_index([source]);assert len(resources)==1
    path=resources[0]['src'];assert b.get(path).status_code==404
    full=a.get(path);assert full.content==MP4 and full.headers['content-type']=='video/mp4'
    part=a.get(path,headers={'Range':'bytes=2-15'});assert part.status_code==206 and part.content==MP4[2:16]
    assert a.get(path,headers={'Range':'bytes=-5'}).content==MP4[-5:]
    for value in ['bytes=999999-','bytes=-0','bytes=1-0','bytes=1-2,4-5','bytes=x-y']:
        assert a.get(path,headers={'Range':value}).status_code==416
    assert resource_index([{**source,'status':'failed'}])==[]
    source['content']=MP4
    request=payload(env[1],[source],[],{},1)
    material=request['messages'][1]['content'];assert len(material)==1
    assert '模型未观看视频' in material[0]['text'] and resources[0]['src'] in material[0]['text']
    assert 'data:video' not in str(request)


def test_media_spoofs_and_plot_expressions_are_rejected():
    for name,data in [('fake.mp4',b'<html>'),('fake.webm',MP4),('big.mp4',MP4+b'0'*(5*1024*1024))]:
        with pytest.raises(ValueError):chat_file_source(name,data)
    with pytest.raises(ValueError):validate_node({'id':'p','type':'Plot','props':{'expression':'fetch(x)','xMin':0,'xMax':1}})
    assert video_response(MP4,'mp4','name.mp4','bytes=0-9999').status_code==206
