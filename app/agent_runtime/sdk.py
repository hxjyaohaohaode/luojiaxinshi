"""Authenticated async Python SDK. Shares the application's owner/CSRF checks."""
import json
import re
from urllib.parse import urlsplit
import uuid

import httpx

TERMINAL = {'turn.completed', 'turn.failed', 'turn.cancelled', 'turn.interrupted', 'turn.discarded'}


class Client:
    def __init__(self, base_url='http://127.0.0.1:8765', *, transport=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('base_url must be an application origin')
        if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Remote SDK connections require HTTPS')
        self.http = httpx.AsyncClient(base_url=base_url.rstrip('/'), timeout=httpx.Timeout(30, read=90),
            headers={'Origin': base_url.rstrip('/'), 'X-Requested-With': 'campus-notice'},
            follow_redirects=False, trust_env=False, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def request(self, method, path, **kwargs):
        response = await self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def login(self, username, password):
        await self.request('POST', '/api/auth/login', json={'username': username, 'password': password})
        session = await self.request('GET', '/api/session')
        self.http.headers['X-CSRF-Token'] = session['csrf']
        return session['user']

    async def start_thread(self, **options):
        thread = await self.request('POST', '/api/agent/threads', json=options)
        return Thread(self, thread['id'])

    def resume_thread(self, thread_id):
        return Thread(self, thread_id)

    async def start_conversation(self, title='新的校园对话'):
        chat = await self.request('POST', '/api/conversations', json={'title': title})
        return self.conversation(chat['id'])

    def conversation(self, conversation_id):
        """Use the same Agent, evidence review and history as the existing chat UI."""
        return Conversation(self, conversation_id)


class Conversation:
    def __init__(self, client, conversation_id):
        if not re.fullmatch(r'[0-9a-f]{32}', conversation_id):
            raise ValueError('Invalid conversation ID')
        self.client, self.id = client, conversation_id
        self.path = '/api/conversations/' + conversation_id

    async def read(self):
        return await self.client.request('GET', self.path)

    async def approve(self, approval_id, digest, decision):
        return await self.client.request('POST', self.path + '/agent/approvals/' + approval_id,
                                         json={'digest': digest, 'decision': decision})

    async def interrupt(self):
        chat = await self.read()
        return await self.client.request('POST', self.path + '/cancel', json={'version': chat['version']})

    async def run_streamed(self, prompt, *, allow_external_processing=False, request_id=None):
        chat = await self.read()
        body = {'version': chat['version'], 'content': prompt, 'request_id': request_id or uuid.uuid4().hex,
                'allow_external_processing': allow_external_processing}
        async with self.client.http.stream('POST', self.path + '/messages/stream', json=body) as response:
            response.raise_for_status()
            kind, seq = '', ''
            async for line in response.aiter_lines():
                if line.startswith('event: '):kind = line[7:]
                elif line.startswith('id: '):seq = line[4:]
                elif line.startswith('data: '):
                    yield {'type': kind, 'seq': int(seq), 'data': json.loads(line[6:])}

    async def run(self, prompt, *, on_approval=None, **options):
        terminal, events, resolved = None, [], set()
        async for item in self.run_streamed(prompt, **options):
            events.append(item)
            if item['type'] == 'agent':
                for approval in (item['data'].get('state') or {}).get('approvals', []):
                    if approval['id'] in resolved:continue
                    decision = await on_approval(approval) if on_approval else 'deny'
                    await self.approve(approval['id'], approval['digest'], decision if decision in ('approve', 'deny') else 'deny')
                    resolved.add(approval['id'])
            if item['type'] == 'done':terminal = item['data']['conversation']
        if terminal is None:
            raise RuntimeError('Event connection ended; use conversation.read() to reconcile the persisted reply before retrying')
        message = next(m for m in reversed(terminal['messages']) if m['role'] == 'assistant')
        return {'conversation_id': self.id, 'message_id': message['id'], 'status': message['status'],
                'final_response': message['content'] if message['status'] == 'complete' else '', 'error': message['error'],
                'grounding': message.get('grounding'), 'events': events}


class Thread:
    def __init__(self, client, thread_id):
        if not re.fullmatch(r'[0-9a-f]{32}', thread_id):
            raise ValueError('Invalid thread ID')
        self.client, self.id = client, thread_id
        self.path = '/api/agent/threads/' + thread_id

    async def read(self):
        return await self.client.request('GET', self.path)

    async def approve(self, approval_id, digest, decision):
        return await self.client.request('POST', self.path + '/approvals/' + approval_id, json={'digest': digest, 'decision': decision})

    async def interrupt(self, turn_id):
        return await self.client.request('POST', self.path + '/turns/' + turn_id + '/interrupt')

    async def run_streamed(self, prompt, *, allow_external_processing=False, request_id=None):
        run = await self.client.request('POST', self.path + '/turns', json={'prompt': prompt,
            'request_id': request_id or uuid.uuid4().hex, 'allow_external_processing': allow_external_processing})
        async for item in self.events(run['id']):
            yield item

    async def events(self, turn_id, after=0):
        """Reconnect with the last delivered seq; never re-submit a paid turn."""
        async with self.client.http.stream('GET', self.path + '/stream', params={'after': after}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith('data: '):
                    item = json.loads(line[6:])
                    if item['turn_id'] != turn_id:
                        continue
                    yield item
                    if item['type'] in TERMINAL:
                        return

    async def run(self, prompt, *, on_approval=None, **options):
        items, final = [], None
        async for item in self.run_streamed(prompt, **options):
            items.append(item)
            if item['type'] == 'approval.requested':
                # Programmatic execution defaults to refusal. A callback must
                # explicitly inspect the exact tool, arguments and digest.
                decision = await on_approval(item['data']) if on_approval else 'deny'
                if decision not in {'approve', 'deny'}:
                    decision = 'deny'
                await self.approve(item['data']['id'], item['data']['digest'], decision)
            if item['type'] in TERMINAL:
                final = item['data']
        if final is None:
            raise RuntimeError('Event connection ended without a terminal event; reconnect using the last seq')
        return {'thread_id': self.id, 'status': final['status'], 'final_response': final['answer'],
                'error': final['error'], 'usage': final['usage'], 'events': items}
