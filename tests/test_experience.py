import io
import zipfile
import pytest
from app.documents import file_source
from app.spreadsheet import spreadsheet_sections
from app.genui_ai import payload
from app.models import Profile
from test_workflow import env,account,notice,manual,confirm


def workbook(target='worksheets/sheet1.xml',cell='<c r="A1" t="inlineStr"><is><t>报名材料</t></is></c>'):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="准备" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships><Relationship Id="rId1" Target="{target}"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">{cell}</row></sheetData></worksheet>')
    return data.getvalue()


def test_spreadsheet_bounds_and_no_formula_execution():
    result=spreadsheet_sections(workbook(),'xlsx')
    assert result['sections'][0]['table'] and result['sections'][0]['text']=='报名材料'
    formula=spreadsheet_sections(workbook(cell='<c r="A1"><f>WEBSERVICE("https://example.invalid")</f><v>12</v></c>'),'xlsx')
    assert formula['sections'][0]['text']=='12' and '未重新计算' in formula['warning']
    for bad in [workbook(target='../bad.xml'),workbook(cell='<c r="ZZ1"><v>1</v></c>')]:
        with pytest.raises(ValueError):spreadsheet_sections(bad,'xlsx')
    with pytest.raises(ValueError):spreadsheet_sections(('a,'*51).encode(),'csv')
    assert spreadsheet_sections('名称,数量\n申请表,2'.encode(),'csv')['sections'][1]['text']=='申请表\t2'
    assert file_source('sheet.xlsx',workbook())['status']=='review'


def test_profile_preferences_reach_model_but_contacts_do_not(env):
    c=account(env);profile=Profile(preferred_name='同学',response_detail='concise',response_style='direct',campus_area='文理学部',phone='18800000000',student_id='private-id').model_dump()
    assert c.put('/api/profile',json=profile).status_code==200
    request=payload(env[1],[],[],profile,1)
    assert '简明' in request['messages'][0]['content'] and '直接清楚' in request['messages'][0]['content']
    assert '文理学部' in str(request) and '18800000000' not in str(request) and 'private-id' not in str(request)
    assert c.put('/api/profile',json={**profile,'response_style':'<script>'}).status_code==422


def test_import_preview_atomic_idempotent_and_owner_scoped(env):
    source=account(env);other=account(env,'other')
    n=manual(source,notice(source));confirm(source,n)
    data=source.get('/api/export').json();preview=other.post('/api/import',json={'data':data})
    assert preview.status_code==200,preview.text
    assert other.get('/api/notices').json()==[]
    assert other.post('/api/import',json={'data':data,'confirm':True,'digest':'wrong'}).status_code==409
    commit={'data':data,'confirm':True,'digest':preview.json()['digest']}
    first=other.post('/api/import',json=commit);assert first.status_code==200,first.text
    assert first.json()['added']==1
    imported=other.get('/api/tasks').json();assert len(imported)==1 and imported[0]['data']['deadline_confirmed'] is False and imported[0]['data']['reminder_at'] is None
    assert other.get('/api/notices/'+n['id']).status_code==404
    assert other.post('/api/import',json=commit).json()['skipped']==1
    assert len(source.get('/api/tasks').json())==1
    bad={**data,'profile':{'__proto__':{'admin':True}}}
    assert other.post('/api/import',json={'data':bad}).status_code==422
    assert len(other.get('/api/tasks').json())==1


def test_task_attachment_metadata_and_notice_video_are_private(env):
    from test_chat_media import MP4
    c=account(env);other=account(env,'other')
    n=notice(c,files=[('files',('sheet.csv','材料,数量\n申请表,2'.encode(),'text/csv'))]);n=manual(c,n);confirm(c,n)
    task=c.get('/api/tasks').json()[0];assert task['attachments'][0]['name']=='sheet.csv'
    assert 'sections' not in task['attachments'][0] and 'content' not in task['attachments'][0]
    video=notice(c,text='视频为补充展示。',files=[('files',('preview.mp4',MP4,'video/mp4'))])
    sid=next(s['id'] for s in video['sources'] if s['kind']=='mp4');path=f"/api/notices/{video['id']}/sources/{sid}/download?preview=true"
    assert c.get(path,headers={'Range':'bytes=1-10'}).content==MP4[1:11]
    assert other.get(path).status_code==404


def test_notice_to_chat_is_private_idempotent_and_preserves_original(env):
    c=account(env);other=account(env,'other')
    n=notice(c,files=[('files',('plan.csv','项目,数量\n申请表,2'.encode(),'text/csv'))])
    path=f"/api/notices/{n['id']}/conversation";body={'version':n['version']}
    assert other.post(path,json=body).status_code==404
    assert c.post(path,json={'version':n['version']+1}).status_code==409
    response=c.post(path,json=body);assert response.status_code==200,response.text
    cid=response.json()['conversation_id'];chat=c.get('/api/conversations/'+cid).json()
    assert len(chat['sources'])==len(n['sources']) and chat['messages']==[]
    assert c.post(path,json=body).json()['conversation_id']==cid
    assert c.get('/api/notices/'+n['id']).json()['version']==n['version']
    assert other.get('/api/conversations/'+cid).status_code==404
    source=next(s for s in chat['sources'] if s['kind']=='csv')
    assert c.get(f"/api/conversations/{cid}/sources/{source['id']}/download").content=='项目,数量\n申请表,2'.encode()


def test_import_incomplete_reply_is_not_marked_complete(env):
    c=account(env)
    data={'format_version':1,'conversations':[{'id':'backup-chat','title':'未完成的对话','messages':[{'role':'user','content':'问题','status':'complete','created_at':1700000000},{'role':'assistant','content':'已收到的片段','status':'processing','created_at':1700000001}]}]}
    preview=c.post('/api/import',json={'data':data});assert preview.status_code==200,preview.text
    assert c.post('/api/import',json={'data':data,'confirm':True,'digest':preview.json()['digest']}).status_code==200
    chats=c.get('/api/conversations').json();m=c.get('/api/conversations/'+chats[0]['id']).json()['messages'][-1]
    assert m['status']=='cancelled' and m['content']=='已收到的片段'
    data['conversations'][0]['messages'][0]['created_at']=10**30
    assert c.post('/api/import',json={'data':data}).status_code==422
