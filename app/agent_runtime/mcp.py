"""Small bounded Streamable HTTP MCP client for administrator-defined servers.

Every tool invocation requires explicit approval. Server readOnlyHint is never
used as authorization. Stdio spawning and OAuth provisioning are not supported.
"""
import json
import os
import re
from urllib.parse import urlsplit

import httpx

from .providers import loopback_url
from .types import AgentError


def validate_servers(servers):
    if not isinstance(servers, dict) or len(servers) > 8:
        raise ValueError('AGENT_MCP_SERVERS_JSON 最多配置 8 个服务器')
    for name, server in servers.items():
        if not re.fullmatch(r'[a-z0-9_-]{1,64}', name) or not isinstance(server, dict) or set(server) - {'url', 'token_env', 'tools'}:
            raise ValueError('MCP 配置格式无效')
        url = urlsplit(server.get('url', ''))
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('MCP 地址不能包含凭证、查询或片段')
        if url.scheme != 'https':
            loopback_url(server.get('url', ''))
        token_env = server.get('token_env', '')
        if token_env and not re.fullmatch(r'AGENT_MCP_[A-Z0-9_]+', token_env):
            raise ValueError('MCP 凭证变量必须以 AGENT_MCP_ 开头')
        allowed = server.get('tools', [])
        if not isinstance(allowed, list) or len(allowed) > 100 or any(not isinstance(t, str) or not t or len(t) > 128 for t in allowed):
            raise ValueError('MCP tools 必须为明确允许的工具名称列表')
    return servers


class MCP:
    def __init__(self, config, transport=None):
        self.config, self.transport = validate_servers(config), transport

    async def request(self, name, method, params):
        if name not in self.config:
            raise AgentError('MCP 服务器未获维护者配置')
        server = self.config[name]
        if method == 'tools/call' and params['name'] not in server.get('tools', []):
            raise AgentError('MCP 工具不在维护者允许列表中')
        headers = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}
        if server.get('token_env'):
            token = os.getenv(server['token_env'], '')
            if not token:
                raise AgentError('MCP 凭证未配置')
            headers['Authorization'] = 'Bearer ' + token
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                async def rpc(method, params, key):
                    body = {'jsonrpc': '2.0', 'method': method, 'params': params}
                    if key is not None:
                        body['id'] = key
                    async with client.stream('POST', server['url'], json=body, headers=headers) as response:
                        if response.status_code not in {200, 202, 204}:
                            raise AgentError(f'MCP 返回 HTTP {response.status_code}，未自动重试')
                        session = response.headers.get('Mcp-Session-Id')
                        if session:
                            if len(session) > 512:
                                raise AgentError('MCP 会话标识过长')
                            headers['Mcp-Session-Id'] = session
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 256000:
                                raise AgentError('MCP 响应超过上限')
                            if key is not None and 'text/event-stream' in response.headers.get('content-type', ''):
                                normalized = data.decode('utf-8', errors='replace').replace('\r\n', '\n')
                                for frame in normalized.split('\n\n')[:-1]:
                                    value = '\n'.join(line[5:].lstrip() for line in frame.splitlines() if line.startswith('data:'))
                                    if value:
                                        item = json.loads(value)
                                        if item.get('id') == key:
                                            return result(item, key)
                        if key is None:
                            return {}
                        return result(json.loads(data), key)

                def result(item, key):
                    if item.get('id') != key or item.get('jsonrpc') != '2.0' or 'error' in item or 'result' not in item:
                        raise AgentError('MCP 返回错误或不匹配的请求结果')
                    return item['result']

                init = await rpc('initialize', {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'campus-agent', 'version': '1'}}, 1)
                if init.get('protocolVersion') not in {'2024-11-05', '2025-03-26', '2025-06-18'}:
                    raise AgentError('MCP 协议版本不受当前适配器支持')
                headers['MCP-Protocol-Version'] = init['protocolVersion']
                await rpc('notifications/initialized', {}, None)
                if method == 'tools/list':
                    collected, cursor = [], None
                    seen = set()
                    for index in range(5):
                        page = await rpc('tools/list', {'cursor': cursor} if cursor else {}, index + 2)
                        collected.extend(t for t in page.get('tools', []) if t.get('name') in server.get('tools', []))
                        cursor = page.get('nextCursor')
                        if not cursor:
                            return {'tools': collected[:100]}
                        if cursor in seen:
                            raise AgentError('MCP 工具分页重复')
                        seen.add(cursor)
                    return {'tools': collected[:100], 'truncated': True}
                return await rpc(method, params, 2)
        except AgentError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise AgentError('MCP 连接失败或响应协议无效，未自动重试') from None
