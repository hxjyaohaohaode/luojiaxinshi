"""Public GET transport: validate DNS once and connect to that exact IP.

TLS SNI and certificate validation still use the URL's hostname. Pinning the
socket avoids a second DNS lookup turning a checked public host into a LAN host.
"""
import asyncio
import ipaddress
import socket
import ssl

import certifi
import httpcore
import httpx


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, backend=None):
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in (80,443):
            raise httpcore.ConnectError('Public reader port is not allowed')
        try:
            async with asyncio.timeout(timeout if timeout is not None else 5):
                addresses = await asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM)
                ips = list(dict.fromkeys(a[4][0] for a in addresses))
                if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                    raise httpcore.ConnectError('Public reader refuses non-public addresses')
                last = None
                for ip in ips[:4]:
                    try:
                        return await self.backend.connect_tcp(ip,port,timeout,local_address,socket_options)
                    except (httpcore.ConnectError,httpcore.ConnectTimeout) as exc:
                        last = exc
                raise last or httpcore.ConnectError('Public reader could not connect')
        except TimeoutError:
            raise httpcore.ConnectTimeout('Public reader connection timed out') from None
        except (OSError,ValueError):
            raise httpcore.ConnectError('Public reader DNS lookup failed') from None

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError('Public reader refuses local sockets')

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class PublicHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        # HTTPX's pinned 0.28 adapter owns a httpcore pool. Keep its documented
        # response/error mapping, supplying the pool's public network_backend API.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=4,max_keepalive_connections=2,
            network_backend=PublicNetworkBackend())
