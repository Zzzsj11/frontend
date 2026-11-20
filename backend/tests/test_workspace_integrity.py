import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from test_image_download import configure

from app import creative, domain
from app.database import session_factory
from app.models import GenerationJobModel


def test_audio_edit_preserves_script_and_cast_change_updates_all_lines(client):
    config = {"storyBible": {"version": 2}, "songEmotion": "温暖", "videoModelDefaults": {"duration": 10}}
    project_id = client.post("/api/projects", json={"name": "音轨与阵容"}).json()["id"]
    task = client.post(f"/api/projects/{project_id}/tasks", json={"storyboard_config": config}).json()
    endpoint = f"/api/tasks/{task['id']}"
    track = {"audioTrackVisible": True, "audioOffsetSeconds": -2.5}
    assert client.patch(endpoint + "/audio-track", json=track).status_code == 200
    assert client.get(endpoint).json()["storyboardConfig"] == {**config, **track}
    assert client.patch(endpoint, json={"storyboard_config": {"audioOffsetSeconds": 3}}).status_code == 200
    assert client.get(endpoint).json()["storyboardConfig"] == {**config, **track, "audioOffsetSeconds": 3}
    humans = [human["id"] for human in client.get("/api/digital-humans").json() if human["readOnly"]][:2]
    assert len(humans) == 2
    assert client.put(endpoint + "/cast", json={"digital_human_ids": humans}).status_code == 200
    for cast in [humans, humans[:1], []]:
        response = client.post(endpoint + "/storyboard/lines", json={"digital_human_ids": cast})
        assert response.status_code == 201, response.text
    for _ in range(2):
        assert client.put(endpoint + "/cast", json={"digital_human_ids": humans[1:]}).status_code == 200
    saved = client.get(endpoint).json()
    assert saved["cast"] == humans[1:]
    assert [line["digitalHumanIds"] for line in saved["lines"]] == [humans[1:], [], []]


def test_recovered_portrait_has_one_record_and_style_merge_persists(client, monkeypatch):
    configure(monkeypatch)
    register = AsyncMock()
    monkeypatch.setattr(domain, "_sync_human_asset_avatar", register)
    user_id = client.get("/api/auth/me").json()["id"]
    url = f"https://preview-media.tos-cn-beijing.volces.com/users/{user_id}/portrait.jpg"
    job_id = f"image-{uuid4().hex}"

    async def seed_finished_job():
        async with session_factory() as db:
            db.add(GenerationJobModel(id=job_id, kind="image", user_id=user_id, status="succeeded", result={"urls": [url]}))
            await db.commit()

    asyncio.run(seed_finished_job())
    style = client.post("/api/digital-human-styles", json={"name": "原分类"}).json()
    assert client.post("/api/digital-human-styles", json={"name": "原分类"}).json()["id"] == style["id"]
    target = client.post("/api/digital-human-styles", json={"name": "目标分类"}).json()
    payload = {"name": "恢复的人物", "style_id": style["id"], "avatar_url": url, "source_job_id": job_id}
    first = client.post("/api/digital-humans", json=payload)
    assert first.status_code == 201, first.text
    replay = client.post("/api/digital-humans", json=payload)
    assert replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    register.assert_awaited_once()
    renamed = client.patch(f"/api/digital-human-styles/{style['id']}", json={"name": "中间名"})
    assert renamed.json() == {"id": style["id"], "name": "中间名"}
    merged = client.patch(f"/api/digital-human-styles/{style['id']}", json={"name": target["name"]})
    assert merged.json() == {"id": target["id"], "name": target["name"]}
    matching = [item for item in client.get("/api/digital-humans").json() if item["id"] == first.json()["id"]]
    assert len(matching) == 1
    assert matching[0]["styleId"] == target["id"]
    assert style["id"] not in {item["id"] for item in client.get("/api/digital-human-styles").json()}
    assert client.delete(f"/api/digital-humans/{first.json()['id']}").status_code == 200
    assert client.post("/api/digital-humans", json=payload).status_code == 410


def test_replayed_creative_request_enqueues_and_charges_once(client, monkeypatch):
    monkeypatch.setattr(creative, "provider_status", lambda: {"gemini": {"configured": True, "model": "fixture"}})
    dispatch = AsyncMock()
    monkeypatch.setattr(creative.jobs, "dispatch", dispatch)
    quota = AsyncMock(wraps=creative.consume_daily_quota)
    monkeypatch.setattr(creative, "consume_daily_quota", quota)
    endpoint = "/api/creative/optimizations"
    payload = {"request_id": str(uuid4()), "provider": "gemini", "prompt": "一场春雨"}
    first = client.post(endpoint, json=payload)
    assert first.status_code == 201, first.text
    replay = client.post(endpoint, json=payload)
    assert replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert client.post(endpoint, json={**payload, "prompt": "不同意图"}).status_code == 409
    dispatch.assert_awaited_once()
    quota.assert_awaited_once()


def test_omitted_headshot_resolution_keeps_model_specific_default(monkeypatch):
    from app import generation_preferences
    from app.schemas import ImageGenerationCreate

    monkeypatch.setattr(generation_preferences, "read_selection", AsyncMock(return_value={}))
    cases = [
        ("nano-banana-2.1-all-in-one", [], {}, "1K"),
        ("seedream-5.0-pro-all-in-one", ["reference.png"], {}, "2K"),
        ("seedream-5.0-pro-all-in-one", ["reference.png"], {"resolution": "4K"}, "4K"),
    ]
    for model, references, extra, expected in cases:
        payload = ImageGenerationCreate(prompt="portrait", model=model, images=references, **extra)
        asyncio.run(generation_preferences.apply_media_preference(None, "fixture", "image", payload))
        assert payload.resolution == expected
