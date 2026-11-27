"""Build OSS material archives incrementally, without temporary media files."""

import asyncio
import json
import logging
import os
import zipfile
from collections.abc import Awaitable, Callable
from urllib.parse import quote

import httpx
from oss2.models import PartInfo

from .config import settings
from .oss_storage import OssStorage, internal_read_url, public_host
from .storage import stream_public_download

logger = logging.getLogger(__name__)
PART_BYTES = 16 * 1024**2
SOURCE_LIMIT = 500 * 1024**2
HELPER = "/usr/local/bin/mv-streamzip"
Progress = Callable[[int, int], Awaitable[None]]


class MultipartBuffer:
    """A non-seekable ZIP output drained by the asynchronous uploader."""

    def __init__(self, limit: int):
        self.buffer = bytearray()
        self.size = 0
        self.limit = limit

    def tell(self) -> int:
        return self.size

    def flush(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.size += len(data)
        if self.size > self.limit:
            raise ValueError("素材包超过导出大小限额")
        self.buffer.extend(data)
        return len(data)


async def _oss_operation(call, *args, **kwargs):
    operation = asyncio.create_task(asyncio.to_thread(call, *args, **kwargs))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        await operation
        raise


async def _run_helper(bucket, object_key: str, upload_id: str, sources: list[dict], markdown: str, limit: int, progress: Progress):
    maximum = min(limit, SOURCE_LIMIT * len(sources) + len(markdown.encode()) + 4096 * (len(sources) + 1))
    part_count = (maximum + PART_BYTES - 1) // PART_BYTES
    if part_count > 10000:
        raise ValueError("素材包超过 OSS 分片数量限额")

    def sign() -> list[str]:
        return [bucket.sign_url("PUT", object_key, 7200, params={"partNumber": str(i), "uploadId": upload_id}, slash_safe=True) for i in range(1, part_count + 1)]

    urls = await asyncio.to_thread(sign)
    process = await asyncio.create_subprocess_exec(
        HELPER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={"GOMAXPROCS": "1"},
        limit=2**20,
    )
    try:
        process.stdin.write(json.dumps({"PartSize": PART_BYTES, "InFlight": 2, "Limit": limit, "Jobs": [{"Sources": sources, "Parts": urls, "Markdown": markdown}]}).encode())
        await process.stdin.drain()
        process.stdin.close()
        result = None
        async for line in process.stdout:
            event = json.loads(line)
            if "processed" in event:
                await progress(event["processed"], event["bytes"])
            else:
                result = event
        if await process.wait() or not result or result["Failure"]:
            raise RuntimeError(f"流式打包失败（{result['Failure'] if result else '传输中断'}）")
        parts = result["Parts"]
        return [PartInfo(i, part["ETag"]) for i, part in enumerate(parts, 1)], sum(part["Size"] for part in parts), result["Download"]
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


async def _stream_legacy(bucket, object_key: str, upload_id: str, items: list[dict], markdown: str, limit: int, progress: Progress):
    sink = MultipartBuffer(limit)
    parts = []
    processed_bytes = 0

    async def drain(final: bool = False):
        while len(sink.buffer) >= PART_BYTES or (final and sink.buffer):
            data = bytes(memoryview(sink.buffer)[:PART_BYTES])
            del sink.buffer[: len(data)]
            number = len(parts) + 1
            part = await _oss_operation(bucket.upload_part, object_key, upload_id, number, data)
            parts.append(PartInfo(number, part.etag))

    async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for index, item in enumerate(items, 1):
                size = 0
                internal = internal_read_url(item["url"])
                source = client.stream("GET", internal) if internal else stream_public_download(item["url"], client)
                async with source as response:
                    if internal:
                        response.raise_for_status()
                    with archive.open(item["arcname"], "w", force_zip64=True) as member:
                        async for chunk in response.aiter_bytes(1024**2):
                            size += len(chunk)
                            if size > SOURCE_LIMIT:
                                raise ValueError("远程文件超过允许大小")
                            member.write(chunk)
                            await drain()
                processed_bytes += size
                await progress(index, processed_bytes)
            archive.writestr("prompts.md", markdown, compress_type=zipfile.ZIP_DEFLATED)
    await drain(final=True)
    return parts, sink.size, processed_bytes


async def stream_material_zip(key: str, items: list[dict], markdown: str, progress: Progress, finishing: Progress) -> tuple[str, int]:
    bucket = OssStorage().bucket
    object_key = f"{settings.oss_prefix}/{key}"
    limit = min(settings.export_temp_limit_mb * 1024**2, 10000 * PART_BYTES)
    initialization = asyncio.create_task(asyncio.to_thread(bucket.init_multipart_upload, object_key, headers={"Content-Type": "application/zip"}))
    upload_id = None
    completed = False
    try:
        upload_id = (await asyncio.shield(initialization)).upload_id
        sources = [{"URL": internal_read_url(item["url"]), "Name": item["arcname"]} for item in items]
        if all(source["URL"] for source in sources) and os.access(HELPER, os.X_OK):
            parts, size, processed_bytes = await _run_helper(bucket, object_key, upload_id, sources, markdown, limit, progress)
        else:
            parts, size, processed_bytes = await _stream_legacy(bucket, object_key, upload_id, items, markdown, limit, progress)
        await finishing(size, processed_bytes)
        await _oss_operation(bucket.complete_multipart_upload, object_key, upload_id, parts)
        completed = True
        return f"https://{public_host()}/{quote(object_key, safe='/')}", size
    finally:
        if not completed:
            try:
                if upload_id is None and not initialization.cancelled():
                    upload_id = (await asyncio.shield(initialization)).upload_id
                if upload_id:
                    await _oss_operation(bucket.abort_multipart_upload, object_key, upload_id)
            except Exception:
                logger.warning("素材导出分片清理失败", exc_info=True)
