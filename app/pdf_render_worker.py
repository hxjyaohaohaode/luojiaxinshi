"""Rasterize explicitly requested PDF pages; no network or document actions."""
import base64
import io
import json
import math
import sys


def render(data, pages):
    import pypdfium2 as pdfium
    if not data.startswith(b'%PDF-') or len(data) > 5 * 1024 * 1024:
        raise ValueError('PDF 原件格式或大小无效')
    if pages is not None and (not pages or len(pages) > 50 or any(type(page) is not int or page < 1 for page in pages)):
        raise ValueError('PDF 图像页数量或页码无效')
    result, size = [], 0
    with pdfium.PdfDocument(data) as pdf:
        pdf.init_forms()
        count=len(pdf)
        if pages is None:pages=list(range(1,count+1))
        if not pages or count > 50 or max(pages) > count:
            raise ValueError('PDF 页数超出解析范围，未截断处理')
        for number in pages:
            page=pdf[number-1]
            try:
                width, height = page.get_size()
                if not all(math.isfinite(value) and 0 < value <= 14400 for value in (width, height)):
                    raise ValueError('PDF 页面尺寸无效或过大')
                scale = min(1536 / width, 3072 / height, 3)
                bitmap = page.render(scale=scale, draw_annots=True, may_draw_forms=True,
                                     fill_color=(255, 255, 255, 255), limit_image_cache=True)
                try:
                    with bitmap.to_pil().convert('RGB') as image:
                        output = io.BytesIO()
                        image.save(output, format='JPEG', quality=90)
                        content = output.getvalue()
                finally:
                    bitmap.close()
                size += len(content)
                if size > 5 * 1024 * 1024:
                    raise ValueError('PDF 页面图像总大小超出预算，未发送部分页面冒充完整内容')
                result.append({'page': number, 'jpeg': base64.b64encode(content).decode('ascii')})
            finally:
                page.close()
    return {'pages': result,'page_count':count}


if __name__ == '__main__':
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (18, 18))
        value = render(sys.stdin.buffer.read(5 * 1024 * 1024 + 1), json.loads(sys.argv[1]))
    except Exception as error:
        value = {'error': str(error) if isinstance(error, ValueError) else 'PDF 页面无法完整渲染，请核对原件或补充清晰页面'}
    sys.stdout.buffer.write(json.dumps(value).encode('utf-8'))
