"""Loopback push acceptance: real API and worker, simulated delivery only."""
from memory_engine_preview_server import app, seed, PORT
from app import push_delivery
from types import SimpleNamespace
from app import source_sync
from app.documents import text_source
from fastapi import HTTPException

assert PORT == 8786
sent = []
source_revision = 1


async def source_index(config):
    if not config['url'].startswith('https://notice-fixture.example/'):
        raise HTTPException(422,'合成验收仅支持指定虚拟来源，不发起网络请求')
    return [{'url':'https://notice-fixture.example/info/fixture.htm','title':'合成官网通知','published_at':None}]


async def source_article(url):
    if url!='https://notice-fixture.example/info/fixture.htm':
        raise HTTPException(422,'不存在此合成原文')
    source=text_source('合成官网通知：请核对第 '+str(source_revision)+' 版办理要求。')
    source['origin']={'url':url,'retrieved_at':source_revision,'attachments':[],'warnings':[]}
    return source,'合成官网通知'


source_sync.fetch_index=source_index
source_sync.read_link=source_article


@app.post('/api/fixture/source-version')
def change_fixture_source():
    global source_revision
    source_revision+=1
    return {'synthetic':True,'revision':source_revision}

def simulated_delivery(device, payload, config):
    sent.append({'device_id': device['id'], 'user_id': device['user_id'], 'payload': payload})
    return SimpleNamespace(status_code=201)

push_delivery.deliver = simulated_delivery

@app.get('/api/fixture/push-deliveries')
def deliveries():
    return {'synthetic': True, 'deliveries': sent}

if __name__ == '__main__':
    import uvicorn
    seed()
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
