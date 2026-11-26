from dataclasses import replace
from importlib import import_module
from io import BytesIO
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from app import image_download, oss_storage, storage, system_human_media


@pytest.fixture
def config(monkeypatch):
    value = replace(
        storage.settings,
        storage_backend="oss",
        oss_region="cn-shenzhen",
        oss_bucket="media-example",
        oss_access_key_id="sample",
        oss_access_key_secret="sample",
        oss_prefix="mv/test/media",
        tos_endpoint="tos-cn-beijing.volces.com",
        tos_reference_bucket="legacy",
    )
    for module in (storage, image_download, oss_storage):
        monkeypatch.setattr(module, "settings", value)
    return value


@pytest.mark.asyncio
async def test_new_objects_use_internal_oss_and_stable_public_urls(config, monkeypatch, tmp_path):
    clients = [Mock(), Mock()]
    constructor = Mock(side_effect=clients)
    monkeypatch.setattr(oss_storage.oss2, "Bucket", constructor)
    upload = Mock()
    monkeypatch.setattr(oss_storage.oss2, "resumable_upload", upload)
    writer = storage.get_storage()
    key = "users/alice/a b.jpg"
    public = await writer.put_bytes(key, b"image", "image/jpeg")
    assert public == "https://media-example.oss-cn-shenzhen.aliyuncs.com/mv/test/media/users/alice/a%20b.jpg"
    assert constructor.call_args_list[0].args[1] == "https://oss-cn-shenzhen-internal.aliyuncs.com"
    assert clients[0].put_object.call_args.args == ("mv/test/media/" + key, b"image")
    assert await writer.put_file(key, tmp_path / "file", content_disposition="attachment") == public
    assert upload.call_args.args[:2] == (clients[0], "mv/test/media/" + key)
    assert upload.call_args.kwargs["headers"]["Content-Disposition"] == "attachment"
    assert storage.is_user_owned_tos_url(public, "alice")
    assert not storage.is_user_owned_tos_url(public.replace("/test/", "/production/"), "alice")
    assert not storage.is_user_owned_tos_url(public, "bob")
    assert storage.is_user_owned_tos_url("https://legacy.tos-cn-beijing.volces.com/users/alice/old.jpg", "alice")


@pytest.mark.asyncio
async def test_export_reads_exact_oss_namespace_via_internal_endpoint(config, tmp_path):
    src = "https://media-example.oss-cn-shenzhen.aliyuncs.com/mv/test/media/users/alice/clip.mp4"

    def respond(request):
        assert request.url.host == "media-example.oss-cn-shenzhen-internal.aliyuncs.com"
        assert request.url.path.endswith("/users/alice/clip.mp4")
        return httpx.Response(200, content=b"test")

    target = tmp_path / "clip"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await storage.download_public_url_to_path(src, target, client=client)
    assert (result[0], result[2], target.read_bytes()) == (src, 4, b"test")
    for invalid in (src + "?token=x", src.replace("/test/", "/production/"), src.replace("/alice/", "/%2e%2e/"), src.replace(".aliyuncs.com", ".invalid")):
        assert oss_storage.internal_read_url(invalid) is None


def test_shared_bucket_keeps_platform_and_mv_account_scopes(config, monkeypatch):
    prefix = config.oss_prefix + "/users/u-" + "1" * 32
    cfg = replace(config, oss_prefix=prefix)
    monkeypatch.setattr(oss_storage, "settings", cfg)
    monkeypatch.setattr(storage, "settings", cfg)
    src = f"https://{oss_storage.public_host()}/{prefix}/users/alice/video.mp4"
    assert storage.is_user_owned_tos_url(src, "alice")
    assert not storage.is_user_owned_tos_url(src, "bob")
    assert not storage.is_user_owned_tos_url(src.replace("1" * 32, "2" * 32), "alice")


def test_system_portrait_copy_uses_verified_public_oss_url(config, monkeypatch):
    migration = import_module("migrations.versions.0dc71af19e32_system_portraits_to_oss")
    for module in (migration, system_human_media):
        monkeypatch.setattr(module, "settings", config)
    original = BytesIO()
    Image.new("RGB", (8, 12)).save(original, format="JPEG")
    source = "https://legacy.tos-cn-beijing.volces.com/references/neutral-version/001.jpg"
    writer = Mock()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=original.getvalue() if request.method == "GET" else b"")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        destination = migration._copy(client, writer, source, system_human_media.portrait_key("001"), versioned=True)
        with pytest.raises(RuntimeError, match="Unexpected source"):
            migration._copy(client, writer, "https://other.example/001.jpg", system_human_media.portrait_key("001"))

    assert str(requests[0].url) == source
    assert requests[1].method == "HEAD"
    assert str(requests[1].url) == destination
    assert destination.startswith("https://media-example.oss-cn-shenzhen.aliyuncs.com/mv/test/media/system/digital-humans/neutral-")
    key, uploaded = writer.bucket.put_object.call_args.args
    assert destination.endswith("/" + key)
    assert uploaded == original.getvalue()


def test_missing_stock_portrait_accepts_restored_oss_object(config, monkeypatch):
    migration = import_module("migrations.versions.0dc71af19e32_system_portraits_to_oss")
    monkeypatch.setattr(system_human_media, "settings", config)
    key = system_human_media.portrait_key("028")
    source = system_human_media.legacy_portrait_url(key)
    destination = system_human_media.portrait_url(key)
    writer = Mock()

    def respond(request):
        if request.method == "HEAD":
            assert str(request.url) == destination
            return httpx.Response(200, headers={"content-type": "image/jpeg"})
        assert str(request.url) == source
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert migration._copy(client, writer, source, key) == destination
        with pytest.raises(httpx.HTTPStatusError):
            migration._copy(client, writer, source, key, versioned=True)
    writer.bucket.put_object.assert_not_called()
