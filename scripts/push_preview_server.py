"""Loopback push acceptance: real API and worker, simulated delivery only."""
from memory_engine_preview_server import app, seed, PORT
from app import push_delivery
from types import SimpleNamespace
from app import source_sync
from app.documents import text_source
from fastapi import HTTPException
import os

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


@app.post('/api/fixture/qq-enable')
def enable_synthetic_qq():
    if os.getenv('QQ_GROUP_BROWSER_FIXTURE')!='1':
        raise HTTPException(404,'No synthetic QQ fixture')
    from mvp_preview_server import config
    from app import qq_group_media

    async def download(url):
        if url!='https://multimedia.nt.qq.com.cn/download?fileid=browser-synthetic':
            raise qq_group_media.AttachmentError('合成验收只提供指定原件')
        return '合成群通知原件，请核对课程资料。'.encode()

    qq_group_media.fetch_file=download
    config.qq_bot_app_id='qq-browser-synthetic'
    config.qq_bot_secret='qq-browser-signing-fixture'
    return {'synthetic':True}


def simulated_delivery(device, payload, config):
    sent.append({'device_id': device['id'], 'user_id': device['user_id'], 'payload': payload})
    return SimpleNamespace(status_code=201)

push_delivery.deliver = simulated_delivery

@app.get('/api/fixture/push-deliveries')
def deliveries():
    return {'synthetic': True, 'deliveries': sent}


def seed_pilot():
    from fastapi.testclient import TestClient
    from app.security import new_invite
    from synthetic_auth import verified_registration
    settings=app.state.settings
    with TestClient(app,base_url=settings.origin,headers={'Origin':settings.origin,'X-Requested-With':'campus-notice'}) as client:
        accounts=[('pilot-site','admin'),('pilot-counselor','user')]
        if os.getenv('SPRINT_BROWSER_FIXTURE')=='1':
            accounts.extend(('sprint-'+engine,'user') for engine in ['chromium','firefox','webkit'])
        for username,role in accounts:
            verified_registration(client,{'username':username,'display_name':username,
                'password':'PilotFixtureOnly2026!','accepted_terms':True,'invite':new_invite(app.state.db,role)})
            client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
        client.post('/api/auth/login',json={'username':'pilot-site','password':'PilotFixtureOnly2026!'}).raise_for_status()
        client.headers['X-CSRF-Token']=client.get('/api/session').json()['csrf']
        client.put('/api/campus/members/pilot-counselor',json={'college_id':'sres','role':'counselor',
            'version':0,'scopes':[{'grade':'2026级','class_name':'试点一班'}]}).raise_for_status()

    class Capture:
        codes={}
        def available(self,channel):
            return channel in {'sms','email'}
        def send_code(self,channel,target,code,purpose,request_id):
            if not (channel=='sms' and target.startswith('1399900') or channel=='email' and target.endswith('@example.invalid')):
                raise HTTPException(422,'仅允许隔离夹具的联系方式')
            self.codes[request_id]=code
            return 'synthetic-pilot-provider'
    app.state.verification.provider=Capture()


@app.get('/api/fixture/pilot-otp/{cid}')
def pilot_code(cid:str):
    provider=app.state.verification.provider
    if os.getenv('PILOT_BROWSER_FIXTURE')!='1' or cid not in getattr(provider,'codes',{}):
        raise HTTPException(404,'No synthetic challenge')
    return {'synthetic':True,'code':provider.codes[cid]}


if __name__ == '__main__':
    import uvicorn
    seed()
    if os.getenv('PILOT_BROWSER_FIXTURE')=='1':
        seed_pilot()
    uvicorn.run(app, host='127.0.0.1', port=PORT, access_log=False)
