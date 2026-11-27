from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import platform_archive


@pytest.mark.asyncio
async def test_platform_copy_is_bound_to_one_job_owner_and_keeps_user_destinations(monkeypatch):
    job = SimpleNamespace(id="mv-1", provider_task_id="job-1", kind="video")
    hostname = "example.oss-cn-shenzhen.aliyuncs.com"
    directory = "model-service/clients/client/users/u-" + "a" * 32 + "/job-1/"
    base = "https://" + hostname + "/" + directory
    item = dict(
        url=base + "videos/0.mp4",
        cover_url=base + "covers/0.jpg",
        thumbnail_url=base + "covers/0-thumbnail.jpg",
        metadata=dict(width=64, height=32, duration=5.2, fps=24, stream=dict(codec_name="h264"), file_size=2400),
    )
    body = {"id": "job-1", "result": {"archive": {"version": 1, "job_id": "job-1", "storage": "oss"}, "media": [item]}}
    writer = AsyncMock()
    writer.copy_object.side_effect = lambda source, key: "https://cdn/" + key
    monkeypatch.setattr(platform_archive, "settings", SimpleNamespace(storage_backend="oss"))
    monkeypatch.setattr(platform_archive, "public_host", lambda: hostname)
    monkeypatch.setattr(platform_archive, "OssStorage", lambda: writer)
    data = await platform_archive.copy_platform_archive(job, body, "users/user1/generated")
    assert data["fileSize"] == 2400 and job.video_metadata_probed
    assert data["videoUrl"] == "https://cdn/users/user1/generated/videos/mv-1.mp4"
    assert writer.copy_object.await_count == 3
    for bad in (base.replace("job-1", "job-2"), base.replace("a" * 32, "b" * 32), base.replace(hostname, "other.example"), base + "../"):
        item["cover_url"] = bad + "covers/0.jpg"
        assert await platform_archive.copy_platform_archive(job, body, "users/user1/generated") is None
    assert writer.copy_object.await_count == 3


@pytest.mark.asyncio
async def test_video_without_verified_platform_archive_requires_reconciliation():
    from app.all_in_one import store_result
    from app.providers import ProviderError

    job = SimpleNamespace(id="mv-1", provider_task_id="job-1", kind="video", user_id="user1", request={})
    body = {"id": "job-1", "result": {"media": [{"url": "https://example.com/video.mp4"}]}}
    with pytest.raises(ProviderError, match="视频归档未通过校验"):
        await store_result(job, body)
