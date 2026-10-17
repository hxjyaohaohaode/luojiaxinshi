"""The public evidence reader must never connect to a re-resolved/private host."""
import asyncio
import socket

import httpcore
import pytest

from app.public_http import PublicNetworkBackend, PublicHTTPTransport


def test_checked_ip_is_the_socket_target_even_if_a_hostname_would_rebind(monkeypatch):
    async def run():
        calls=[];dns=[]
        class Backend:
            async def connect_tcp(self,*args):calls.append(args);return 'stream'
        async def resolve(host,port,**kwargs):
            dns.append((host,port));return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',port))]
        monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',resolve)
        reader=PublicNetworkBackend(Backend())
        assert await reader.connect_tcp('news.example.com',443,5)=='stream'
        assert dns==[('news.example.com',443)] and calls[0][:2]==('93.184.216.34',443)
    asyncio.run(run())


@pytest.mark.parametrize('addresses',[['127.0.0.1'],['10.0.0.1'],['169.254.169.254'],['::1'],['93.184.216.34','192.168.1.1']])
def test_private_or_mixed_dns_is_rejected_before_any_connection(monkeypatch,addresses):
    async def run():
        class Backend:
            async def connect_tcp(self,*args):raise AssertionError('must not reach a socket')
        async def resolve(host,port,**kwargs):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,port)) for ip in addresses]
        monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',resolve)
        with pytest.raises(httpcore.ConnectError):await PublicNetworkBackend(Backend()).connect_tcp('public.example.com',443,5)
    asyncio.run(run())


def test_transport_preserves_httpx_adapter_and_rejects_other_socket_types():
    transport=PublicHTTPTransport()
    assert isinstance(transport._pool,httpcore.AsyncConnectionPool)
    async def run():
        with pytest.raises(httpcore.ConnectError):await PublicNetworkBackend().connect_unix_socket('/tmp/private')
        with pytest.raises(httpcore.ConnectError):await PublicNetworkBackend().connect_tcp('example.com',8080)
        await transport.aclose()
    asyncio.run(run())
