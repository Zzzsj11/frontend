from test_multi_user import create_and_login_user

from app.generation_preferences import text_selection
from app.llm_policy import completion_options


def test_preferences_are_user_owned_and_modality_checked(client):
    _, first = create_and_login_user(client, "preference-first")
    _, second = create_and_login_user(client, "preference-second")
    path = "/api/generation-preferences"
    selection = {"model": "nano-banana-2.1-all-in-one", "channel": None}
    saved = client.put(path + "/image", headers=first, json=selection)
    assert saved.status_code == 200, saved.text
    assert client.get(path, headers=first).json() == {"image": selection}
    assert client.get(path, headers=second).json() == {}
    assert client.put(path + "/video", headers=first, json=selection).status_code == 422
    assert client.get(path, headers=first).json() == {"image": selection}


def test_text_channel_is_explicit_and_context_is_reset():
    token = text_selection.set({"model": "gemini-3.8-flash-all-in-one", "channel": "toapis"})
    try:
        assert completion_options("gemini-3.8-flash-all-in-one", 512)["extra_body"] == {"channel": "toapis"}
    finally:
        text_selection.reset(token)
    assert "extra_body" not in completion_options("gemini-3.8-flash-all-in-one", 512)


def test_unavailable_channel_does_not_overwrite_preference(client, monkeypatch):
    from app import generation_preferences

    async def catalog(*args):
        return {"selection_parameter": "channel", "channels": []}

    monkeypatch.setattr(generation_preferences, "fetch_channels", catalog)
    path = "/api/generation-preferences/image"
    result = client.put(path, json={"model": "nano-banana-2.1-all-in-one", "channel": "missing"})
    assert result.status_code == 422
    assert client.get("/api/generation-preferences").json() == {}


def test_image_job_keeps_selection_after_user_changes_preferences(client, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import generation_preferences
    from app.jobs import jobs

    async def catalog(*args):
        return {"selection_parameter": "channel", "channels": [{"channel": "toapis-official", "available": True}]}

    monkeypatch.setattr(generation_preferences, "fetch_channels", catalog)
    monkeypatch.setattr(jobs, "dispatch", AsyncMock())
    _, headers = create_and_login_user(client, "snapshot-preference")
    choice = {"model": "nano-banana-2.1-all-in-one", "channel": "toapis-official"}
    assert client.put("/api/generation-preferences/image", headers=headers, json=choice).status_code == 200
    response = client.post("/api/generations/images", headers=headers, json={"prompt": "synthetic", "resolution": "2K"})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert client.put("/api/generation-preferences/image", headers=headers, json={**choice, "channel": None}).status_code == 200
    saved = asyncio.run(jobs.get(job_id))
    assert saved.request["model"] == choice["model"]
    assert saved.request["channel"] == choice["channel"]
    assert saved.request["resolution"] == "2K"


def test_channel_discovery_uses_configured_environment_and_fails_closed(monkeypatch):
    import asyncio
    import dataclasses

    import httpx
    import pytest
    from fastapi import HTTPException

    from app import generation_preferences as preferences

    monkeypatch.setattr(preferences, "settings", dataclasses.replace(preferences.settings, all_in_one_base_url="https://mg-test.example"))
    monkeypatch.setattr(preferences.all_in_one, "headers", lambda **kwargs: {"Authorization": "Bearer synthetic"})
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "unauthorized"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(HTTPException) as error:
        asyncio.run(preferences.fetch_channels("seedance-2.0", "test-user"))
    assert error.value.status_code == 502
    assert len(requests) == 1
    assert str(requests[0].url) == "https://mg-test.example/v1/models/seedance-2.0/channels?available_only=true"


def test_channel_limits_reject_unsupported_media_without_switching_model():
    import pytest
    from fastapi import HTTPException

    from app.generation_preferences import validate_channel_parameters
    from app.schemas import ImageGenerationCreate, VideoGenerationCreate

    image = ImageGenerationCreate(model="nano-banana-2.1-all-in-one", prompt="test", resolution="4K")
    with pytest.raises(HTTPException, match="清晰度"):
        validate_channel_parameters("image", image, {"resolutions": ["1k", "2k"]})
    image.resolution = "1K"
    validate_channel_parameters("image", image, {"resolutions": ["1k", "2k"]})
    video = VideoGenerationCreate(model="doubao-seedance-2.0-all-in-one", prompt="test", image_urls=["https://example.test/reference.png"])
    with pytest.raises(HTTPException, match="参考素材"):
        validate_channel_parameters("video", video, {"max_images": 0})
    assert video.model == "doubao-seedance-2.0-all-in-one"


def test_admin_comparison_validates_channels_before_calling_models(client, monkeypatch):
    from unittest.mock import AsyncMock

    from app import admin, generation_preferences

    async def catalog(*args):
        return {"selection_parameter": "channel", "channels": [{"channel": "toapis", "available": True}]}

    monkeypatch.setattr(generation_preferences, "fetch_channels", catalog)
    compare = AsyncMock(return_value=[])
    monkeypatch.setattr(admin, "compare_chat_models", compare)
    model = "gemini-3.8-flash-all-in-one"
    payload = {"models": [model], "prompt": "synthetic", "channels": {model: "missing"}}
    assert client.post("/api/admin/chat-comparison/run", json=payload).status_code == 422
    compare.assert_not_called()
    payload["channels"][model] = "bad/channel"
    assert client.post("/api/admin/chat-comparison/run", json=payload).status_code == 422
    payload["channels"][model] = "toapis"
    assert client.post("/api/admin/chat-comparison/run", json=payload).status_code == 200
    assert compare.call_args.kwargs["channels"] == {model: "toapis"}
    _, user = create_and_login_user(client, "comparison-channel-user")
    assert client.get(f"/api/admin/chat-comparison/models/{model}/channels", headers=user).status_code == 403
