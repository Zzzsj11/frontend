import asyncio
import shutil
import subprocess
import uuid
from datetime import timedelta

import pytest
from test_multi_user import create_and_login_user

from app import mv_export
from app.database import session_factory
from app.jobs import jobs
from app.models import GenerationJobModel, MaterialExportModel, ProjectAudioAssetModel, ProjectModel, ProjectTaskModel, ShotAssetModel, StoryboardLineModel, utcnow
from app.mv_render import normalize_ass, probe, render, verify

ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 3,840
PlayResY: 2,160
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,,180,&H0000FFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,0,2,0,2,30,30,40,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:03.50,Default,,0,0,0,,{\\K100}欢喜{\\K200}就好
"""


@pytest.fixture
def export_case(client, monkeypatch):
    user_id, headers = create_and_login_user(client, "mv-" + uuid.uuid4().hex[:10])
    project_id, task_id = "p-" + uuid.uuid4().hex, "t-" + uuid.uuid4().hex

    async def seed():
        async with session_factory() as db:
            db.add(ProjectModel(id=project_id, user_id=user_id, name="MV"))
            await db.flush()
            db.add(ProjectTaskModel(id=task_id, project_id=project_id, title="ASS MV", storyboard_type="ass", source_ass_url="https://test.tos/source.ass"))
            db.add(
                ProjectAudioAssetModel(
                    id="a-" + task_id,
                    user_id=user_id,
                    project_id=project_id,
                    original_filename="song.mp3",
                    audio_url="https://test.tos/audio.mp3",
                    file_size=100,
                    duration_seconds=7,
                )
            )
            await db.flush()
            for i in range(2):
                line_id = f"{task_id}-l{i}"
                db.add(StoryboardLineModel(id=line_id, project_task_id=task_id, sort_order=i, start_time=i * 3.5, end_time=(i + 1) * 3.5))
                await db.flush()
                db.add(ShotAssetModel(id=f"{task_id}-s{i}", storyboard_line_id=line_id, cover_url="", video_url=f"https://test.tos/clip{i}.mp4", duration=4))
            await db.commit()

    asyncio.run(seed())

    async def dispatch(*args):
        pass

    monkeypatch.setattr(jobs, "dispatch", dispatch)
    return headers, task_id


def test_snapshot_duplicate_isolation_and_validation(client, export_case):
    headers, task_id = export_case
    response = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers)
    assert response.status_code == 202, response.text
    first = response.json()
    assert first["kind"] == "video" and first["progress"] == 0
    assert client.post(f"/api/tasks/{task_id}/video-exports", headers=headers).json()["id"] == first["id"]
    _, foreign = create_and_login_user(client, "foreign-" + uuid.uuid4().hex[:8])
    assert client.post(f"/api/tasks/{task_id}/video-exports", headers=foreign).status_code == 404
    assert client.get(f"/api/material-exports/{first['id']}", headers=foreign).status_code == 404
    assert client.get(f"/api/material-exports/{first['id']}/events", headers=foreign).status_code == 404

    async def change():
        async with session_factory() as db:
            export = await db.get(MaterialExportModel, first["id"])
            snapshot = export.input_snapshot
            assert snapshot["clips"][0]["url"] == "https://test.tos/clip0.mp4"
            assert snapshot["audioOffset"] == 0
            export.status = "failed"
            asset = await db.get(ShotAssetModel, task_id + "-s0")
            asset.deleted_at = utcnow()
            await db.commit()

    asyncio.run(change())
    invalid = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers)
    assert invalid.status_code == 422 and "1 段" in invalid.text
    assert client.get(f"/api/material-exports/{first['id']}", headers=headers).status_code == 200


def test_video_and_material_exports_coexist(client, export_case):
    headers, task_id = export_case
    video = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers).json()
    material = client.post(f"/api/tasks/{task_id}/material-exports", headers=headers).json()
    assert material["id"] != video["id"] and material["kind"] == "materials"
    listed = client.get(f"/api/tasks/{task_id}/material-exports", headers=headers).json()
    assert {v["kind"] for v in listed} == {"materials", "video"}


def test_ass_keeps_karaoke_and_shifts_with_audio():
    text = normalize_ass(ASS, 1.5)
    assert "PlayResX: 3840" in text and "Noto Sans CJK SC" in text
    assert r"{\K100}欢喜{\K200}就好" in text
    assert "0:00:02.00,0:00:05.00" in text
    assert "&H00FFFFFF" in text


@pytest.fixture
def media(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for rendering integration")
    for i, size in enumerate(["320x180", "256x144"]):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={'red' if i == 0 else 'blue'}:s={size}:r=24:d=4",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                str(tmp_path / f"clip{i}.mp4"),
            ],
            check=True,
        )
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=7", str(tmp_path / "audio.mp3")], check=True)
    (tmp_path / "source.ass").write_text(ASS)
    return tmp_path


@pytest.mark.parametrize("offset", [0, 0.5, -0.5])
def test_real_render_and_progress(media, offset):
    async def run():
        progress = []

        async def update(fraction, seconds):
            progress.append(fraction)

        metadata = await render(media, {"audioOffset": offset, "clips": [{"start": 0}, {"start": 3.5}]}, update)
        await verify(media, metadata, update)
        info = await probe(media / "final.mp4")
        assert metadata["width"] == 256 and metadata["height"] == 144
        assert abs(float(info["format"]["duration"]) - (7 + offset)) < 0.15
        assert progress and max(progress) > 0.95
        assert (media / "cover.jpg").stat().st_size > 0
        assert (media / "thumbnail.jpg").stat().st_size > 0

    asyncio.run(run())


def test_runner_persists_complete_upload_and_sse(client, export_case, media, monkeypatch):
    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers).json()

    async def download(url, destination, progress_callback=None, **kwargs):
        source = media / url.rsplit("/", 1)[1]
        shutil.copyfile(source, destination)
        size = source.stat().st_size
        await progress_callback(size, size)
        return "", "", size

    class Storage:
        async def put_file(self, key, path, mime, progress_callback=None, content_disposition=None):
            if mime == "video/mp4":
                assert content_disposition.startswith("attachment;")
            if progress_callback:
                progress_callback(path.stat().st_size, path.stat().st_size)
            return "https://test.tos/" + key

    monkeypatch.setattr(mv_export, "download_public_url_to_path", download)
    monkeypatch.setattr(mv_export, "get_storage", Storage)

    async def run():
        async with session_factory() as db:
            job = jobs._from_model(await db.get(GenerationJobModel, created["jobId"]))
        await mv_export.run_video_export(created["id"], job)

    asyncio.run(run())
    result = client.get(f"/api/material-exports/{created['id']}", headers=headers).json()
    assert result["status"] == "ready" and result["progress"] == 100
    assert result["archiveUrl"].endswith(".mp4")
    assert result["metadata"]["thumbnailUrl"].endswith(".jpg")
    events = client.get(f"/api/material-exports/{created['id']}/events", headers=headers)
    assert "合并导出完成" in events.text


def test_stale_export_recovers_then_fails_cleanly(client, export_case):
    from app.worker import _recover_stale

    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers).json()

    async def run():
        for attempt in [1, 3]:
            async with session_factory() as db:
                model = await db.get(GenerationJobModel, created["jobId"])
                model.status, model.attempt = "running", attempt
                model.lease_expires_at = utcnow() - timedelta(seconds=10)
                await db.commit()
            resumed, failed = await _recover_stale(("mv_export",), ())
            async with session_factory() as db:
                export = await db.get(MaterialExportModel, created["id"])
                assert export.status == ("queued" if attempt == 1 else "failed")
                assert (resumed, failed) == ((1, 0) if attempt == 1 else (0, 1))

    asyncio.run(run())


def test_runner_failure_is_visible_and_retryable(client, export_case, monkeypatch):
    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers).json()

    async def fail(*args, **kwargs):
        raise ValueError("素材不可读取，请重试")

    monkeypatch.setattr(mv_export, "download_public_url_to_path", fail)

    async def run():
        async with session_factory() as db:
            job = jobs._from_model(await db.get(GenerationJobModel, created["jobId"]))
        with pytest.raises(ExceptionGroup):
            await mv_export.run_video_export(created["id"], job)

    asyncio.run(run())
    result = client.get(f"/api/material-exports/{created['id']}", headers=headers).json()
    assert result["status"] == "failed" and result["progress"] < 100
    assert "素材不可读取" in result["error"]
    retry = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers)
    assert retry.status_code == 202 and retry.json()["id"] != created["id"]


def test_copied_ass_resolves_only_same_project_source(client, export_case):
    headers, task_id = export_case

    async def prepare():
        async with session_factory() as db:
            task = await db.get(ProjectTaskModel, task_id)
            source = ProjectTaskModel(id=task_id + "-source", project_id=task.project_id, title="source", storyboard_type="ass", source_ass_url=task.source_ass_url)
            db.add(source)
            task.source_ass_url = None
            task.storyboard_config = {"copySource": {"taskId": source.id, "sourceAssUrl": "https://untrusted.example/not-used.ass"}}
            await db.commit()

    asyncio.run(prepare())
    response = client.post(f"/api/tasks/{task_id}/video-exports", headers=headers)
    assert response.status_code == 202

    async def check():
        async with session_factory() as db:
            item = await db.get(MaterialExportModel, response.json()["id"])
            assert item.input_snapshot["assUrl"] == "https://test.tos/source.ass"

    asyncio.run(check())
