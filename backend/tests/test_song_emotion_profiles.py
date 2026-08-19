"""ASS 歌曲情感库管理接口与种子保护。"""

import asyncio
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sample(code: str = "98765432") -> dict:
    return {
        "song_code": code,
        "song_name": "测试歌曲",
        "artists": "测试歌手",
        "lyrics": "第一句\n第二句",
        "primary_category": "流行歌曲",
        "secondary_category": "通用积极",
        "tertiary_category": "生活",
        "material_category": "流行歌曲-通用积极-生活",
        "seasons": "春",
        "atmosphere": "明亮 | 温暖",
        "character_setting": "无需人物",
        "status": 2,
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
    assert detail.json()["lyrics"] == "第一句\n第二句"
    assert detail.json()["characterSetting"] == "无需人物"
    assert detail.json()["status"] == 2
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
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "secure-admin-123"})
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
    changed = client.post(
        "/api/auth/change-password",
        headers=bearer(login["accessToken"]),
        json={"current_password": "secure-pass-123", "new_password": "secure-pass-456"},
    ).json()
    headers = bearer(changed["accessToken"])
    assert client.get("/api/admin/song-emotion-profiles", headers=headers).status_code == 200
    assert client.post("/api/admin/song-emotion-profiles", json=sample("98765434"), headers=headers).status_code == 201
    assert client.patch("/api/admin/song-emotion-profiles/98765434", json={"song_name": "已修改"}, headers=headers).status_code == 200
    assert client.delete("/api/admin/song-emotion-profiles/98765434", headers=headers).status_code == 200
    assert client.get("/api/admin/storyboard-options", params={"kind": "genre"}, headers=headers).status_code == 200
    assert client.get("/api/admin/dashboard", headers=headers).status_code == 403
    assert client.get("/api/admin/users", headers=headers).status_code == 403
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "secure-admin-123"})
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


def xlsx_file(rows: list[list]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["编号", "歌名", "歌星", "歌词", "一级分类", "二级分类", "三级分类", "素材分类", "季节", "氛围基调", "人物设定", "状态"])
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


def test_song_emotion_xlsx_import_is_atomic_and_rejects_duplicates(client):
    row = [
        "98765991",
        "导入歌曲",
        "导入歌手",
        "导入歌词",
        "流行歌曲",
        "通用积极",
        "生活",
        "流行歌曲-通用积极-生活",
        "春",
        "明亮",
        "无需人物",
        2,
    ]
    imported = client.post(
        "/api/admin/song-emotion-profiles/import-xlsx",
        files={"file": ("songs.xlsx", xlsx_file([row]).getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    detail = client.get("/api/admin/song-emotion-profiles/98765991").json()
    assert detail["lyrics"] == "导入歌词"
    assert detail["characterSetting"] == "无需人物"

    duplicate = client.post(
        "/api/admin/song-emotion-profiles/import-xlsx",
        files={"file": ("songs.xlsx", xlsx_file([row, [*row[:1], "另一首歌", *row[2:]]]).getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert duplicate.status_code == 409
    assert "文件内重复" in duplicate.json()["detail"]
    assert "已存在于数据库" in duplicate.json()["detail"]
    client.delete("/api/admin/song-emotion-profiles/98765991")
