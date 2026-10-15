from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from app import admin, providers
from app.providers import ProviderError


def test_providers_list_video_models_uses_env_key_and_base_url(monkeypatch) -> None:
    captured: dict = {}

    async def fake_get(self, url, headers=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers or {}
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "seedance-2.0", "object": "model", "owned_by": "platform", "kind": "video"}]}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(providers, "settings", SimpleNamespace(all_in_one_base_url="https://all-in-one.example"))
    monkeypatch.setattr("app.all_in_one.headers", lambda **kwargs: {"Authorization": "Bearer synthetic-aio-key"})
    models = asyncio.run(providers.list_video_models())

    assert models == [{"id": "seedance-2.0", "object": "model", "owned_by": "platform", "kind": "video"}]
    assert captured["url"] == "https://all-in-one.example/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer synthetic-aio-key"


def test_aigc_models_endpoint_returns_provider_model_list(client, monkeypatch) -> None:
    fake_models = [
        {"id": "seedance-2.0", "object": "model", "created": 0, "owned_by": "platform", "kind": "video"},
        {"id": "gemini-omni-1.1-flash-preview", "object": "model", "created": 0, "owned_by": "platform", "kind": "video"},
    ]

    async def fake_list(**kwargs):
        return fake_models

    monkeypatch.setattr(admin, "list_video_models", fake_list)
    monkeypatch.setattr(admin, "settings", SimpleNamespace(all_in_one_api_key="yh-0123456789abcdef", all_in_one_base_url="https://all-in-one.example"))

    response = client.get("/api/aigc/models")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "all-in-one"
    assert body["baseUrl"] == "https://all-in-one.example"
    assert body["apiKeySuffix"] == "abcdef"
    assert body["count"] == 2
    assert [m["id"] for m in body["models"]] == ["seedance-2.0", "gemini-omni-1.1-flash-preview"]


def test_aigc_models_endpoint_surfaces_provider_failure(client, monkeypatch) -> None:
    def boom(**kwargs):
        raise ProviderError("API Key 无效，请检查后重试")

    monkeypatch.setattr(admin, "list_video_models", boom)
    monkeypatch.setattr(admin, "settings", SimpleNamespace(all_in_one_api_key="yh-0123456789abcdef", all_in_one_base_url="https://all-in-one.example"))

    response = client.get("/api/aigc/models")

    assert response.status_code == 502
    assert "API Key 无效，请检查后重试" in response.json()["detail"]
