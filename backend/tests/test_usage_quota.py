from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi import HTTPException


def test_daily_quota_is_per_user_and_category(client) -> None:
    from app.database import session_factory
    from app.usage_quota import consume_daily_quota

    first = client.post(
        "/api/admin/users",
        json={"username": "quota-user-one", "password": "secure-pass-123", "display_name": "Quota One"},
    ).json()
    second = client.post(
        "/api/admin/users",
        json={"username": "quota-user-two", "password": "secure-pass-123", "display_name": "Quota Two"},
    ).json()

    async def exercise() -> None:
        async with session_factory() as db:
            assert await consume_daily_quota(db, user_id=first["id"], category="image", limit=2) == 1
            assert await consume_daily_quota(db, user_id=first["id"], category="image", limit=2) == 2
            with pytest.raises(HTTPException) as error:
                await consume_daily_quota(db, user_id=first["id"], category="image", limit=2)
            assert error.value.status_code == 429
            assert "2次" in str(error.value.detail)

            assert await consume_daily_quota(db, user_id=first["id"], category="video", limit=2) == 1
            assert await consume_daily_quota(db, user_id=second["id"], category="image", limit=2) == 1

    asyncio.run(exercise())


def test_generation_endpoint_returns_readable_429_when_quota_is_exhausted(client) -> None:
    from app.database import session_factory
    from app.usage_quota import consume_daily_quota

    user = client.get("/api/auth/me").json()
    assert client.patch(f"/api/admin/users/{user['id']}", json={"daily_video_limit": 1}).status_code == 200

    async def exhaust() -> None:
        async with session_factory() as db:
            await consume_daily_quota(db, user_id=user["id"], category="video")

    asyncio.run(exhaust())
    response = client.post("/api/generations/videos", json={"prompt": "quota", "duration": 5})
    assert response.status_code == 429
    assert response.json()["detail"] == "今日视频生成调用量已达到上限（1次），请明日再试"
    assert client.patch(f"/api/admin/users/{user['id']}", json={"daily_video_limit": 100}).status_code == 200


def test_per_user_limit_resets_on_next_natural_day(client, monkeypatch) -> None:
    from app import usage_quota
    from app.database import session_factory

    created = client.post(
        "/api/admin/users",
        json={
            "username": "daily-reset-user",
            "password": "secure-pass-123",
            "daily_chat_limit": 1,
            "daily_image_limit": 2,
            "daily_video_limit": 3,
        },
    ).json()

    async def consume() -> None:
        async with session_factory() as db:
            assert await usage_quota.consume_daily_quota(db, user_id=created["id"], category="chat") == 1

    monkeypatch.setattr(usage_quota, "quota_date", lambda: date(2026, 8, 17))
    asyncio.run(consume())
    with pytest.raises(HTTPException):
        asyncio.run(consume())

    monkeypatch.setattr(usage_quota, "quota_date", lambda: date(2026, 8, 18))
    asyncio.run(consume())
