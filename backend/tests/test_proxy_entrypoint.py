import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from starlette.responses import JSONResponse

from app import proxy_entrypoint

ROOT = Path(__file__).resolve().parents[2]


async def echo(scope, receive, send):
    response = JSONResponse([scope["client"][0], scope["scheme"]])
    await response(scope, receive, send)


async def request(app, peer, chain="203.0.113.42"):
    transport = httpx.ASGITransport(app=app, client=(peer, 4000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        headers = {} if chain is None else {"X-Forwarded-For": chain, "X-Forwarded-Proto": "https"}
        return (await client.get("/", headers=headers)).json()


@pytest.fixture(params=["image", "rollback"])
def launcher(request, monkeypatch):
    # A prior image only needs its original app.main:app. Exercise the actual
    # file and import path supplied by the rollback Compose overlay as well.
    main = ModuleType("app.main")
    main.app = echo
    monkeypatch.setitem(sys.modules, "app.main", main)
    monkeypatch.delenv("TRUST_COMPOSE_FRONTEND", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_NETWORKS", raising=False)
    if request.param == "image":
        command = (ROOT / "backend/docker-entrypoint.sh").read_text()
        assert "uvicorn app.proxy_entrypoint:create_app --factory" in command and "--no-proxy-headers" in command
        return proxy_entrypoint
    overlay = yaml.safe_load((ROOT / "docker-compose.rollback.yml").read_text())
    backend = overlay["services"]["backend"]
    config = backend["configs"][0]
    module, factory = backend["entrypoint"][1].split(":")
    assert module == Path(config["target"]).stem and factory == "create_app"
    assert "--no-proxy-headers" in backend["entrypoint"] and "--factory" in backend["entrypoint"]
    spec = importlib.util.spec_from_file_location(module, ROOT / overlay["configs"][config["source"]]["file"])
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


async def test_no_default_trust_for_direct_connections(launcher, monkeypatch):
    resolve = AsyncMock()
    monkeypatch.setattr(launcher, "_frontend_addresses", resolve)
    app = launcher.create_app()
    for peer in ("127.0.0.1", "::1", "172.19.0.4", "192.168.1.5", "10.1.2.3", "198.51.100.6"):
        assert await request(app, peer) == [peer, "http"]
    resolve.assert_not_awaited()


async def test_compose_frontend_appears_moves_and_disappears(launcher, monkeypatch):
    env = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["backend"]["environment"]
    monkeypatch.setenv("TRUST_COMPOSE_FRONTEND", env["TRUST_COMPOSE_FRONTEND"])
    assert env["TRUSTED_PROXY_NETWORKS"] == "${TRUSTED_PROXY_NETWORKS:-}"
    app = launcher.create_app()
    now = [100.0]
    monkeypatch.setattr(launcher, "monotonic", lambda: now[0])
    old, new = "172.19.0.3", "172.19.0.7"
    resolve = AsyncMock(side_effect=[OSError(), {old}, {new}, TimeoutError()])
    monkeypatch.setattr(launcher, "_frontend_addresses", resolve)
    assert await request(app, "127.0.0.1", None) == ["127.0.0.1", "http"]
    resolve.assert_not_awaited()
    assert await request(app, old) == [old, "http"]
    now[0] += launcher._RETRY_SECONDS
    simultaneous = await asyncio.gather(*(request(app, old) for _ in range(5)))
    assert simultaneous == [["203.0.113.42", "https"]] * 5 and resolve.await_count == 2
    assert await request(app, "172.19.0.4") == ["172.19.0.4", "http"]
    now[0] += launcher._CACHE_SECONDS
    assert await request(app, old) == [old, "http"]
    assert await request(app, new) == ["203.0.113.42", "https"]
    now[0] += launcher._CACHE_SECONDS
    assert await request(app, new) == [new, "http"]


async def test_explicit_trusted_proxy_chain_stops_at_first_unknown_peer(launcher, monkeypatch):
    monkeypatch.setenv("TRUST_COMPOSE_FRONTEND", "1")
    monkeypatch.setenv("TRUSTED_PROXY_NETWORKS", "127.0.0.1, 192.0.2.16/29")
    monkeypatch.setattr(launcher, "_frontend_addresses", AsyncMock(return_value={"172.19.0.3"}))
    app = launcher.create_app()
    # One configured host, one configured network, and the frontend address.
    chain = "203.0.113.42, 198.51.100.6, 192.0.2.17, 172.19.0.3"
    assert await request(app, "127.0.0.1", chain) == ["198.51.100.6", "https"]
    assert await request(app, "192.0.2.24", chain) == ["192.0.2.24", "http"]


@pytest.mark.parametrize("network", ["*", "frontend", "10.0.0.7/24"])
def test_malformed_explicit_network_fails_at_startup(network):
    with pytest.raises(ValueError):
        proxy_entrypoint.TrustedProxyHeaders(echo, networks=network, compose_frontend=False)
