"""Exercise the actual video, cover, metadata and DB paths using a local MP4."""

import asyncio
import io
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import TEST_DB
from PIL import Image
from test_video_submission_recovery import video_submission  # noqa: F401

from app import all_in_one, providers, storage, video_metadata, video_reconciliation
from app.jobs import Job, jobs

SOURCE_URL = "https://platform.example/video.mp4"


@pytest.fixture
def original_video(tmp_path):
    source = tmp_path / "original.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=960x540:d=1:r=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True,
    )
    return source


@pytest.fixture
def archive_storage(original_video, monkeypatch):
    async def download(url, path):
        assert url == SOURCE_URL
        shutil.copyfile(original_video, path)
        return url, "video/mp4", original_video.stat().st_size

    class Storage:
        def __init__(self):
            self.objects = {}

        async def put_file(self, key, path, content_type):
            return await self.put_bytes(key, Path(path).read_bytes(), content_type)

        async def put_bytes(self, key, data, content_type):
            url = "https://mv.example/" + key
            self.objects[url] = (data, content_type)
            return url

    download_spy = AsyncMock(side_effect=download)
    monkeypatch.setattr(storage, "download_public_url_to_path", download_spy)
    writer = Storage()
    monkeypatch.setattr(storage, "get_storage", lambda: writer)
    return writer, download_spy


@pytest.mark.parametrize("probe_error", [False, True], ids=["worker", "recovery-without-ffprobe"])
def test_single_download_from_platform_until_asset_commit(client, video_submission, original_video, archive_storage, monkeypatch, probe_error):  # noqa: F811
    writer, download_spy = archive_storage
    payload, _, _, _ = video_submission
    job_id = client.post("/api/generations/videos", json=payload).json()["id"]
    platform_id = "platform-" + job_id
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET provider='all-in-one',provider_task_id=? WHERE id=?", (platform_id, job_id))
        if probe_error:
            db.execute("UPDATE generation_jobs SET status='failed',phase='manual_review' WHERE id=?", (job_id,))

    remote_probe = AsyncMock(side_effect=AssertionError("already processed in the local archive directory"))
    monkeypatch.setattr(video_metadata, "probe_video_url", remote_probe)
    if probe_error:
        monkeypatch.setattr(video_metadata, "probe_video_file", AsyncMock(side_effect=OSError("ffprobe unavailable")))

    response = {"status": "SUCCEEDED", "result": {"media": [{"url": SOURCE_URL}]}, "billing": {"status": "settled", "points": "2.50"}}
    query = AsyncMock(return_value=response)
    monkeypatch.setattr(all_in_one, "query_task", query)
    if probe_error:
        assert asyncio.run(video_reconciliation.reconcile_one(job_id))["action"] == "recovered"
    else:

        async def run_worker():
            job = await jobs.get(job_id)
            await jobs.run_claimed(job, all_in_one.resume)

        asyncio.run(run_worker())

    download_spy.assert_awaited_once()
    assert not download_spy.await_args.args[1].exists()
    remote_probe.assert_not_awaited()
    query.assert_awaited_once()
    with sqlite3.connect(TEST_DB) as db:
        user_id, status, result = db.execute("SELECT user_id,status,result FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        asset = db.execute("SELECT video_url,cover_url,cover_thumbnail_url,file_size,actual_width,actual_height FROM shot_assets WHERE generation_job_id=?", (job_id,)).fetchone()
        assert db.execute("SELECT request_id,generation_origin FROM token_usage_records WHERE generation_job_id=?", (job_id,)).fetchall() == [(platform_id, "agent_test")]
    assert status == "succeeded"
    result = json.loads(result)
    assert result["sourceUrl"] == SOURCE_URL and result["usage"]["platformBilling"] == response["billing"]
    video, cover, thumbnail = (result[key] for key in ("videoUrl", "coverUrl", "coverThumbnailUrl"))
    objects = writer.objects
    assert len(objects) == 3 and all(url.startswith(f"https://mv.example/users/{user_id}/generated/") for url in objects)
    assert objects[video] == (original_video.read_bytes(), "video/mp4")
    for url, size in ((cover, (960, 540)), (thumbnail, (640, 360))):
        content, content_type = objects[url]
        assert content_type == "image/jpeg"
        with Image.open(io.BytesIO(content)) as image:
            assert image.format == "JPEG" and image.size == size
    assert asset[:4] == (video, cover, thumbnail, original_video.stat().st_size)
    if probe_error:
        assert asset[4:] == (None, None)
    else:
        assert asset[4:] == (960, 540)
        assert (result["codec"], result["fps"], result["actualDuration"]) == ("h264", 12, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_stage", ["cover-extraction", "thumbnail-upload"])
async def test_failed_archive_cleans_temp_and_retries_same_job_objects(archive_storage, monkeypatch, fail_stage):
    writer, download = archive_storage
    job_fields = dict(kind="video", id="retry-archive", user_id="test-user", provider_task_id="original-platform-order")
    response = {"status": "SUCCEEDED", "result": {"media": [{"url": SOURCE_URL}]}}
    with monkeypatch.context() as fault:
        if fail_stage == "cover-extraction":
            fault.setattr(providers, "extract_video_cover", AsyncMock(side_effect=OSError("test failure")))
        else:
            put_bytes = writer.put_bytes

            async def fail_thumbnail(key, data, content_type):
                if key.endswith("-thumbnail.jpg"):
                    raise OSError("test failure")
                return await put_bytes(key, data, content_type)

            fault.setattr(writer, "put_bytes", fail_thumbnail)

        with pytest.raises(OSError, match="test failure"):
            await all_in_one.store_result(Job(**job_fields), response)
    first_attempt_keys = set(writer.objects)
    assert len(first_attempt_keys) == (0 if fail_stage == "cover-extraction" else 2)
    assert not download.await_args.args[1].parent.exists()

    result = await all_in_one.store_result(Job(**job_fields), response)
    assert download.await_count == 2
    assert not download.await_args.args[1].parent.exists()
    assert first_attempt_keys.issubset(writer.objects)
    assert set(writer.objects) == {result["videoUrl"], result["coverUrl"], result["coverThumbnailUrl"]}
