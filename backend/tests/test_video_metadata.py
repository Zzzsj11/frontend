from __future__ import annotations

import shutil
import subprocess

import pytest

from app import video_metadata


def test_provider_resolution_uses_model_capability_mapping_and_legacy_fallback():
    capabilities = {"providerResolutionMap": {"720p": "768P"}}
    assert video_metadata.provider_resolution("minimax-h3", "720p", capabilities) == "768P"
    assert video_metadata.provider_resolution("minimax-h3-runninghub", "720p") == "0.9MP"
    assert video_metadata.provider_resolution("doubao-seedance-2.0", "1080p") == "1080P"


def test_wan_resolution_mapping_keeps_ui_values_out_of_provider_payload():
    capabilities = {"providerResolutionMap": {"480p": "480P", "720p": "720P", "1080p": "1080P"}}
    assert video_metadata.provider_resolution("wan3.0-video", "480p", capabilities) == "480P"
    assert video_metadata.provider_resolution("wan3.0-video-prime", "1080p", capabilities) == "1080P"


@pytest.mark.asyncio
async def test_probe_video_url_reads_actual_encoded_dimensions(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1344x768:d=1:r=24",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    async def fake_download(_url, target):
        shutil.copyfile(source, target)

    monkeypatch.setattr(video_metadata, "download_public_url_to_path", fake_download)
    result = await video_metadata.probe_video_url("https://tos.test/video.mp4")
    assert result["actualWidth"] == 1344
    assert result["actualHeight"] == 768
    assert result["fps"] == 24
    assert result["codec"] == "h264"
    assert result["actualDuration"] == 1
    assert result["fileSize"] > 0
