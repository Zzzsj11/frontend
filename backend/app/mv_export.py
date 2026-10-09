"""User-owned, restartable final-video exports, sharing existing export transport."""

from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from .auth import CurrentUser
from .database import session_factory
from .domain import Db, _set_export_progress, export_progress_locks, material_export_public, owned_task
from .error_logging import redact_error_text
from .jobs import Job, jobs
from .models import MaterialExportModel, ProjectAudioAssetModel, ProjectTaskModel, ShotAssetModel, StoryboardLineModel, UserModel, utcnow
from .mv_render import render, verify
from .storage import download_public_url_to_path, get_storage, safe_key

router = APIRouter(prefix="/api")


async def input_snapshot(db, task, user_id: str) -> dict:
    ass_url = task.source_ass_url
    if not ass_url:
        source_id = ((task.storyboard_config or {}).get("copySource") or {}).get("taskId")
        source = await db.get(ProjectTaskModel, source_id) if isinstance(source_id, str) else None
        if source and source.project_id == task.project_id and source.deleted_at is None:
            ass_url = source.source_ass_url
    if task.storyboard_type != "ass" or not ass_url:
        raise HTTPException(422, "仅支持保留原始 ASS 文件的字幕分镜子项目")
    audio = await db.scalar(
        select(ProjectAudioAssetModel).where(
            ProjectAudioAssetModel.project_id == task.project_id,
            ProjectAudioAssetModel.user_id == user_id,
            ProjectAudioAssetModel.is_current.is_(True),
            ProjectAudioAssetModel.deleted_at.is_(None),
        )
    )
    if not audio:
        raise HTTPException(422, "请先上传歌曲音频")
    lines = list(
        (
            await db.scalars(
                select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order)
            )
        ).all()
    )
    assets = list(
        (
            await db.scalars(
                select(ShotAssetModel).where(
                    ShotAssetModel.storyboard_line_id.in_([v.id for v in lines]),
                    ShotAssetModel.deleted_at.is_(None),
                    ShotAssetModel.is_current.is_(True),
                    ShotAssetModel.status == "ready",
                )
            )
        ).all()
    )
    current = {v.storyboard_line_id: v for v in assets}
    missing = [i + 1 for i, v in enumerate(lines) if v.id not in current or not current[v.id].video_url]
    if not lines or missing:
        raise HTTPException(422, f"还有 {len(missing)} 段视频未完成：" + "、".join(map(str, missing)) if lines else "没有可合成的分镜")
    starts = [v.start_time for v in lines]
    if any(v is None or not math.isfinite(v) or v < 0 for v in starts) or starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])):
        raise HTTPException(422, "分镜时间轴需从 0 开始且按时间递增，请先修正分镜")
    offset = float((task.storyboard_config or {}).get("audioOffsetSeconds") or 0)
    if not math.isfinite(offset) or not 0 < audio.duration_seconds + offset <= 3600:
        raise HTTPException(422, "音频偏移或歌曲时长不适合合成（最长 1 小时）")
    return {
        "title": task.title,
        "assUrl": ass_url,
        "audioUrl": audio.audio_url,
        "audioId": audio.id,
        "audioOffset": offset,
        "clips": [{"lineId": v.id, "assetId": current[v.id].id, "url": current[v.id].video_url, "start": v.start_time} for v in lines],
    }


