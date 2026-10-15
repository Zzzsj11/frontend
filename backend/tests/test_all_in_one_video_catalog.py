"""The live platform contract is frozen locally; all suppliers here are synthetic."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app import all_in_one
from app.all_in_one_catalog import VIDEO_MODEL_CODES, video_rows
from app.jobs import Job, jobs
from app.main import validate_video_references
from app.media_constraints import normalize_video_duration
from app.schemas import VideoGenerationCreate
from app.story_bible import exact_durations


def test_catalog_is_complete_and_presentation_is_provider_free():
    rows = video_rows()
    assert len(rows) == len(VIDEO_MODEL_CODES) == 12
    assert len({row["capabilities"]["series"] for row in rows}) == 6
    assert all("all in one" not in row["name"] and "英和" not in row["name"] for row in rows)
    assert all(row["capabilities"]["billing"]["provider"] == "all-in-one" for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("row", video_rows(), ids=lambda row: row["code"])
async def test_every_video_model_maps_to_canonical_platform_request(monkeypatch, row):
    caps = row["capabilities"]
    duration = caps["durations"]["min"]
    resolution = "720p" if "720p" in caps["resolutions"] else caps["resolutions"][0]
    request = VideoGenerationCreate(model=row["code"], prompt="Synthetic contract test", duration=duration, resolution=resolution, h3_mode="text")
    validate_video_references(request, caps)
    captured = []

    def handler(request):
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"id": "synthetic-upstream"})

    factory = httpx.AsyncClient
    monkeypatch.setattr(all_in_one.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(all_in_one, "headers", lambda **kwargs: {"X-Agent-Name": "code-agent", "X-Agent-Run-Id": "synthetic-contract", "X-Test-Run-Id": "synthetic-contract"})
    for method in ["record_provider_request", "mark_provider_submitting", "record_provider_response", "set_provider_task"]:
        monkeypatch.setattr(jobs, method, AsyncMock())
    monkeypatch.setattr(all_in_one, "resume", AsyncMock(return_value={"synthetic": True}))
    job = Job(
        id="synthetic-" + row["code"],
        kind="video",
        user_id="owner",
        request={"model": row["code"], "_provider": "all-in-one", "_providerModelId": row["provider_model_id"], "_capabilities": caps},
    )
    assert await all_in_one.generate(request, job) == {"synthetic": True}
    assert len(captured) == 1
    assert captured[0]["model"] == row["provider_model_id"]
    assert captured[0]["duration"] == duration
    assert captured[0]["resolution"] == caps.get("providerResolutionMap", {}).get(resolution, resolution)


def test_fixed_and_discrete_durations_do_not_leak_legacy_fifteen_second_limit():
    by_code = {row["code"]: row["capabilities"] for row in video_rows()}
    omni = by_code["gemini-omni-1.1-flash-preview-all-in-one"]
    assert exact_durations(210, 17, omni) == [10] * 17
    assert normalize_video_duration(5, omni) == 10
    assert normalize_video_duration(30, by_code["doubao-seedance-2.5-all-in-one"]) == 30
    assert normalize_video_duration(1, by_code["grok-video-1.5-all-in-one"]) == 1
    assert set(exact_durations(31, 5, by_code["veo-3.1-all-in-one"])) <= {4, 6, 8}


def test_retired_video_codes_cannot_start_new_work(client):
    for code in ["doubao-seedance-2.0", "minimax-h3-runninghub", "veo-3.1-generate-preview", "kling-v3"]:
        response = client.post("/api/generations/videos", json={"model": code, "prompt": "must not run"})
        assert response.status_code == 422
        assert "退役" in response.json()["detail"]


def test_grok_reference_mode_rejects_unsupported_full_hd():
    caps = next(row["capabilities"] for row in video_rows() if row["provider_model_id"] == "grok-video-1.5")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        validate_video_references(VideoGenerationCreate(prompt="synthetic", resolution="1080p", image_urls=["https://tos.test/ref.png"]), caps)
    assert error.value.status_code == 422
    validate_video_references(VideoGenerationCreate(prompt="synthetic", resolution="1080p", h3_mode="first_frame", image_urls=["https://tos.test/ref.png"]), caps)
