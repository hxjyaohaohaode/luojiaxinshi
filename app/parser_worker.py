"""Bounded document reader. Run in a separate process, never execute document code."""
import io
import json
import sys
import zipfile

from defusedxml import ElementTree as ET
from pypdf import PdfReader

MAX_TEXT = 10000


def extract(data, kind):
    if kind in {'csv','xlsx'}:
        from .spreadsheet import spreadsheet_sections
        return spreadsheet_sections(data,kind)
    if kind in {'png','jpg','jpeg','webp'}:
        import warnings
        from PIL import Image
        Image.MAX_IMAGE_PIXELS=20000000
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as picture:
                expected={'png':'PNG','jpg':'JPEG','jpeg':'JPEG','webp':'WEBP'}[kind]
                if picture.format!=expected or getattr(picture,'n_frames',1)!=1:
                    raise ValueError('图片类型与扩展名不一致，或包含多帧；请上传单张静态图片')
                picture.verify()
        return {'sections':[],'status':'review','warning':'图片原件已保存。对话可交由视觉模型阅读；其中日期和关键要求仍需本人核对。'}
    sections = []
    warnings = []
    total = 0

    def add(locator, text):
        nonlocal total
        text = text.replace('\x00', '').strip()
        total += len(text)
        if total > MAX_TEXT:
            raise ValueError('提取文本超过 10000 字，未截断；请拆分材料后重新上传')
        if text:
            sections.append({'locator': locator, 'text': text})

    if kind == 'pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('文件内容不是 PDF')
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError('加密 PDF 不可解析，请上传解密后的有权处理版本')
        if len(reader.pages) > 50:
            raise ValueError('PDF 超过 50 页，请拆分后上传')
        for i, page in enumerate(reader.pages, 1):
            content = page.get_contents()
            if content and len(content.get_data()) > 8*1024*1024:
                raise ValueError('PDF 单页内容过大，请简化文档')
            text = page.extract_text() or ''
            add(f'第 {i} 页', text)
            if len(text.strip()) < 8:
                warnings.append(f'第 {i} 页没有足够的可提取文字，可能是扫描件或空白页，请核对')
    elif kind == 'docx':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos)>500 or sum(x.file_size for x in infos)>25*1024*1024:
                raise ValueError('DOCX 解压体积或文件数量超限')
            if any(x.flag_bits & 1 for x in infos):
                raise ValueError('加密 DOCX 不可解析')
            if any(x.filename.endswith('vbaProject.bin') for x in infos):
                raise ValueError('不接受包含宏的文件')
            ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            root = ET.fromstring(archive.read('word/document.xml'))
            for i, paragraph in enumerate(root.findall('.//w:body//w:p', ns), 1):
                add(f'第 {i} 段', ''.join(paragraph.itertext()) if not paragraph.findall('.//w:t',ns)
                    else ''.join(node.text or '' for node in paragraph.findall('.//w:t', ns)))
            if root.findall('.//w:tbl', ns):
                warnings.append('文档含表格：文字已按段落提取，请核对行列对应关系后解除待核对状态')
            if root.findall('.//w:drawing', ns) or root.findall('.//w:pict', ns):
                warnings.append('文档含图片：图片内容未识别，请补充其中的关键信息')
            if any(x.filename.startswith(('word/header','word/footer','word/footnotes','word/endnotes')) for x in infos):
                warnings.append('页眉、页脚或脚注未纳入正文，请核对是否包含办理信息')
    elif kind in {'txt','md'}:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gb18030')
        for i, line in enumerate(text.splitlines(), 1):
            add(f'第 {i} 段', line)
    else:
        raise ValueError('仅支持文字型 PDF、DOCX、TXT')
    if not sections:
        raise ValueError('没有可提取文字，请补充正文；扫描件暂不支持')
    if any('\ufffd' in x['text'] for x in sections):
        warnings.append('文本含不可识别字符，请核对原件')
    return {'sections':sections,'status':'review' if warnings else 'ok','warning':'；'.join(warnings)}


if __name__ == '__main__':
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU,(18,18))
        result = extract(sys.stdin.buffer.read(5*1024*1024+1), sys.argv[1])
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '文件损坏或结构不受支持，请补充正文或更换文件'
        result = {'sections':[], 'status':'failed', 'warning':message}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
