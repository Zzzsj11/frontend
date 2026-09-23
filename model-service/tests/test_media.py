import base64
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public-api"))


@pytest.mark.asyncio
async def test_gemini_uses_actual_image_mime_and_original_bytes(monkeypatch):
    from gateway import media

    output = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format="PNG")
    raw = output.getvalue()

    async def download(url, max_bytes):
        assert url == "https://example.com/original.jpg" and max_bytes == 20 * 1024 * 1024
        return url, raw, "image/jpeg"

    monkeypatch.setattr(media, "download_public_url", download)
    result = await media.gemini_images({"images": ["https://example.com/original.jpg"], "prompt": "test"})
    assert result["images"] == ["data:image/png;base64," + base64.b64encode(raw).decode()]
    assert result["prompt"] == "test"


@pytest.mark.asyncio
async def test_gemini_rejects_non_image(monkeypatch):
    from gateway import media

    async def download(url, max_bytes):
        return url, b"not an image", "image/png"

    monkeypatch.setattr(media, "download_public_url", download)
    with pytest.raises(Exception):
        await media.gemini_images({"images": ["https://example.com/original"]})


@pytest.mark.parametrize(
    "body",
    [
        {"content": {"video_url": "https://example.com/result.mp4"}},
        {"code": 200, "data": {"task": {"content": {"url": "https://example.com/result.mp4"}}}},
        {"data": {"task_result": {"videos": [{"url": "https://example.com/result.mp4"}]}}},
        {"resultUrl": "https://example.com/result.mp4"},
        {"results": [{"url": "https://example.com/result.mp4", "outputType": "mp4"}]},
        {"result": {"data": [{"url": "https://example.com/result.mp4"}]}},
    ],
)
def test_output_shapes(body):
    from gateway.media import output_urls

    assert output_urls(body, "video") == ["https://example.com/result.mp4"]


@pytest.mark.asyncio
async def test_media_connections_reject_private_and_pin_ip(monkeypatch):
    from gateway import network

    network._cache.clear()
    for host in ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "198.18.0.1"]:
        with pytest.raises(ValueError):
            await network.public_addresses(host, 443)
    backend = network.PublicNetworkBackend()
    seen = []

    async def addresses(host, port):
        return ["8.8.8.8"]

    async def connect(host, port, *args):
        seen.append((host, port))
        return "stream"

    monkeypatch.setattr(network, "public_addresses", addresses)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    assert await backend.connect_tcp("example.com", 443) == "stream"
    assert seen == [("8.8.8.8", 443)]


@pytest.mark.asyncio
async def test_image_archive_records_actual_not_requested_size(monkeypatch):
    from types import SimpleNamespace

    from gateway import media

    output = io.BytesIO()
    Image.new("RGB", (3, 2), "white").save(output, format="PNG")

    async def download(url, max_bytes):
        return url, output.getvalue(), "image/png"

    async def store(key, content, mime):
        return "https://tos.example/original.png", "https://tos.example/thumbnail.jpg"

    monkeypatch.setattr(media, "download_public_url", download)
    monkeypatch.setattr(media, "put_image_with_thumbnail", store)
    job = SimpleNamespace(id="job", client_id="client", user_id="user", kind="image", payload={"size": "1024x1024"})
    result = await media.archive(job, {"resultUrl": "https://example.com/image.png"})
    assert result["media"][0]["width"] == 3
    assert result["media"][0]["height"] == 2
    assert result["media"][0]["requested_size"] == "1024x1024"
    assert result["native"]["resultUrl"] == "https://tos.example/original.png"


def test_process_secret_isolation():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "process_environment", Path(__file__).resolve().parents[1] / "scripts/process_environment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = {
        "PATH": "/bin",
        "DATABASE_URL": "database",
        "YINGHE_API_KEY": "supplier",
        "TOS_SECRET_KEY": "storage",
        "ADMIN_PASSWORD": "admin",
        "ADMIN_JWT_SECRET": "jwt",
    }
    assert module.for_service("web", source) == {"PATH": "/bin"}
    assert "YINGHE_API_KEY" not in module.for_service("admin", source)
    assert "TOS_SECRET_KEY" not in module.for_service("admin", source)
    assert "ADMIN_JWT_SECRET" not in module.for_service("public", source)
    assert module.for_service("worker", source)["YINGHE_API_KEY"] == "supplier"


@pytest.mark.parametrize(
    "protocol,name,resolution,expected_key",
    [
        ("seedance", "doubao-seedance-2.0", "720p", "content"),
        ("seedance", "doubao-seedance-2.0-mini", "720p", "content"),
        ("seedance", "doubao-seedance-2.0-fast", "720p", "content"),
        ("h3", "MiniMax-H3", "720p", "content"),
        ("wan", "wan3.0-video", "720p", "input"),
        ("wan", "wan3.0-video-prime", "720p", "input"),
        ("kling", "kling-v3", "720p", "model_name"),
        ("unified", "veo-3.1-generate-preview", "720p", "metadata"),
        ("unified", "veo-3.1-fast-generate-preview", "720p", "metadata"),
        ("unified", "gemini-omni-flash-preview", "720p", "metadata"),
    ],
)
def test_canonical_video_model_payloads(protocol, name, resolution, expected_key):
    from types import SimpleNamespace

    from gateway.adapters import video_payload
    from gateway.schemas import VideoCreate

    model = SimpleNamespace(protocol=protocol, provider_model=name)
    result = video_payload(model, VideoCreate(model=name, prompt="test", resolution=resolution))
    assert expected_key in result
    if protocol == "h3":
        assert result["resolution"] == "768P"
    if name.startswith("veo-"):
        assert result["duration"] == 8
    if name.startswith("gemini-"):
        assert result["duration"] == 10


def test_canonical_identity_reference_never_becomes_kling_first_frame():
    from types import SimpleNamespace

    from fastapi import HTTPException
    from gateway.adapters import video_payload
    from gateway.schemas import VideoCreate

    req = VideoCreate(model="kling-v3", prompt="test", images=["https://example.com/identity.jpg"])
    with pytest.raises(HTTPException):
        video_payload(SimpleNamespace(protocol="kling", provider_model="kling-v3"), req)
