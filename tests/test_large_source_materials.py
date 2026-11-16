"""Large public attachments retain all extracted evidence and original bytes."""
from io import BytesIO

from pypdf import PdfWriter

from app import ai, source_sync
from app.documents import file_source, text_source, total_chars
from app.notice_semantics import SourceCheck
from app.pdf_visual import declared_pages
from tests.test_experience import workbook
from tests.test_source_subscriptions import enable, website
from tests.test_workflow import account, env


def test_public_reader_handles_long_pdf_and_spreadsheet_without_truncation():
    output=BytesIO();writer=PdfWriter()
    for _ in range(63):writer.add_blank_page(width=72,height=72)
    writer.write(output);pdf=output.getvalue()
    assert file_source('long.pdf',pdf)['status']=='failed'
    parsed=file_source('long.pdf',pdf,expanded=True)
    assert parsed['content']==pdf and parsed['status']=='review'
    assert len(parsed['sections'])==63 and declared_pages(parsed)==list(range(1,64))

    rows=''.join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>材料编号{i}及说明内容</t></is></c></row>' for i in range(1,1102))
    data=workbook(rows=rows)
    assert file_source('long.xlsx',data)['status']=='failed'
    parsed=file_source('long.xlsx',data,expanded=True)
    assert parsed['content']==data and len(parsed['sections'])==1101
    assert parsed['sections'][-1]['locator']=='准备 · 第 1101 行'
    assert parsed['sections'][-1]['text']=='材料编号1101及说明内容'
    assert total_chars([parsed])>10000


def test_subscription_keeps_every_attachment_and_model_reference(env,monkeypatch):
    client=account(env);sid=website(client);enable(client,sid)
    article='https://school.example.edu.cn/info/large.htm'
    files=[f'https://school.example.edu.cn/files/{i}.docx' for i in range(6)]
    async def index(config):return [{'url':article,'title':'合成通知','published_at':None}]
    async def read(url):
        if url==article:
            source=text_source('报名通知正文','合成通知')
            source['origin']={'url':url,'attachments':files,'warnings':[]}
        else:
            i=files.index(url);source=text_source(f'文件{i}开始'+('甲'*2600)+f'文件{i}末尾',f'材料{i}.docx')
            source.update(kind='docx',content=f'original-{i}'.encode())
            source['origin']={'url':url,'attachments':[],'warnings':[]}
        return source,source['name']
    monkeypatch.setattr(source_sync,'fetch_index',index)
    monkeypatch.setattr(source_sync,'read_link',read)
    response=client.post('/api/source-catalog/'+sid+'/refresh')
    assert response.status_code==200 and response.json()['issue_count']==0,response.text
    listing=client.get('/api/notices').json();assert len(listing)==1
    notice=client.get('/api/notices/'+listing[0]['id']).json()
    active=[source for source in notice['sources'] if source['active']]
    assert len(active)==7 and total_chars(active)>10000
    assert all(f'文件{i}末尾' in active[i+1]['sections'][0]['text'] for i in range(6))
    _,_,model_input=ai.prepare_notice_input(env[1],notice,active,{})
    assert all(f'文件{i}末尾' in model_input for i in range(6))
    assert SourceCheck(source_index=6,requirements_summary='合成材料供本人核对',evidence_refs=[],coverage='background').source_index==6
    again=client.post('/api/source-catalog/'+sid+'/refresh')
    assert again.status_code==200 and len(client.get('/api/notices').json())==1


def test_large_source_text_survives_portable_import_validation():
    from app.data_transfer import sources
    rows=[{'locator':f'第 {i} 行','text':f'{i}'+('甲'*70),'table':True} for i in range(1,2102)]
    restored=sources([{'id':'saved','name':'名单.xlsx','sections':rows}])
    assert len(restored[0]['sections'])==2101
    assert restored[0]['sections'][-1]==rows[-1]
