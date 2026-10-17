"""Offline protocol and UI-choice evaluation, not a claim about live model quality."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.genui import parse_message
from app.console import configure_text_output


def evaluate(case):
    errors=[]
    try:
        parts=parse_message(case['response'],data=case.get('data',{}))
        blocks=[p['spec'] for p in parts if p['kind']=='ui']
        actual='ui' if blocks else 'text'
        if actual!=case['expected']:errors.append('choice_mismatch')
        for block in blocks:
            if not block['complete']:errors.append('incomplete')
            errors.extend(e['code'] for e in block['errors'])
        types={node['type'] for block in blocks for node in block['nodes'].values()}
        if not set(case.get('components',[]))<=types:errors.append('missing_expected_component')
        if not any(p['kind']=='text' and p['text'].strip() for p in parts):errors.append('missing_readable_text')
    except (ValueError,TypeError,KeyError):errors.append('invalid_response')
    return {'id':case['id'],'expected':case['expected'],'passed':not errors,'errors':sorted(set(errors))}


def run(path):
    cases=json.loads(path.read_text(encoding='utf-8'));results=[evaluate(case) for case in cases]
    return {'source':'离线合成工程夹具；未调用模型，不代表真实模型取舍或质量','total':len(results),'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'results':results}


if __name__=='__main__':
    configure_text_output()
    parser=argparse.ArgumentParser();parser.add_argument('--cases',type=Path,default=ROOT/'fixtures/genui/eval-cases.json');parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=run(args.cases)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    raise SystemExit(0 if not report['failed'] else 1)
