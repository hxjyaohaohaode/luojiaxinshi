"""Bounded spreadsheet text preview; formulas, macros and external links never run."""
import csv
import io
import posixpath
import re
import zipfile
from defusedxml import ElementTree as ET

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def spreadsheet_sections(data,kind):
    sheets=[]
    warnings=[]
    if kind=='csv':
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:text=data.decode('gb18030')
        if len(text)>10000:raise ValueError('表格文字超过 10000 字，请拆分上传')
        rows=list(csv.reader(io.StringIO(text)))
        sheets=[('CSV',rows)]
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist()
            if len(infos)>500 or sum(x.file_size for x in infos)>25*1024*1024 or any(x.flag_bits&1 for x in infos):
                raise ValueError('表格解压体积超限或包含加密内容')
            if any('vbaproject' in x.filename.lower() or 'externallinks/' in x.filename.lower() for x in infos):
                raise ValueError('不接受宏或外部链接表格，请另存为普通 XLSX')
            strings=[]
            if 'xl/sharedStrings.xml' in archive.namelist():
                for node in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si',NS):
                    strings.append(''.join(x.text or '' for x in node.findall('.//s:t',NS)))
                    if len(strings)>10000:raise ValueError('表格共享字符串数量超限')
            links={node.attrib['Id']:node.attrib.get('Target','') for node in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels')) if node.attrib.get('TargetMode')!='External'}
            book=ET.fromstring(archive.read('xl/workbook.xml'))
            for sheet in book.findall('s:sheets/s:sheet',NS):
                if len(sheets)>=20:raise ValueError('表格超过 20 个工作表，请拆分上传')
                target=links.get(sheet.attrib.get('{'+REL+'}id'),'')
                name=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
                if not name.startswith('xl/worksheets/') or not name.endswith('.xml'):raise ValueError('工作表引用无效')
                root=ET.fromstring(archive.read(name));rows=[]
                for row in root.findall('s:sheetData/s:row',NS):
                    values=[]
                    for cell in row.findall('s:c',NS):
                        match=re.fullmatch(r'([A-Z]{1,3})([0-9]{1,7})',cell.attrib.get('r',''))
                        if not match:raise ValueError('工作表单元格地址无效')
                        col=0
                        for char in match[1]:col=col*26+ord(char)-64
                        if col>50:raise ValueError('表格超过 50 列，请只保留相关列')
                        while len(values)<col:values.append('')
                        value=cell.findtext('s:v','',NS)
                        if cell.attrib.get('t')=='s':
                            if not value.isdigit() or int(value)>=len(strings):raise ValueError('共享字符串引用无效')
                            value=strings[int(value)]
                        elif cell.attrib.get('t')=='inlineStr':value=''.join(x.text or '' for x in cell.findall('.//s:t',NS))
                        if cell.find('s:f',NS) is not None:
                            if '公式显示文件中保存的值，未重新计算' not in warnings:warnings.append('公式显示文件中保存的值，未重新计算')
                            value=value or '[公式无缓存值]'
                        values[col-1]=value.replace('\t',' ').replace('\r',' ').replace('\n',' ')
                    rows.append(values)
                    if len(rows)>1000:raise ValueError('单工作表超过 1000 行，请拆分上传')
                if root.find('s:mergeCells',NS) is not None:warnings.append('含合并单元格，请下载原件核对对应关系')
                sheets.append((sheet.attrib.get('name','工作表'),rows))
        warnings.append('文字表格预览不保留格式、图表和日期数字格式，请核对原件')
    sections=[];total=0;cells=0
    for name,rows in sheets:
        if len(rows)>1000:raise ValueError('单工作表超过 1000 行，请拆分上传')
        for i,row in enumerate(rows,1):
            if len(row)>50:raise ValueError('表格超过 50 列，请只保留相关列')
            cells+=len(row)
            if cells>5000:raise ValueError('表格超过 5000 个单元格，请拆分上传')
            text='\t'.join(str(x).replace('\t',' ').replace('\n',' ').replace('\r',' ') for x in row)
            total+=len(text)
            if total>10000:raise ValueError('表格文字超过 10000 字，请拆分上传')
            if text.strip():sections.append({'locator':f'{name[:40]} · 第 {i} 行','text':text,'table':True})
    if not sections:raise ValueError('表格没有可读取的文字')
    return {'sections':sections,'status':'review' if warnings else 'ok','warning':'；'.join(dict.fromkeys(warnings))}
