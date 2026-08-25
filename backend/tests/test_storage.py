import socket

import pytest

from app.storage import _validate_public_url, download_public_url, safe_key


def test_safe_key_removes_path_traversal() -> None:
    key = safe_key("../../images", "../../avatar 中文.png")
    assert ".." not in key
    assert key.startswith("images/")
    assert key.endswith(".png")


def test_safe_key_supports_user_scoped_tos_paths() -> None:
    key = safe_key("users/user-1/projects/project-1", "scene.png")
    assert key.startswith("users/user-1/projects/project-1/")


@pytest.mark.asyncio
async def test_remote_import_rejects_local_and_plain_http_urls() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        await download_public_url("http://127.0.0.1/private.png")


@pytest.mark.asyncio
async def test_remote_import_allows_plain_http_for_exact_vod_provider_host(monkeypatch) -> None:
    resolved_ports: list[int] = []

    def fake_getaddrinfo(_host, port, *_args, **_kwargs):
        resolved_ports.append(port)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("43.132.80.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    await _validate_public_url("http://store.vod-qcloud.com/generated/video.mp4")

    assert resolved_ports == [80]


@pytest.mark.asyncio
async def test_remote_import_rejects_http_host_that_only_looks_like_allowlisted_provider() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        await _validate_public_url("http://store.vod-qcloud.com.example.com/generated/video.mp4")

    with pytest.raises(ValueError, match="HTTPS"):
        await _validate_public_url("http://store.vod-qcloud.com@evil.example/generated/video.mp4")
