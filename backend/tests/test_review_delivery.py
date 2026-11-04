import asyncio
from unittest.mock import AsyncMock

from test_multi_user import create_and_login_user


def test_batch_status_preserves_manual_review_phase(client, monkeypatch):
    from app.database import session_factory
    from app.models import GenerationJobModel

    uid = client.get("/api/auth/me").json()["id"]

    async def seed():
        async with session_factory() as db:
            db.add(GenerationJobModel(id="review-phase", user_id=uid, kind="video", request={}, status="failed", phase="manual_review", error="Needs reconciliation"))
            await db.commit()

    asyncio.run(seed())
    response = client.post("/api/generations/status", json={"ids": ["review-phase"]})
    assert response.status_code == 200
    assert response.json()[0].get("phase") == "manual_review", response.json()


def test_preferences_lock_merges_latest_values(client):
    from app.database import session_factory
    from app.generation_preferences import GenerationPreference, save_preference
    from app.models import UserModel

    uid, _ = create_and_login_user(client, "review-stale-preferences")

    async def reproduce():
        async with session_factory() as first, session_factory() as second:
            # Both requests have already run require_user before acquiring the save lock.
            a = await first.get(UserModel, uid)
            b = await second.get(UserModel, uid)
            await save_preference("image", GenerationPreference(model="nano-banana-2.1-all-in-one"), a, first)
            await save_preference("video", GenerationPreference(model="doubao-seedance-2.0-all-in-one"), b, second)
        async with session_factory() as check:
            prefs = (await check.get(UserModel, uid)).generation_preferences
            assert set(prefs) == {"image", "video"}, prefs

    asyncio.run(reproduce())


def test_video_retry_keeps_original_selection(client, monkeypatch):
    from app.jobs import jobs

    monkeypatch.setattr(jobs, "dispatch", AsyncMock())
    _, headers = create_and_login_user(client, "review-replay-preferences")
    p = client.post("/api/projects", headers=headers, json={"name": "review"}).json()
    t = client.post(f"/api/projects/{p['id']}/tasks", headers=headers, json={"title": "review"}).json()
    line = client.post(f"/api/tasks/{t['id']}/storyboard/lines", headers=headers, json={"shot_type": "empty", "shot_prompt": "test"}).json()
    payload = {
        "request_id": "review-original-intent",
        "prompt": "test",
        "model": "doubao-seedance-2.0-all-in-one",
        "duration": 5,
        "resolution": "720p",
        "storyboard_line_id": line["id"],
        "project_task_id": t["id"],
    }
    first = client.post("/api/generations/videos", headers=headers, json=payload)
    assert first.status_code == 202, first.text
    saved = client.put("/api/generation-preferences/video", headers=headers, json={"model": "minimax-h3-all-in-one", "channel": None})
    assert saved.status_code == 200, saved.text
    replay = client.post("/api/generations/videos", headers=headers, json=payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"]

    changed = client.post("/api/generations/videos", headers=headers, json={**payload, "prompt": "changed"})
    assert changed.status_code == 409
    assert jobs.dispatch.await_count == 1

    # Once accepted, even a disabled original model must not break reconciliation.
    from sqlalchemy import select

    from app.database import session_factory
    from app.models import AiModelModel

    async def disable_original_model():
        async with session_factory() as db:
            model = await db.scalar(select(AiModelModel).where(AiModelModel.code == payload["model"]))
            old_status = model.status
            model.status = "disabled"
            await db.commit()
            return old_status

    async def restore_original_model(status):
        async with session_factory() as db:
            model = await db.scalar(select(AiModelModel).where(AiModelModel.code == payload["model"]))
            model.status = status
            await db.commit()

    status = asyncio.run(disable_original_model())
    try:
        replay = client.post("/api/generations/videos", headers=headers, json=payload)
        assert replay.status_code == 202, replay.text
        assert replay.json()["id"] == first.json()["id"]
        assert jobs.dispatch.await_count == 1
    finally:
        asyncio.run(restore_original_model(status))
