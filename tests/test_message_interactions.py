"""Real database/API input receipts and isolation; provider is a recorded fixture."""
import uuid
import pytest
from app import chat_ai
from app.genui_state import context_text
from test_workflow import env,account
from test_workspace import conversation,send

@pytest.fixture
def chat(env,monkeypatch):
    env[1].ai_api_key='synthetic-no-network'
    seen=[]
    def reply(settings,sources,messages,profile):
        seen.append(messages)
        return {'answer':'原消息：活动是周五，正式时间仍需原文核对。','citations':[],'image_sources':[]},{'input_tokens':1,'output_tokens':1}
    monkeypatch.setattr(chat_ai,'reply',reply)
    client=account(env)
    return client,conversation(client),seen

def test_burst_keeps_each_message_and_calls_model_once(chat):
    c,detail,seen=chat
    extra=[{'content':'第二条：只看本周。','request_id':uuid.uuid4().hex},{'content':'第三条：把地点也列出来。','request_id':uuid.uuid4().hex}]
    result,payload=send(c,detail,'第一条：整理讲座。',additional_messages=extra)
    assert [m['content'] for m in result['messages'] if m['role']=='user']==['第一条：整理讲座。',*[i['content'] for i in extra]]
    assert len(seen)==1 and len([m for m in result['messages'] if m['role']=='assistant'])==1
    assert [m['client_request_id'] for m in result['messages'] if m['role']=='user']==[payload['request_id'],*[i['request_id'] for i in extra]]
    again=c.post('/api/conversations/'+detail['id']+'/messages',json=payload)
    assert again.status_code==200 and again.json()==result and len(seen)==1
    changed={**payload,'additional_messages':[{**extra[0],'content':'伪装成同一消息的不同内容'},extra[1]]}
    assert c.post('/api/conversations/'+detail['id']+'/messages',json=changed).status_code==409

def test_quote_is_server_checked_context_and_survives_reload(chat):
    c,detail,seen=chat
    detail,_=send(c,detail,'这次活动安排是什么？')
    old=detail['messages'][-1]
    quote={'message_id':old['id'],'excerpt':'活动是周五'}
    result,_=send(c,detail,'这句话有原文依据吗？',reply_to=quote)
    user=[m for m in result['messages'] if m['role']=='user'][-1]
    assert user['reply_to']=={**quote,'role':'assistant'}
    assert '不是官方证据' in context_text(seen[-1][-1]) and '活动是周五' in context_text(seen[-1][-1])
    assert c.get('/api/conversations/'+detail['id']).json()['messages'][-2]['reply_to']==user['reply_to']
    body={'version':result['version'],'content':'伪造引文','request_id':uuid.uuid4().hex,'reply_to':{**quote,'excerpt':'活动是周日'}}
    assert c.post('/api/conversations/'+detail['id']+'/messages',json=body).status_code==422
    assert len(seen)==2

def test_quote_cannot_cross_conversations_or_accounts(chat,env):
    c,detail,_=chat
    detail,_=send(c,detail,'原消息')
    other=conversation(c)
    body={'version':other['version'],'content':'引用','request_id':uuid.uuid4().hex,'reply_to':{'message_id':detail['messages'][0]['id']}}
    assert c.post('/api/conversations/'+other['id']+'/messages',json=body).status_code==404
    foreign=account(env,'other-owner')
    assert foreign.put('/api/conversations/'+detail['id']+'/messages/'+detail['messages'][0]['id']+'/emoji',json={'emoji':'👍','active':True}).status_code==404

def test_emoji_feedback_is_idempotent_and_not_model_input(chat):
    c,detail,seen=chat
    detail,_=send(c,detail,'原消息')
    for message in detail['messages']:
        url='/api/conversations/'+detail['id']+'/messages/'+message['id']+'/emoji'
        for _ in range(2):assert c.put(url,json={'emoji':'🎉','active':True}).json()=={'emojis':['🎉']}
        loaded=c.get('/api/conversations/'+detail['id']).json()
        assert next(m for m in loaded['messages'] if m['id']==message['id'])['emojis']==['🎉']
        assert c.put(url,json={'emoji':'🎉','active':False}).json()=={'emojis':[]}
        assert c.put(url,json={'emoji':'untrusted','active':True}).status_code==422
    assert len(seen)==1
    snapshot=c.get('/api/conversations/'+detail['id']+'/message-feedback').json()
    assert snapshot['emojis']=={} and snapshot['reactions']=={} and len(snapshot['signature'])==24

def test_invalid_later_fragment_rolls_back_whole_batch(chat):
    c,detail,seen=chat
    body={'version':detail['version'],'content':'不应部分存入','request_id':uuid.uuid4().hex,
          'additional_messages':[{'content':'引用别的对话','request_id':uuid.uuid4().hex,'reply_to':{'message_id':'missing'}}]}
    assert c.post('/api/conversations/'+detail['id']+'/messages',json=body).status_code==404
    assert c.get('/api/conversations/'+detail['id']).json()['messages']==[] and not seen

