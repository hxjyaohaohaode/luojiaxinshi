"""Opt-in paid adversarial checks for fast independent multimodal review."""
import argparse,asyncio,io,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw,ImageFont
from app.config import Settings
from app import grounding
from app.visual_evidence import register_images,IMAGE_LOCATOR,IMAGE_NOTE

async def main():
    picture=Image.new('RGB',(640,240),'white')
    ImageDraw.Draw(picture).multiline_text((24,25),'Engineering assignment\nRequired: login, search, book list\nDeadline: October 31\nDeliver: source code and short report',fill='black',font=ImageFont.load_default(size=24),spacing=12)
    output=io.BytesIO();picture.save(output,format='PNG')
    sources=register_images([{'id':'synthetic-image','name':'assignment.png','kind':'png','content':output.getvalue(),'status':'image','sections':[],'warning':''}])
    citation={'source_id':'synthetic-image','locator':IMAGE_LOCATOR,'quote':IMAGE_NOTE}
    cases=[
        ('wrong-date','截止是 10 月 11 日。[1]',False),
        ('invented-grading','评分标准只有登录、搜索和书单，其他方面不会影响成绩。[1]',False),
        ('grounded-advice','作业要求登录、搜索和书单，截止 10 月 31 日，提交源代码和简短报告；年份与具体时刻未给出。[1] 个人建议：先建立项目目录和报告提纲。',True),
    ]
    settings=Settings.from_env();reports=[]
    for name,text,expected in cases:
        value={'answer':text,'citations':[citation],'image_sources':['synthetic-image'],'claims':[]}
        started=time.monotonic();issues,usage,_=await grounding.verify(settings,value,sources,'帮我核对图片内容并安排下一步。',{})
        reports.append({'case':name,'accepted':not issues,'expected':expected,'issues':issues,'seconds':round(time.monotonic()-started,2),'options':grounding.review_options(settings,value,sources),'usage':usage})
    folder=ROOT/'artifacts/composer-review-live';folder.mkdir(parents=True,exist_ok=True)
    (folder/'results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(reports,ensure_ascii=False,indent=2))
    assert all(r['accepted']==r['expected'] for r in reports)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--allow-paid-synthetic-test',action='store_true',required=True);parser.parse_args()
    asyncio.run(main())
