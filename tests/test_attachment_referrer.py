"""Public parent provenance is required by real CMS attachment endpoints."""
import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from pypdf import PdfWriter

from app import notice_intake
from app.documents import text_source


def pdf_bytes():
    output=BytesIO();writer=PdfWriter();writer.add_blank_page(width=200,height=200);writer.write(output)
    return output.getvalue()


def test_cms_attachment_uses_public_parent_without_query_or_fragment(monkeypatch):
    parent='https://dept.example.edu/news/123.html?private_parameter=do-not-forward#anchor'
    attachment='https://dept.example.edu/system/_content/download.jsp?id=public-document'
    calls=[]
    def response(request):
        calls.append(request)
        if request.headers.get('referer')!='https://dept.example.edu/news/123.html':
            return httpx.Response(200,headers={'content-type':'text/html'},text='<html>Return to the article</html>')
        return httpx.Response(200,headers={'content-type':'application/octet-stream',
            'content-disposition':'attachment; filename="appendix.pdf"'},content=pdf_bytes())
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(response))
    source=text_source('这是原始通知，附件请以下载内容为准。')
    source['origin']={'url':parent,'attachments':[attachment],'attachment_names':{attachment:'appendix.pdf'}}
    materials=asyncio.run(notice_intake.read_notice_materials(source))
    assert len(materials)==2 and materials[1]['kind']=='pdf'
    assert materials[0]['origin']['received_attachments']==[attachment]
    assert materials[1]['origin']['url']==attachment
    assert len(calls)==1 and 'private_parameter' not in calls[0].headers['referer']


@pytest.mark.parametrize('parent',['https://other.example.edu/private?token=x','http://127.0.0.1/private',None])
def test_unrelated_or_private_parent_is_not_forwarded(monkeypatch,parent):
    calls=[]
    def response(request):
        calls.append(request)
        return httpx.Response(200,headers={'content-type':'text/plain'},text='这是公开的附件文本。')
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(response))
    asyncio.run(notice_intake._read_link('https://dept.example.edu/file.txt',referrer=parent))
    assert 'referer' not in calls[0].headers


def test_attachment_redirect_cannot_send_referrer_to_another_host(monkeypatch):
    calls=[]
    def response(request):
        calls.append(request)
        return httpx.Response(302,headers={'location':'https://other.example.edu/steal'})
    monkeypatch.setattr(notice_intake,'PublicHTTPTransport',lambda:httpx.MockTransport(response))
    with pytest.raises(HTTPException) as error:
        asyncio.run(notice_intake._read_link('https://dept.example.edu/file.pdf',allowed_host='dept.example.edu',
                                           referrer='https://dept.example.edu/news/123.html'))
    assert error.value.status_code==422 and len(calls)==1
