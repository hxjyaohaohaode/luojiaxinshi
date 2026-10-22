"""Bounded OpenAI-compatible tool protocol; explicit MiMo/loopback OSS selection."""
import ipaddress
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx

from .types import AgentError


def loopback_url(url):
    parsed = urlsplit(url)
    try:
        local = ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        local = parsed.hostname == 'localhost'
    if not local or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('本地模型地址须为回环地址，不能包含凭证、查询或片段')
    return url.rstrip('/')


class Provider:
    def __init__(self, settings, kind):
        self.settings, self.kind = settings, kind
        self.reuse_connections, self._client = False, None
        if kind == 'oss':
            self.url = loopback_url(settings.agent_oss_url)
            self.model, self.key = settings.agent_oss_model, ''
            if not self.model:
                raise AgentError('本地模型尚未配置：请设置 AGENT_OSS_MODEL 并启动 Ollama 或 LM Studio')
        elif kind == 'mimo':
            from ..model_catalog import validate
            validate(settings)
            self.url, self.model, self.key = settings.ai_base_url, settings.ai_model, settings.ai_api_key
            if not self.key:
                raise AgentError('小米模型尚未配置，请先设置 MIMO_API_KEY')
        else:
            raise AgentError('不支持的模型服务')

    @asynccontextmanager
    async def client(self):
        options = dict(timeout=httpx.Timeout(self.settings.ai_timeout, connect=10), follow_redirects=False, trust_env=False)
        if self.reuse_connections:
            if self._client is None:
                self._client = httpx.AsyncClient(**options)
            yield self._client
        else:
            async with httpx.AsyncClient(**options) as client:
                yield client

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def complete(self, messages, tools):
        return await self._request(messages, tools)

    async def complete_stream(self, messages, tools, on_text, *, on_answer_arguments=None):
        return await self._request(messages, tools, on_text, on_answer_arguments)

    async def _request(self, messages, tools, on_text=None, on_answer_arguments=None):
        payload = {'model': self.model, 'messages': messages, 'stream': False,
                   'tools': tools, 'tool_choice': 'auto', 'max_tokens': 4096}
        if self.kind == 'mimo':
            payload.pop('max_tokens')
            payload.update(max_completion_tokens=8192, thinking={'type': 'disabled'}, temperature=0.2)
            # The embedded chat has a typed final-answer tool. Requiring a
            # call here avoids paying to repair an unstructured plain-text
            # answer. Children and the SDK/OSS loop keep their own completion
            # contract; this does not force searches or extra planning steps.
            if any(tool['function']['name'] == 'submit_answer' for tool in tools):
                payload['tool_choice'] = 'required'
        if on_text:
            payload.update(stream=True, stream_options={'include_usage': True})
        headers = {'Authorization': 'Bearer ' + self.key} if self.key else {}
        try:
            async with self.client() as client:
                async with client.stream('POST', self.url + '/chat/completions', json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        raise AgentError(f'模型服务返回 HTTP {response.status_code}；未自动重试，请核对配置与额度')
                    if on_text:
                        data = await stream_message(response, on_text, on_answer_arguments)
                    else:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 1048576:
                                raise AgentError('模型响应超过 1 MB，已停止读取')
                        data = json.loads(body)
            choice = data['choices'][0]
            if choice.get('finish_reason') not in {'stop', 'tool_calls'}:
                raise AgentError('模型响应未完整结束，未执行其中的工具')
            msg = choice['message']
            if msg.get('content') is not None and not isinstance(msg['content'], str):
                raise ValueError('content')
            calls = msg.get('tool_calls') or []
            if not isinstance(calls, list) or len(calls) > 8:
                raise ValueError('calls')
            ids = set()
            for call in calls:
                if call.get('type') != 'function' or not isinstance(call.get('id'), str) or not call['id'] or len(call['id']) > 128 or call['id'] in ids:
                    raise ValueError('call id')
                ids.add(call['id'])
                fn = call['function']
                if not isinstance(fn.get('name'), str) or not isinstance(fn.get('arguments'), str) or len(fn['arguments'].encode()) > 64000:
                    raise ValueError('function')
            usage = data.get('usage') or {}
            safe_usage = {key: max(0, int(usage.get(key) or 0)) for key in ('prompt_tokens', 'completion_tokens')}
            for field, detail, total in (('prompt_tokens_details', 'cached_tokens', 'prompt_tokens'),
                                         ('completion_tokens_details', 'reasoning_tokens', 'completion_tokens')):
                if isinstance(usage.get(field), dict) and detail in usage[field]:
                    safe_usage[field] = {detail: min(safe_usage[total], max(0, int(usage[field][detail] or 0)))}
            # Hidden reasoning is neither exposed as an event nor persisted.
            return {'role': 'assistant', 'content': msg.get('content') or '', **({'tool_calls': calls} if calls else {})}, safe_usage
        except AgentError:
            raise
        except httpx.HTTPError:
            raise AgentError('模型连接失败或超时；请求可能已计费，未自动重试') from None
        except (ValueError, TypeError, KeyError, IndexError):
            raise AgentError('模型未返回兼容的完整工具协议；未执行本次工具') from None


async def stream_message(response, on_text, on_answer_arguments=None):
    """Buffer tools until a complete finish; optionally decode submit's answer.

The argument callback feeds AnswerDecoder, never the raw UI or other tools.
Nothing is executed or published by either preview callback.
"""
    import codecs
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer, content, calls, usage, finish, size = '', '', {}, {}, None, 0
    previewed_arguments = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > 8 * 1048576:
            raise AgentError('模型流超过大小限制')
        buffer += decoder.decode(chunk)
        if len(buffer) > 262144:
            raise AgentError('模型流数据行过长')
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            if not line.startswith('data:'):continue
            value = line[5:].strip()
            if value == '[DONE]':continue
            packet = json.loads(value)
            usage = packet.get('usage') or usage
            for choice in packet.get('choices', []):
                if choice.get('index', 0) != 0:continue
                finish = choice.get('finish_reason') or finish
                delta = choice.get('delta', {})
                text = delta.get('content') or ''
                if not isinstance(text, str):raise ValueError('content')
                if text:
                    content += text
                    if len(content.encode()) > 1048576:raise ValueError('content_limit')
                    on_text(text)
                for part in delta.get('tool_calls') or []:
                    index = part['index']
                    if type(index) is not int or not 0 <= index < 8:raise ValueError('call_limit')
                    call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                    if part.get('id'):call['id'] += part['id']
                    if part.get('type'):call['type'] = part['type']
                    for key in ('name', 'arguments'):
                        call['function'][key] += (part.get('function') or {}).get(key) or ''
                    if len(call['function']['arguments'].encode()) > 64000 or len(call['function']['name']) > 128:
                        raise ValueError('call_limit')
                    if on_answer_arguments and index == 0 and call['function']['name'] in ('submit_answer', 'submit_interface'):
                        arguments = call['function']['arguments']
                        if len(arguments) > previewed_arguments:
                            on_answer_arguments(arguments[previewed_arguments:])
                            previewed_arguments = len(arguments)
    if decoder.decode(b'', final=True) or buffer.strip():raise ValueError('incomplete_stream')
    return {'choices': [{'finish_reason': finish, 'message': {'content': content, 'tool_calls': [calls[k] for k in sorted(calls)]}}], 'usage': usage}
