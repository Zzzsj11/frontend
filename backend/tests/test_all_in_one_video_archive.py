"""Exercise the platform OSS archive through video completion and recovery."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import TEST_DB
from test_video_submission_recovery import video_submission  # noqa: F401

from app import all_in_one, platform_archive, providers, storage, video_metadata, video_reconciliation
from app.jobs import Job, jobs

HOST = "platform.oss-cn-shenzhen.aliyuncs.com"


def response_for(platform_id):
    base = f"https://{HOST}/model-service/clients/client/users/u-{'a' * 32}/{platform_id}/"
    item = {
        "url": base + "videos/0.mp4",
        "cover_url": base + "covers/0.jpg",
        "thumbnail_url": base + "covers/0-thumbnail.jpg",
        "metadata": {
            "width": 960,
            "height": 540,
            "file_size": 2400,
            "fps": 12,
            "duration": 1,
            "stream": {"codec_name": "h264"},
        },
    }
    return {
        "id": platform_id,
        "status": "SUCCEEDED",
        "result": {"archive": {"version": 1, "job_id": platform_id, "storage": "oss"}, "media": [item]},
        "billing": {"status": "settled", "points": "2.50"},
    }


@pytest.fixture
def archive_storage(monkeypatch):
    writer = SimpleNamespace(copy_object=AsyncMock(side_effect=lambda _, key: "https://mv.example/" + key))
    monkeypatch.setattr(platform_archive, "settings", SimpleNamespace(storage_backend="oss"))
    monkeypatch.setattr(platform_archive, "public_host", lambda: HOST)
    monkeypatch.setattr(platform_archive, "OssStorage", lambda: writer)
    for module, name in (
        (storage, "download_public_url_to_path"),
        (providers, "extract_video_cover"),
        (video_metadata, "probe_video_url"),
        (video_metadata, "probe_video_file"),
    ):
        monkeypatch.setattr(module, name, AsyncMock(side_effect=AssertionError(f"Unexpected local media processing: {name}")))
    return writer


@pytest.mark.parametrize("recovery", [False, True], ids=["worker", "recovery"])
def test_platform_copy_is_used_through_asset_commit(client, video_submission, archive_storage, monkeypatch, recovery):  # noqa: F811
    payload, _, _, _ = video_submission
    job_id = client.post("/api/generations/videos", json=payload).json()["id"]
    platform_id = "platform-" + job_id
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET provider='all-in-one',provider_task_id=? WHERE id=?", (platform_id, job_id))
        if recovery:
            db.execute("UPDATE generation_jobs SET status='failed',phase='manual_review' WHERE id=?", (job_id,))

    response = response_for(platform_id)
    query = AsyncMock(return_value=response)
    monkeypatch.setattr(all_in_one, "query_task", query)
    if recovery:
        assert asyncio.run(video_reconciliation.reconcile_one(job_id))["action"] == "recovered"
    else:

        async def run_worker():
            job = await jobs.get(job_id)
            await jobs.run_claimed(job, all_in_one.resume)

        asyncio.run(run_worker())

    query.assert_awaited_once()
    assert archive_storage.copy_object.await_count == 3
    with sqlite3.connect(TEST_DB) as db:
        user_id, status, result = db.execute("SELECT user_id,status,result FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        asset = db.execute("SELECT video_url,cover_url,cover_thumbnail_url,file_size,actual_width,actual_height FROM shot_assets WHERE generation_job_id=?", (job_id,)).fetchone()
        assert db.execute("SELECT request_id,generation_origin FROM token_usage_records WHERE generation_job_id=?", (job_id,)).fetchall() == [(platform_id, "agent_test")]
    assert status == "succeeded"
    result = json.loads(result)
    assert result["archiveMethod"] == "oss_copy"
    assert result["sourceUrl"] == response["result"]["media"][0]["url"]
    assert result["usage"]["platformBilling"] == response["billing"]
    urls = tuple(result[key] for key in ("videoUrl", "coverUrl", "coverThumbnailUrl"))
    assert all(url.startswith(f"https://mv.example/users/{user_id}/generated/") for url in urls)
    assert asset == (*urls, 2400, 960, 540)
    assert (result["codec"], result["fps"], result["actualDuration"]) == ("h264", 12, 1)


@pytest.mark.asyncio
async def test_partial_copy_retries_the_same_job_destinations(archive_storage):
    job_fields = dict(kind="video", id="retry-archive", user_id="test-user", provider_task_id="original-platform-order")
    response = response_for(job_fields["provider_task_id"])
    copy = archive_storage.copy_object
    successful_copy = copy.side_effect

    def fail_thumbnail(source, key):
        if key.endswith("-thumbnail.jpg"):
            raise OSError("OSS copy unavailable")
        return successful_copy(source, key)

    copy.side_effect = fail_thumbnail
    with pytest.raises(providers.ProviderError, match="OSS 复制失败"):
        await all_in_one.store_result(Job(**job_fields), response)
    first_calls = copy.await_args_list.copy()
    assert len(first_calls) == 3
    copy.reset_mock(side_effect=True)
    copy.side_effect = successful_copy
    result = await all_in_one.store_result(Job(**job_fields), response)
    assert result["archiveMethod"] == "oss_copy"
    assert copy.await_args_list == first_calls
