"""Loopback-only memory UI fixture with an explicitly simulated provider."""
from mvp_preview_server import app, seed, PORT
from app import chat_ai, genui_ai
from dataclasses import replace
from app import memory_assist,evidence_web
from app import notice_intake
from app.documents import text_source
from fastapi import HTTPException
import time

assert PORT in {8786,8787}, 'Memory fixture must use its own loopback port'
app.state.settings=replace(app.state.settings,ai_api_key='synthetic-fixture-only',notice_semantic_review=False)


async def edit_fixture(settings,selection,instruction):
    if instruction.startswith('替换为：'):return instruction.removeprefix('替换为：')
    raise ValueError('Only a literal fixture replacement is supported')


async def no_external_requests(*args,**kwargs):
    raise RuntimeError('External model requests are disabled in this synthetic fixture')


memory_assist.propose=edit_fixture
evidence_web.completion=no_external_requests


async def intake_link_fixture(url):
    # Only an explicit synthetic domain is available. No public network or real
    # campus pages are used by browser regression tests.
    if not url.startswith('https://notice-fixture.example/'):
        raise HTTPException(422,'合成验收只提供指定示例链接')
    if '/failure' in url:raise HTTPException(422,'示例链接暂时不可读取，请粘贴正文或上传原件')
    source=text_source('【合成链接材料】这是一则只需阅读的资料通知。\n材料标识：'+url)
    source['name']='合成通知原文'
    source['origin']={'url':url,'retrieved_at':int(time.time()),'attachments':[],
                      'warnings':['仅用于工程验收的合成网页内容。']}
    return source,'合成资料通知'


notice_intake.read_link=intake_link_fixture

def reply(settings, sources, messages, profile):
    quote=next((message['content'] for message in reversed(messages) if message['role']=='user'),'')
    result={'answer':'【工程测试回复】已收到这条测试消息；记忆结果以服务器回执为准，没有执行真实办理。',
            'citations':[],'image_sources':[],'memory_actions':[]}
    if quote=='【合成验收】输出代码块':
        result['answer']='以下是合成代码，仅用于组件验收。\n\n```python\nprint("组件验收 <safe>")\n```'
    elif quote=='【合成验收】长篇阅读':
        result['answer']='\n\n'.join(f'第 {index} 段：这是合成阅读材料，用于核对侧面板展开和侧栏变化时的位置。保留正在阅读的文字，继续查看后面的记录。' for index in range(1,61))
    if quote.startswith('记住，我的测试称呼'):
        result['memory_actions']=[{'operation':'remember','content':quote,'source_quote':quote,'kind':'fact'}]
    elif quote.startswith('我以后希望每次回答先给结论'):
        result['memory_actions']=[{'operation':'remember','content':'回答先给结论，再说明原因。','source_quote':quote,'kind':'preference','basis':'explicit','lifetime':'long_term'}]
    return result,{}

async def stream(settings,sources,messages,profile,tier):
    result,usage=reply(settings,sources,messages,profile)
    yield {'type':'delta','text':result['answer']}
    yield {'type':'complete','result':result,'usage':usage}

chat_ai.reply=reply
genui_ai.stream_reply=stream

if __name__=='__main__':
    import uvicorn
    seed()
    uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
