"""Repeatable local-only comparison with the checked-in retrieval baseline.

No provider, secrets, real accounts or documents are used. Timings are local
microbenchmarks under current machine load, not model or production latency.
"""
import ast
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.grounding import select_sections,source


def main():
    committed=subprocess.run(['git','show','HEAD:app/grounding.py'],cwd=ROOT,check=True,capture_output=True,encoding='utf-8').stdout
    node=next(n for n in ast.parse(committed).body if isinstance(n,ast.FunctionDef) and n.name=='select_sections')
    namespace={'__package__':'app'}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'checked-in-baseline','exec'),namespace)
    baseline=namespace['select_sections']
    key='申请必须通过甲系统提交，最终截止2027年3月12日17:00。'
    paragraph='工程背景说明。'*3000+'地理信息实验最终申请入口：'+key+'补充说明。'*300
    records=[source(f'noise-{i}','合成历史资料',[{'locator':f'第{j}段','text':'无关的历史背景说明。'*60} for j in range(24)],'notice') for i in range(120)]
    records.append(source('target','地理信息实验项目',[{'locator':'完整正文','text':paragraph}],'notice'))
    query=['地理信息实验 最终申请入口 甲系统']
    report={'synthetic_only':True,'scanned_sources':len(records),'scanned_characters':sum(len(s['text']) for r in records for s in r['sections']),
        'comparison':'current local retrieval vs current HEAD baseline; not a production benchmark'}
    for name,select in [('baseline',baseline),('current',select_sections)]:
        select(records,query,46000)  # warm imports/caches before measuring
        durations=[]
        for _ in range(5):
            started=time.perf_counter();got,coverage=select(records,query,46000);durations.append(time.perf_counter()-started)
        spans=[s for r in got for s in r['sections']]
        report[name]={'tail_fact_retrieved':any(key in s['text'] for s in spans),'median_seconds':round(statistics.median(durations),5),
            'runs_seconds':[round(x,5) for x in durations],'selected_sources':coverage['selected_sources'],'characters':coverage['characters']}
    assert report['current']['tail_fact_retrieved']
    target=next(s for r in got if r['id']=='target' for s in r['sections'])
    assert target['text']==paragraph[target['_retrieval_offset']:target['_retrieval_offset']+len(target['text'])]
    output=ROOT/'artifacts/proactive-retrieval-comparison.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
