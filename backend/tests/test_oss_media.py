from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest

from app import image_download, oss_storage, storage


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
