"""Rasterize the existing self-contained app icon for Web App Manifest consumers."""
from base64 import b64decode
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

ROOT=Path(__file__).resolve().parent.parent
assets=ROOT/'static/assets'
svg=ET.fromstring((assets/'app-icon.svg').read_text(encoding='utf-8'))
element=svg.find('{http://www.w3.org/2000/svg}image')
assert element is not None
href=element.attrib['href']
assert href.startswith('data:image/png;base64,')
with Image.open(BytesIO(b64decode(href.split(',',1)[1],validate=True))) as source:
    for size in (192,512):
        canvas=Image.new('RGB',(size,size),'white')
        offset=round(size*32/512)
        mark=source.convert('RGBA').resize((size-2*offset,size-2*offset),Image.Resampling.LANCZOS)
        canvas.paste(mark,(offset,offset),mark)
        canvas.save(assets/f'app-icon-{size}.png',optimize=True)
        print(f'app-icon-{size}.png: {size} x {size}')
