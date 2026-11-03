"""Explicitly isolated delivery double. Never configured by environment or HTTP."""
class CapturedMessages:
    def __init__(self):self.codes={};self.mail=[]
    def available(self, channel):return True
    def send_code(self, channel, destination, code, purpose, request_id):
        self.codes[request_id]=code
        return 'synthetic-provider-receipt'
    def send_mail(self,destination,subject,body):
        self.mail.append((destination,subject,body));return 'synthetic-mail-receipt'


def install_capture(app):
    app.state.verification.provider=CapturedMessages()
    return app.state.verification.provider


def proof(client,purpose='register',destination='fixture@example.invalid',channel='email',invite='',username=''):
    app=client.app
    if not isinstance(app.state.verification.provider,CapturedMessages):install_capture(app)
    response=client.post('/api/auth/challenges',json={'purpose':purpose,'channel':channel,'destination':destination,'invite':invite,'username':username})
    assert response.status_code==200,response.text
    cid=response.json()['challenge_id']
    verified=client.post('/api/auth/verify',json={'challenge_id':cid,'code':app.state.verification.provider.codes[cid]})
    assert verified.status_code==200,verified.text
    return verified.json()['verification_token']


def advance_cooldown(app):
    with app.state.db.connect(write=True) as conn:
        conn.execute("DELETE FROM limits WHERE key LIKE 'otp-cooldown:%'")
