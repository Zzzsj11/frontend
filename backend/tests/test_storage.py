import socket

import pytest

from app.storage import _validate_public_url, download_public_url, safe_key


@pytest.mark.parametrize(
    "path",
    [
        "/users/attacker/../victim/private.mp4",
        "/users/attacker/%2e%2e/victim/private.mp4",
        "/users/attacker/%252e%252e/victim/private.mp4",
        "/users/attacker%2f..%2fvictim/private.mp4",
        "/users/attacker/..\\victim/private.mp4",
        "/users/victim/nested/users/attacker/private.mp4",
        "/untrusted-prefix/users/attacker/private.mp4",
        "/users/attacker-2/private.mp4",
    ],
)
def test_owned_tos_rejects_path_ambiguity(monkeypatch, path):
    from dataclasses import replace

    from app import storage

    monkeypatch.setattr(storage, "settings", replace(storage.settings, tos_public_domain="owned.test"))
    assert not storage.is_user_owned_tos_url("https://owned.test" + path, "attacker")


def test_owned_tos_allows_only_exact_user_below_configured_prefix(monkeypatch):
    from dataclasses import replace

    from app import storage

    monkeypatch.setattr(storage, "settings", replace(storage.settings, tos_public_domain="owned.test", tos_reference_prefix="mv/ref", tos_video_prefix="mv/video"))
    for prefix in ("", "mv/ref/", "mv/video/"):
        assert storage.is_user_owned_tos_url(f"https://owned.test/{prefix}users/user-1/creative/file.mp4", "user-1")
    for base in ("http://owned.test", "https://other.test", "https://user@owned.test", "https://owned.test:8443", "https://owned.test:bad"):
        assert not storage.is_user_owned_tos_url(base + "/users/user-1/file.mp4", "user-1")


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


@pytest.mark.asyncio
async def test_toapis_file_host_accepts_proxy_dns_but_not_private_addresses(monkeypatch) -> None:
    def proxy_address(_host, port, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.57", port))]

    monkeypatch.setattr(socket, "getaddrinfo", proxy_address)
    await _validate_public_url("https://files.toapis.cn/generated/image.png")
    with pytest.raises(ValueError, match="禁止访问内网"):
        await _validate_public_url("https://files.toapis.cn:8443/generated/image.png")

    def private_address(_host, port, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", private_address)
    with pytest.raises(ValueError, match="禁止访问内网"):
        await _validate_public_url("https://files.toapis.cn/generated/image.png")
