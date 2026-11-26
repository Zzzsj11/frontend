import io
import zipfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import material_zip


class Bucket:
    def __init__(self):
        self.parts = []
        self.completed = False
        self.aborted = False

    def init_multipart_upload(self, key, headers):
        assert headers["Content-Type"] == "application/zip"
        return SimpleNamespace(upload_id="upload")

    def upload_part(self, key, upload_id, number, data):
        assert upload_id == "upload"
        assert number == len(self.parts) + 1
        self.parts.append(data)
        return SimpleNamespace(etag=str(number))

    def complete_multipart_upload(self, key, upload_id, parts):
        assert [part.part_number for part in parts] == list(range(1, len(self.parts) + 1))
        self.completed = True

    def abort_multipart_upload(self, key, upload_id):
        self.aborted = True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_oss_material_archive_streams_ordered_parts_or_aborts(monkeypatch, fail):
    bucket = Bucket()
    monkeypatch.setattr(material_zip, "OssStorage", lambda: SimpleNamespace(bucket=bucket))
    monkeypatch.setattr(material_zip, "PART_BYTES", 128)
    video = b"video" * 100

    @asynccontextmanager
    async def open_source(url, client):
        async def chunks(_chunk_size):
            yield video
            if fail:
                raise RuntimeError("source disconnected")

        yield SimpleNamespace(aiter_bytes=chunks)

    monkeypatch.setattr(material_zip, "stream_public_download", open_source)
    progress, finishing = AsyncMock(), AsyncMock()
    args = "users/test/exports/sample.zip", [{"url": "https://legacy.example/shot.mp4", "arcname": "videos/01.mp4"}], "# Prompt", progress, finishing
    if fail:
        with pytest.raises(RuntimeError, match="source disconnected"):
            await material_zip.stream_material_zip(*args)
        assert bucket.parts and bucket.aborted and not bucket.completed
        finishing.assert_not_awaited()
    else:
        _, size = await material_zip.stream_material_zip(*args)
        zipped = b"".join(bucket.parts)
        assert len(zipped) == size and bucket.completed and not bucket.aborted
        with zipfile.ZipFile(io.BytesIO(zipped)) as bundle:
            assert bundle.namelist() == ["videos/01.mp4", "prompts.md"]
            assert bundle.read("videos/01.mp4") == video
            assert bundle.read("prompts.md") == b"# Prompt"
            assert bundle.testzip() is None
        progress.assert_awaited_once_with(1, len(video))
        finishing.assert_awaited_once_with(size, len(video))
