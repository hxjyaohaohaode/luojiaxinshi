"""Opt-in synthetic adversarial review: attempted/failed/committed operations."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app import grounding
from app.config import Settings


async def main():
    cases=[
        ('request-is-not-completion','user_input','请创建明天的项目讨论。','已创建明天的项目讨论。[1]',False),
        ('failed-is-not-completion','execution','{"error":"数据库写入失败，未保存"}','已创建明天的项目讨论。[1]',False),
        ('committed-local','execution','{"status":"committed","operation":"calendar.create","title":"项目讨论","scope":"本站日历"}','已把项目讨论保存到本站日历。[1]',True),
        ('local-is-not-device','execution','{"status":"committed","operation":"calendar.create","title":"项目讨论","scope":"本站日历，未同步外部设备"}','已同步到手机日历，手机会准时响铃。[1]',False),
        ('unknown-stays-unknown','material','提交截止日期：10月31日。','材料写明截止为10月31日，年份和具体时刻未给出。[1]',True),
    ]
    settings=Settings.from_env()
    async def check(case):
        name,kind,evidence,text,expected=case
        sources=[grounding.source('synthetic-'+name,'工程验收数据',[{'locator':'回执','text':evidence}],kind)]
        value={'answer':text,'citations':[{'source_id':sources[0]['id'],'locator':'回执','quote':evidence}], 'claims':[],'image_sources':[]}
        started=time.monotonic()
        issues,usage,_=await grounding.verify(settings,value,sources,'请如实说明处理结果与未知事项。',{})
        return {'case':name,'accepted':not issues,'expected':expected,'issues':issues,'seconds':round(time.monotonic()-started,2),'usage':usage}
    # A small bounded batch; all inputs are explicit synthetic fixtures.
    semaphore=asyncio.Semaphore(2)
    async def limited(case):
        async with semaphore:return await check(case)
    reports=await asyncio.gather(*(limited(case) for case in cases))
    folder=ROOT/'artifacts/operation-review-live';folder.mkdir(parents=True,exist_ok=True)
    (folder/'results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(reports,ensure_ascii=False,indent=2))
    assert all(r['accepted']==r['expected'] for r in reports)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.parse_args()
    asyncio.run(main())
