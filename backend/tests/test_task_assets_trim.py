"""P2 切换路径瘦身：GET /tasks/{id} 的 N+1 消除与 history=0 响应裁剪、单行全量端点。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import session_factory
from app.domain import uid
from app.models import (
    ProjectModel,
    ProjectTaskModel,
    SceneAssetModel,
    ShotAssetModel,
    StoryboardLineModel,
    UserModel,
)


async def _make_task_with_assets(db) -> tuple[str, str, str]:
    """创建任务 + 一条分镜 + 场景图 2 版 / 视频 3 版（最新为 current），返回 (task_id, line_id, 另一个任务的 task_id)。"""
    # 用 username 锁定 admin，避免其他测试先跑创建用户后归属漂移（见 test_storyboard_quality.py 注释）
    user = (await db.execute(select(UserModel.id).where(UserModel.username == "admin"))).scalar_one()
    project = ProjectModel(id=uid("proj"), user_id=user, name="trim")
    db.add(project)
    await db.flush()
    task = ProjectTaskModel(id=uid("task"), project_id=project.id, title="trim", storyboard_type="ass", status="ready")
    other = ProjectTaskModel(id=uid("task"), project_id=project.id, title="other", storyboard_type="ass", status="ready")
    db.add_all([task, other])
    await db.flush()
    line = StoryboardLineModel(
        id=uid("line"),
        project_task_id=task.id,
        sort_order=0,
        lyrics="line 0",
        start_time=0.0,
        end_time=5.0,
        planned_duration=5,
        generation_status="succeeded",
    )
    db.add(line)
    await db.flush()
    for index in range(2):
        db.add(
            SceneAssetModel(
                id=uid("scene"),
                storyboard_line_id=line.id,
                image_url=f"https://example.com/scene-{index}.png",
                is_current=index == 1,
            )
        )
    for index in range(3):
        db.add(
            ShotAssetModel(
                id=uid("shot"),
                storyboard_line_id=line.id,
                cover_url=f"https://example.com/cover-{index}.png",
                video_url=f"https://example.com/video-{index}.mp4",
                duration=5.0,
                is_current=index == 2,
            )
        )
    await db.commit()
    return task.id, line.id, other.id


@pytest.mark.asyncio
async def test_get_task_default_returns_full_asset_history(client):
    """默认（不带 history 参数）保持全量资产历史，兼容现有调用方。"""
    async with session_factory() as db:
        task_id, _, _ = await _make_task_with_assets(db)

    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    line = r.json()["lines"][0]
    assert len(line["sceneAssets"]) == 2
    assert len(line["shotAssets"]) == 3
    assert "shotAssetCount" not in line
    assert [a["isCurrent"] for a in line["shotAssets"]] == [False, False, True]


@pytest.mark.asyncio
async def test_get_task_history_trimmed(client):
    """history=0：每行只回传当前选用资产，并附历史版本计数。"""
    async with session_factory() as db:
        task_id, _, _ = await _make_task_with_assets(db)

    r = client.get(f"/api/tasks/{task_id}?history=0")
    assert r.status_code == 200
    line = r.json()["lines"][0]
    assert line["sceneAssetCount"] == 2
    assert line["shotAssetCount"] == 3
    assert line["voiceAssetCount"] == 0
    assert len(line["sceneAssets"]) == 1
    assert len(line["shotAssets"]) == 1
    assert line["shotAssets"][0]["isCurrent"] is True
    assert line["shotAssets"][0]["videoUrl"] == "https://example.com/video-2.mp4"


@pytest.mark.asyncio
async def test_get_storyboard_line_returns_full_history(client):
    """单行端点返回完整资产历史（详情弹窗懒加载 / 生成落定增量合并）。"""
    async with session_factory() as db:
        task_id, line_id, _ = await _make_task_with_assets(db)

    r = client.get(f"/api/tasks/{task_id}/storyboard-lines/{line_id}")
    assert r.status_code == 200
    line = r.json()
    assert line["id"] == line_id
    assert len(line["shotAssets"]) == 3
    assert len(line["sceneAssets"]) == 2
    assert "shotAssetCount" not in line


@pytest.mark.asyncio
async def test_get_storyboard_line_task_mismatch(client):
    """单行端点：分镜不属于指定子项目时 422；不存在的行 404。"""
    async with session_factory() as db:
        task_id, line_id, other_task_id = await _make_task_with_assets(db)

    r = client.get(f"/api/tasks/{other_task_id}/storyboard-lines/{line_id}")
    assert r.status_code == 422
    assert client.get(f"/api/tasks/{task_id}/storyboard-lines/line-missing").status_code == 404
