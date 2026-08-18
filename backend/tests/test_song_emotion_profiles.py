"""ASS 歌曲情感库管理接口与种子保护。"""

import asyncio

from sqlalchemy import select


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sample(code: str = "98765432") -> dict:
    return {
        "song_code": code,
        "song_name": "测试歌曲",
        "artists": "测试歌手",
        "primary_category": "流行歌曲",
        "secondary_category": "通用积极",
        "tertiary_category": "生活",
        "material_category": "流行歌曲-通用积极-生活",
        "seasons": "春",
        "atmosphere": "明亮 | 温暖",
    }


def test_song_emotion_profile_admin_crud(client):
    created = client.post("/api/admin/song-emotion-profiles", json=sample())
    assert created.status_code == 201, created.text
    assert created.json()["songCode"] == "98765432"
    assert client.post("/api/admin/song-emotion-profiles", json=sample()).status_code == 409

    listing = client.get("/api/admin/song-emotion-profiles", params={"q": "测试歌手", "limit": 10})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    descending = client.get("/api/admin/song-emotion-profiles", params={"limit": 2}).json()["items"]
    assert descending[0]["songCode"] > descending[1]["songCode"]

    detail = client.get("/api/admin/song-emotion-profiles/98765432")
    assert detail.json()["songName"] == "测试歌曲"
    updated = client.patch(
        "/api/admin/song-emotion-profiles/98765432",
        json={"song_name": "后台修改歌曲", "atmosphere": "冷色调"},
    )
    assert updated.status_code == 200
    assert updated.json()["songName"] == "后台修改歌曲"

    assert client.delete("/api/admin/song-emotion-profiles/98765432").status_code == 200
    assert client.get("/api/admin/song-emotion-profiles/98765432").status_code == 404
    assert client.post("/api/admin/song-emotion-profiles", json=sample()).status_code == 409
    actions = {x["action"] for x in client.get("/api/admin/audit-logs").json()["items"]}
    assert {"song_emotion_profile.create", "song_emotion_profile.update", "song_emotion_profile.delete"} <= actions


def test_song_emotion_profiles_require_admin(client):
    created = client.post("/api/admin/users", json={"username": "song-profile-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "song-profile-user", "password": "secure-pass-123"}).json()
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/song-emotion-profiles", headers=headers).status_code == 403
    assert client.post("/api/admin/song-emotion-profiles", json=sample("98765433"), headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"


def test_ass_admin_can_only_manage_song_emotions(client):
    created = client.post(
        "/api/admin/users",
        json={"username": "ass-only-admin", "password": "secure-pass-123"},
    ).json()
    assigned = client.put(
        f"/api/admin/users/{created['id']}/admin-role",
        json={"admin_role_code": "ass_admin"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["adminRoleCodes"] == ["ass_admin"]
    login = client.post("/api/auth/login", json={"username": "ass-only-admin", "password": "secure-pass-123"}).json()
    assert login["user"]["isSuperAdmin"] is False
    assert set(login["user"]["permissions"]) == {
        "song_emotions.read",
        "song_emotions.manage",
        "storyboard_options.read",
        "storyboard_options.manage",
    }
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/song-emotion-profiles", headers=headers).status_code == 200
    assert client.post("/api/admin/song-emotion-profiles", json=sample("98765434"), headers=headers).status_code == 201
    assert client.patch("/api/admin/song-emotion-profiles/98765434", json={"song_name": "已修改"}, headers=headers).status_code == 200
    assert client.delete("/api/admin/song-emotion-profiles/98765434", headers=headers).status_code == 200
    assert client.get("/api/admin/storyboard-options", params={"kind": "genre"}, headers=headers).status_code == 200
    assert client.get("/api/admin/dashboard", headers=headers).status_code == 403
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"
    client.delete(f"/api/admin/users/{created['id']}")


def test_song_emotion_seed_does_not_overwrite_or_restore():
    from app.database import session_factory
    from app.models import SongEmotionProfileModel, utcnow
    from app.seed import seed_system_data
    from app.song_emotions import SONG_EMOTIONS

    code = next(iter(SONG_EMOTIONS))

    async def exercise():
        async with session_factory() as session:
            item = await session.get(SongEmotionProfileModel, code)
            original_name = item.song_name
            original_deleted_at = item.deleted_at
            item.song_name = "管理员修改后"
            item.deleted_at = utcnow()
            await session.commit()
        await seed_system_data()
        async with session_factory() as session:
            item = (await session.execute(select(SongEmotionProfileModel).where(SongEmotionProfileModel.song_code == code))).scalar_one()
            assert item.song_name == "管理员修改后"
            assert item.deleted_at is not None
            item.song_name = original_name
            item.deleted_at = original_deleted_at
            await session.commit()

    asyncio.run(exercise())
