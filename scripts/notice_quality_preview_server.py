"""Serve an isolated copy of a retained draft plus its real review, without a key."""
import hashlib
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.config import Settings
from app.main import create_app
from app.version import VERSION
import uvicorn

folder=ROOT/'artifacts/mvp-acceptance'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-report',default='business-notice-streamed-1.8.1.json')
parser.add_argument('--review-report',default='notice-semantics-business-20261018.json')
parser.add_argument('--label',default='')
args=parser.parse_args()
for name in (args.source_report,args.review_report):
    if Path(name).name!=name or Path(name).suffix!='.json':parser.error('Reports must be JSON filenames inside the evidence folder')
if args.label and (not args.label.isascii() or not args.label.isalpha()):parser.error('Label must contain ASCII letters only')
source_file=folder/args.source_report
source=json.loads(source_file.read_text(encoding='utf8'))
review_file=folder/args.review_report
review=json.loads(review_file.read_text(encoding='utf8'))
assert review['input_sha256']==hashlib.sha256(source_file.read_bytes()).hexdigest()
original=Path(source['isolated_data_dir']).resolve();assert original.is_relative_to(folder.resolve())
data=Path(tempfile.mkdtemp(prefix='quality-preview-',dir=folder))
with sqlite3.connect((original/'campus.sqlite3').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(data/'campus.sqlite3') as dest:src.backup(dest)
quality={**review['review'],'model':review['model']}
with sqlite3.connect(data/'campus.sqlite3') as conn:
    current=json.loads(conn.execute('SELECT draft FROM notices WHERE id=?',(source['notice_id'],)).fetchone()[0])
    current['quality']=quality;conn.execute('UPDATE notices SET draft=? WHERE id=?',(json.dumps(current,ensure_ascii=False),source['notice_id']))
app=create_app(Settings(data,origin='http://127.0.0.1:8781',ai_api_key='',notice_semantic_review=False,ai_grounding=False))
(folder/f'quality-preview-{args.label+"-" if args.label else ""}{VERSION}.json').write_text(json.dumps({'version':VERSION,'data_dir':str(data),'notice_id':source['notice_id'],
    'sample':'Retained real-generated draft plus real Flash review; isolated synthetic account; no provider call during browser testing.',
    'source_report':source_file.name,'review_report':review_file.name,'quality':quality},ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8781,access_log=False)
