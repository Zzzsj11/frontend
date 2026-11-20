"""ASGI entry point shared by the API image and the legacy-image rollback launcher."""

import asyncio
import ipaddress
import os
import socket
from time import monotonic

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

_CACHE_SECONDS = 5
_RETRY_SECONDS = 1
_FORWARDED_HEADERS = {b"x-forwarded-for", b"x-forwarded-proto"}


async def _frontend_addresses() -> set[str]:
    # An absolute DNS name avoids appending a host search domain before the
    # service exists. Docker's embedded resolver serves the frontend alias.
    records = await asyncio.get_running_loop().getaddrinfo("frontend.", None, type=socket.SOCK_STREAM)
    return {record[4][0] for record in records}


class TrustedProxyHeaders:
    def __init__(self, app, *, compose_frontend: bool, networks: str):
        self.app = app
        self.compose_frontend = compose_frontend
        self.static = []
        for token in networks.split(","):
            token = token.strip()
            if token:
                address = ipaddress.ip_network(token) if "/" in token else ipaddress.ip_address(token)
                self.static.append(str(address))
        self.middleware = ProxyHeadersMiddleware(app, trusted_hosts=self.static)
        self.addresses = set()
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def _refresh(self):
        async with self.lock:
            if monotonic() < self.expires:
                return
            try:
                addresses = await asyncio.wait_for(_frontend_addresses(), timeout=1)
            except (OSError, TimeoutError):
                addresses = set()
            if self.addresses != addresses:
                self.middleware = ProxyHeadersMiddleware(self.app, trusted_hosts=[*self.static, *addresses])
                self.addresses = addresses
            self.expires = monotonic() + (_CACHE_SECONDS if addresses else _RETRY_SECONDS)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"} or not any(name in _FORWARDED_HEADERS for name, _ in scope["headers"]):
            return await self.app(scope, receive, send)
        if self.compose_frontend and monotonic() >= self.expires:
            await self._refresh()
        return await self.middleware(scope, receive, send)


def create_app():
    from app.main import app

    return TrustedProxyHeaders(app, compose_frontend=os.getenv("TRUST_COMPOSE_FRONTEND") == "1", networks=os.getenv("TRUSTED_PROXY_NETWORKS", ""))
