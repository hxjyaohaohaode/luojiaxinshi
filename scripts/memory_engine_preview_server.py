"""Loopback-only memory UI fixture with an explicitly simulated provider."""
from mvp_preview_server import app, seed, PORT
from app import chat_ai, genui_ai
from dataclasses import replace
from app import memory_assist,evidence_web

assert PORT == 8786, 'Memory fixture must use its own loopback port'
app.state.settings=replace(app.state.settings,ai_api_key='synthetic-fixture-only',notice_semantic_review=False)


async def edit_fixture(settings,selection,instruction):
    if instruction.startswith('替换为：'):return instruction.removeprefix('替换为：')
    raise ValueError('Only a literal fixture replacement is supported')


async def no_external_requests(*args,**kwargs):
    raise RuntimeError('External model requests are disabled in this synthetic fixture')


memory_assist.propose=edit_fixture
evidence_web.completion=no_external_requests

def reply(settings, sources, messages, profile):
    quote=next((message['content'] for message in reversed(messages) if message['role']=='user'),'')
    result={'answer':'【工程测试回复】已收到这条测试消息；记忆结果以服务器回执为准，没有执行真实办理。',
            'citations':[],'image_sources':[],'memory_actions':[]}
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
