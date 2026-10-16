from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_multi_user import create_and_login_user

from app import image_download, storage


def configure(monkeypatch):
    config = replace(storage.settings, tos_reference_bucket="preview-media", tos_video_bucket="preview-video", tos_endpoint="tos-cn-beijing.volces.com", tos_public_domain="")
    monkeypatch.setattr(storage, "settings", config)
    monkeypatch.setattr(image_download, "settings", config)


def test_download_signing_is_owned_and_only_accepts_platform_storage(client, monkeypatch):
    configure(monkeypatch)
    user_id, headers = create_and_login_user(client, "image-download-user")
    signer = AsyncMock(return_value="https://preview-media.tos-cn-beijing.volces.com/image.jpg?signed=test")
    monkeypatch.setattr(image_download, "sign_download_url", signer)
    base = "https://preview-media.tos-cn-beijing.volces.com"
    own = f"{base}/users/{user_id}/image.jpg"
    response = client.get("/api/media/image-download", params={"src": own, "name": "人物原图"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["expiresIn"] == 300
    signer.assert_awaited_once_with(own, "人物原图")
    for src, expected in [
        (f"{base}/users/another-user/image.jpg", 403),
        ("http://127.0.0.1/private.jpg", 422),
        (own + "?arbitrary=value", 422),
        (f"{base}/users/{user_id}/%2e%2e/another.jpg", 403),
    ]:
        assert client.get("/api/media/image-download", params={"src": src}, headers=headers).status_code == expected
    assert signer.await_count == 1
    system = next(item for item in client.get("/api/digital-humans", headers=headers).json() if item["scope"] == "system")
    allowed = image_download.is_tos_url
    monkeypatch.setattr(image_download, "is_tos_url", lambda src: src == system["originalAvatar"] or allowed(src))
    response = client.get("/api/media/image-download", params={"src": system["originalAvatar"]}, headers=headers)
    assert response.status_code == 200
    assert signer.await_count == 2


@pytest.mark.asyncio
async def test_tos_download_uses_short_lived_signed_response_override(monkeypatch):
    configure(monkeypatch)
    tos = object.__new__(storage.TosStorage)
    presign = Mock(return_value=SimpleNamespace(signed_url="https://signed.example/image"))
    tos.client = SimpleNamespace(pre_signed_url=presign)
    monkeypatch.setattr(image_download, "get_storage", lambda: tos)
    result = await image_download.sign_download_url("https://preview-media.tos-cn-beijing.volces.com/users/me/a.jpg", "人物/原图")
    assert result == "https://signed.example/image"
    assert presign.call_args.kwargs["expires"] == 300
    assert "attachment;" in presign.call_args.kwargs["query"]["response-content-disposition"]
