"""Isolated engineering fixtures only; not imported by the application."""
from pathlib import Path
from app.db import ident


def verified_registration(client, payload):
    app=client.app
    settings=app.state.settings
    root=Path(__file__).resolve().parent.parent
    if settings.production or settings.data_dir.resolve()==(root/'data').resolve():
        raise RuntimeError('Synthetic auth is prohibited on production or the real local data directory')
    destination='fixture-'+ident()+'@example.invalid'
    class Capture:
        def __init__(self):self.codes={}
        def available(self, channel):return channel=='email'
        def send_code(self,channel,target,code,purpose,request_id):
            if channel!='email' or not target.endswith('@example.invalid'):raise RuntimeError('Synthetic addresses only')
            self.codes[request_id]=code;return 'isolated-fixture'
    provider=Capture();app.state.verification.provider=provider
    sent=client.post('/api/auth/challenges',json={'purpose':'register','channel':'email','destination':destination,'invite':payload.get('invite','')})
    sent.raise_for_status();cid=sent.json()['challenge_id']
    checked=client.post('/api/auth/verify',json={'challenge_id':cid,'code':provider.codes[cid]})
    checked.raise_for_status()
    response=client.post('/api/auth/register',json={**payload,'verification_token':checked.json()['verification_token']})
    response.raise_for_status()
    return response
