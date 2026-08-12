
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
        return httpx.Response(200, json={"object": "list", "data": [{"id": "doubao-seedance-2.0", "object": "model", "owned_by": "yinhe"}]}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # key/base 由 _video_config 统一从环境变量（VIDEO_API_KEY/AIGC_TOKEN）解析
    monkeypatch.setattr(
        providers,
        "_video_config",
        lambda: ("https://api-aigc.fzyinghe.com", {"Authorization": "Bearer yh-from-env-abcdef12", "Content-Type": "application/json"}),
    )

    models = asyncio.run(providers.list_video_models())

    assert models == [{"id": "doubao-seedance-2.0", "object": "model", "owned_by": "yinhe"}]
    assert captured["url"] == "https://api-aigc.fzyinghe.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer yh-from-env-abcdef12"


def test_aigc_models_endpoint_returns_provider_model_list(client, monkeypatch) -> None:
    fake_models = [
        {"id": "doubao-seedance-2.0", "object": "model", "created": 0, "owned_by": "yinhe"},
        {"id": "kling-v3", "object": "model", "created": 0, "owned_by": "yinhe"},
    ]
    async def fake_list():
        return fake_models

    monkeypatch.setattr(admin, "list_video_models", fake_list)
    monkeypatch.setattr(admin, "settings", SimpleNamespace(video_api_key="yh-0123456789abcdef", video_api_base_url="https://api-aigc.fzyinghe.com"))

    response = client.get("/api/aigc/models")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "yinghe"
    assert body["baseUrl"] == "https://api-aigc.fzyinghe.com"
    assert body["apiKeySuffix"] == "abcdef"
    assert body["count"] == 2
    assert [m["id"] for m in body["models"]] == ["doubao-seedance-2.0", "kling-v3"]


def test_aigc_models_endpoint_surfaces_provider_failure(client, monkeypatch) -> None:
    def boom():
        raise ProviderError("API Key 无效，请检查后重试")

    monkeypatch.setattr(admin, "list_video_models", boom)
    monkeypatch.setattr(admin, "settings", SimpleNamespace(video_api_key="yh-0123456789abcdef", video_api_base_url="https://api-aigc.fzyinghe.com"))

    response = client.get("/api/aigc/models")

    assert response.status_code == 502
    assert "API Key 无效，请检查后重试" in response.json()["detail"]
