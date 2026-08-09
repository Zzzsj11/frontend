from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import balance


def test_balance_signature_matches_business_protocol() -> None:
    assert balance.build_balance_sign("123", 1700000000, "secret") == "859668A4884CD3348D13D2B982ECB404"


@pytest.mark.asyncio
async def test_balance_query_formats_and_caches_response(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"code": 200, "data": {"userId": 123, "balance": "287.391936"}}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append((url, kwargs["json"]))
            return FakeResponse()

    monkeypatch.setattr(balance, "settings", SimpleNamespace(business_api_key="secret", business_user_id="123", business_balance_url="https://balance.test", business_balance_timeout=10, business_balance_cache_seconds=30))
    monkeypatch.setattr(balance.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(balance, "_cache", None)
    monkeypatch.setattr(balance, "_cache_expires_at", 0.0)

    first = await balance.query_business_balance()
    second = await balance.query_business_balance()
    assert first["available"] is True
    assert first["balanceDisplay"] == "287.39"
    assert second == first
    assert len(calls) == 1
    assert calls[0][1]["userId"] == 123


@pytest.mark.asyncio
async def test_balance_query_degrades_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(balance, "settings", SimpleNamespace(business_api_key="", business_user_id=""))
    result = await balance.query_business_balance()
    assert result["available"] is False
    assert result["balanceDisplay"] == "--"
