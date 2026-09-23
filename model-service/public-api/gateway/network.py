"""Public-only media connections, pinned after DNS validation (including redirects)."""

import asyncio
import ipaddress
import os
import socket
import time

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

_cache = {}


async def public_addresses(host: str, port: int):
    key = (host, port)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if os.getenv("MEDIA_DNS_OVER_HTTPS") == "true":
            # Fixed resolver, configured proxy is used for DNS only, never for untrusted media URLs.
            async with httpx.AsyncClient(proxy=os.getenv("MEDIA_DNS_PROXY") or None, timeout=20, trust_env=False) as client:
                response = await client.get("https://dns.google/resolve", params={"name": host, "type": "A"})
                response.raise_for_status()
                addresses = [a["data"] for a in response.json().get("Answer", []) if a.get("type") == 1]
        else:
            records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(r[4][0] for r in records))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Media destination must resolve exclusively to public IP addresses")
    _cache[key] = (time.monotonic() + 30, addresses)
    return addresses


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.backend = AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = await public_addresses(host, port)
        # HTTP Core retains the original hostname for TLS SNI/certificate verification.
        return await self.backend.connect_tcp(addresses[0], port, timeout, local_address, socket_options)

    async def connect_unix_socket(self, *args, **kwargs):
        raise ValueError("Unix sockets are not media destinations")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


def media_client():
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    # httpx 0.28 / httpcore 1.x pin: keep this covered by connection contract tests.
    transport._pool._network_backend = PublicNetworkBackend()
    return httpx.AsyncClient(transport=transport, timeout=180, follow_redirects=False, trust_env=False)