@router.post("/tasks/{task_id}/video-exports", status_code=202)
async def create_video_export(task_id: str, user: CurrentUser, db=Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    # 同用户受理串行化：并发双击不会重复入队，也不会突破用户队列上限。
    await db.execute(select(UserModel.id).where(UserModel.id == user.id).with_for_update())
    active = await db.scalar(
        select(MaterialExportModel).where(
            MaterialExportModel.user_id == user.id,
            MaterialExportModel.project_task_id == task.id,
            MaterialExportModel.export_kind == "video",
            MaterialExportModel.deleted_at.is_(None),
            MaterialExportModel.status.in_(("queued", "running")),
        )
    )
    if active:
        return material_export_public(active)
    count = list(
        (
            await db.scalars(
                select(MaterialExportModel.id).where(
                    MaterialExportModel.user_id == user.id,
                    MaterialExportModel.export_kind == "video",
                    MaterialExportModel.deleted_at.is_(None),
                    MaterialExportModel.status.in_(("queued", "running")),
                )
            )
        ).all()
    )
    if len(count) >= 2:
        raise HTTPException(429, "最多同时排队 2 个成片任务，请等待已有任务完成")
    snapshot = await input_snapshot(db, task, user.id)
    export = MaterialExportModel(
        id=f"export-{uuid.uuid4().hex}",
        user_id=user.id,
        project_task_id=task.id,
        export_kind="video",
        input_snapshot=snapshot,
        stage="排队中，轮到后自动开始",
        total_assets=len(snapshot["clips"]) + 2,
    )
    db.add(export)
    job = await jobs.enqueue(
        db,
        "mv_export",
        {"export_id": export.id, "_executionPool": "mv-final-render", "_executionConcurrency": 1},
        user_id=user.id,
        project_id=task.project_id,
        project_task_id=task.id,
    )
    export.generation_job_id = job.id
    await db.execute(
        update(MaterialExportModel)
        .where(
            MaterialExportModel.project_task_id == task.id,
            MaterialExportModel.export_kind == "video",
            MaterialExportModel.deleted_at.is_(None),
            MaterialExportModel.status.in_(("ready", "failed")),
        )
        .values(deleted_at=utcnow())
    )
    await db.commit()
    await db.refresh(export)
    response = material_export_public(export)
    await jobs.dispatch(job, lambda item: run_video_export(export.id, item))
    return response


async def run_video_export(export_id: str, job: Job) -> dict:
    async def progress(value: int, stage: str, **values):
        await _set_export_progress(export_id, job, value, stage, **values)

    try:
        async with session_factory() as db:
            export = await db.get(MaterialExportModel, export_id)
            if not export or export.deleted_at is not None or export.user_id != job.user_id:
                raise ValueError("导出任务不存在")
            # 已完成但工单终态尚未落库时重放，直接复用结果。
            if export.status == "ready":
                return {"exportId": export_id, "archiveUrl": export.archive_url}
            snapshot = export.input_snapshot
        await progress(1, "准备合成素材")
        with tempfile.TemporaryDirectory(prefix="mv-final-") as temporary:
            folder = Path(temporary)
            if shutil.disk_usage(folder).free < 2 * 1024**3:
                raise ValueError("服务器临时空间不足，请稍后重试")
            sources = [("source.ass", snapshot["assUrl"]), ("audio.mp3", snapshot["audioUrl"])] + [(f"clip{i}.mp4", v["url"]) for i, v in enumerate(snapshot["clips"])]
            received, totals, complete = {}, {}, set()
            last_update = 0.0
            lock, slots = asyncio.Lock(), asyncio.Semaphore(4)

            async def download(i: int, filename: str, url: str):
                async def update_download(current, total):
                    nonlocal last_update
                    received[i], totals[i] = current, total or 0
                    async with lock:
                        now = time.monotonic()
                        if now - last_update < 1 and i not in complete:
                            return
                        last_update = now
                        fraction = sum(1 if n in complete else min(0.99, received.get(n, 0) / totals[n]) if totals.get(n) else 0 for n in range(len(sources))) / len(sources)
                        await progress(
                            2 + int(23 * fraction),
                            f"下载素材 {len(complete)}/{len(sources)}",
                            processed_assets=len(complete),
                            processed_bytes=sum(received.values()),
                            total_bytes=sum(totals.values()),
                        )

                async with slots:
                    for attempt in range(3):
                        try:
                            _, _, size = await download_public_url_to_path(url, folder / filename, progress_callback=update_download, client=client)
                            complete.add(i)
                            await update_download(size, size)
                            return
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt == 2:
                                raise ValueError(f"素材 {i + 1} 下载失败，请稍后重试") from None
                            await asyncio.sleep(2**attempt)

            async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
                async with asyncio.TaskGroup() as group:
                    for i, (filename, url) in enumerate(sources):
                        group.create_task(download(i, filename, url))
            last_percent = -1

            async def render_progress(fraction, seconds):
                nonlocal last_percent
                percent = 28 + int(57 * fraction)
                if percent > last_percent:
                    last_percent = percent
                    await progress(percent, f"合成画面与字幕 · 已处理 {int(seconds)} 秒")

            await progress(26, "读取媒体信息与字幕")
            metadata = await render(folder, snapshot, render_progress)
            await progress(85, "校验成片音视频")

            async def verify_progress(fraction, _seconds):
                nonlocal last_percent
                percent = 85 + int(5 * fraction)
                if percent > last_percent:
                    last_percent = percent
                    await progress(percent, "校验成片音视频")

            await verify(folder, metadata, verify_progress)
            size = (folder / "final.mp4").stat().st_size
            await progress(90, "上传成片", archive_size=size)
            state = {"bytes": 0}

            def upload_progress(current, _total):
                state["bytes"] = current

            storage = get_storage()
            task = asyncio.create_task(
                storage.put_file(
                    safe_key(f"users/{job.user_id}/videos/exports/{job.project_task_id}", f"{export_id}.mp4"),
                    folder / "final.mp4",
                    "video/mp4",
                    progress_callback=upload_progress,
                    content_disposition="attachment; filename=mv.mp4; filename*=UTF-8''" + quote(snapshot["title"][:120] + ".mp4", safe=""),
                )
            )
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=1)
                    await progress(90 + int(8 * min(1, state["bytes"] / max(1, size))), f"上传成片 {state['bytes'] / 1024**2:.1f}/{size / 1024**2:.1f} MB")
                url = await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            await progress(99, "保存成片与封面")
            for name, filename in [("coverUrl", "cover.jpg"), ("thumbnailUrl", "thumbnail.jpg")]:
                metadata[name] = await storage.put_file(safe_key(f"users/{job.user_id}/images/export-covers", filename), folder / filename, "image/jpeg")
        async with session_factory() as db:
            export = await db.get(MaterialExportModel, export_id)
            export.status, export.progress, export.stage = "ready", 100, "合并导出完成"
            export.archive_url, export.archive_size, export.result_metadata = url, size, metadata
            export.error, export.finished_at = None, utcnow()
            await db.commit()
        return {"exportId": export_id, "archiveUrl": url, "archiveSize": size}
    except Exception as exc:
        if isinstance(exc, ExceptionGroup):
            exc = exc.exceptions[0]
        message = redact_error_text(str(exc)) if isinstance(exc, ValueError) else "合成服务暂时不可用，请重试；重复失败请联系管理员"
        async with session_factory() as db:
            export = await db.get(MaterialExportModel, export_id)
            if export:
                export.status, export.stage, export.error, export.finished_at = "failed", "合并导出失败", message, utcnow()
                await db.commit()
        raise
    finally:
        export_progress_locks.pop(export_id, None)