def test_quote_is_not_promoted_into_user_evidence_or_duplicated_by_history_packing(chat,env):
    from app.context_engine import pack_history
    from app.grounding import retrieve
    c,detail,_=chat
    messages=[{'id':'test-question','role':'user','content':'这句话有证据吗？',
        'reply_to':{'message_id':'old-answer','role':'assistant','excerpt':'官方要求在2099年1月1日18:00缴费'}}]
    packed,excerpts,_=pack_history(messages)
    assert context_text(packed[0]).count('2099年1月1日')==1
    assert '2099年1月1日' not in context_text(packed[0],include_quote=False)
    uid=c.get('/api/session').json()['user']['id']
    records,_=retrieve(env[0].state.db,uid,detail['id'],[],packed,{'_history_excerpts':excerpts},['缴费'])
    user_proof='\n'.join(s['text'] for r in records if r['evidence_kind']=='user_input' for s in r['sections'])
    assert '2099年1月1日' not in user_proof and '这句话有证据吗' in user_proof

def test_portable_export_and_import_preserve_quotes_and_emojis_without_old_account_links(chat,env):
    c,detail,_=chat
    detail,_=send(c,detail,'原文问题')
    old=detail['messages'][-1]
    detail,_=send(c,detail,'请核对这句',reply_to={'message_id':old['id'],'excerpt':'活动是周五'})
    assert c.put('/api/conversations/'+detail['id']+'/messages/'+old['id']+'/emoji',json={'emoji':'❤️','active':True}).status_code==200
    archive=c.get('/api/export').json()
    target=account(env,'import-owner')
    preview=target.post('/api/import',json={'data':archive});assert preview.status_code==200,preview.text
    committed=target.post('/api/import',json={'data':archive,'digest':preview.json()['digest'],'confirm':True});assert committed.status_code==200,committed.text
    imported_id=target.get('/api/conversations').json()[0]['id']
    imported=target.get('/api/conversations/'+imported_id).json()
    quoted=next(m for m in imported['messages'] if m.get('reply_to'))
    assert quoted['reply_to']['excerpt']=='活动是周五' and quoted['reply_to']['message_id']!=old['id']
    assert any(m.get('emojis')==['❤️'] for m in imported['messages'])
    assert c.get('/api/conversations/'+imported_id).status_code==404

def test_branch_rebases_message_references_and_keeps_feedback_independent(chat):
    c,detail,_=chat
    detail,_=send(c,detail,'原消息')
    original=detail['messages'][-1]
    detail,_=send(c,detail,'引用继续',reply_to={'message_id':original['id'],'excerpt':'活动是周五'})
    latest=detail['messages'][-1]
    c.put('/api/conversations/'+detail['id']+'/messages/'+original['id']+'/emoji',json={'emoji':'👍','active':True}).raise_for_status()
    result=c.post('/api/conversations/'+detail['id']+'/messages/'+latest['id']+'/branch',json={'version':detail['version'],'request_id':uuid.uuid4().hex})
    assert result.status_code==200,result.text
    branch=result.json();quote=next(m['reply_to'] for m in branch['messages'] if m.get('reply_to'))
    assert quote['message_id']!=original['id'] and quote['message_id'] in {m['id'] for m in branch['messages']}
    assert quote['excerpt']=='活动是周五'
    assert any(m.get('emojis')==['👍'] for m in branch['messages'])

def test_invalid_later_input_cannot_interrupt_an_accepted_stream(env,monkeypatch):
    import asyncio,threading
    from concurrent.futures import ThreadPoolExecutor
    from app import genui_ai
    from test_genui_transport import payload,events
    c=account(env);detail=conversation(c);env[1].ai_api_key='synthetic-no-network'
    started,release=threading.Event(),threading.Event()
    async def response(*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.01)
        yield {'type':'delta','text':'原回复完整保留。'}
        yield {'type':'complete','result':{'answer':'原回复完整保留。','citations':[],'image_sources':[]},'usage':{}}
    monkeypatch.setattr(genui_ai,'stream_reply',response)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(c.post,'/api/conversations/'+detail['id']+'/messages/stream',json=payload(detail))
        assert started.wait(5)
        current=c.get('/api/conversations/'+detail['id']).json();original=current['messages'][-1]
        bad=payload(current,steer_message_id=original['id'],additional_messages=[{'content':'无效的后续附件','request_id':uuid.uuid4().hex,'source_ids':['not-owned']}])
        rejected=c.post('/api/conversations/'+detail['id']+'/messages/stream',json=bad)
        try:
            assert rejected.status_code==422,rejected.text
            assert c.get('/api/conversations/'+detail['id']).json()['messages'][-1]['status']=='processing'
        finally:release.set()
        final=events(future.result(timeout=10))[-1]['data']['conversation']
        assert final['messages'][-1]['status']=='complete' and len(final['messages'])==2
