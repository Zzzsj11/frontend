import asyncio
import uuid

import pytest
from test_multi_user import create_and_login_user

from app.database import session_factory
from app.models import GenerationJobModel, ProjectModel, ProjectTaskModel, ShotAssetModel, StoryboardLineModel


@pytest.fixture
def model_case(client):
    user_id, headers = create_and_login_user(client, "model-" + uuid.uuid4().hex[:8])
    project_id, task_id = "p-" + uuid.uuid4().hex, "t-" + uuid.uuid4().hex

    async def seed():
        async with session_factory() as db:
            db.add(ProjectModel(id=project_id, user_id=user_id, name="Models"))
            await db.flush()
            db.add(
                ProjectTaskModel(id=task_id, project_id=project_id, title="Models", storyboard_type="ass", storyboard_config={"video_model": "doubao-seedance-2.0", "season": "春"})
            )
            await db.flush()
            for i in range(2):
                db.add(
                    StoryboardLineModel(
                        id=f"{task_id}-{i}",
                        project_task_id=task_id,
                        sort_order=i,
                        source="ass",
                        start_time=i * 5,
                        end_time=i * 5 + 5,
                        shot_options={"videoModel": "doubao-seedance-2.0", "resolution": "480p", "ratio": "16:9", "duration": 5, "wardrobeByCharacter": {"one": "服装"}},
                    )
                )
            await db.flush()
            db.add(
                ShotAssetModel(
                    id="asset-" + task_id, storyboard_line_id=f"{task_id}-0", cover_url="", video_url="https://test.tos/video.mp4", model_code="doubao-seedance-2.0", duration=5
                )
            )
            await db.commit()

    asyncio.run(seed())
    return user_id, headers, task_id


def change(client, headers, task, **kwargs):
    return client.post(f"/api/tasks/{task}/video-model", headers=headers, json={"model": "minimax-h3-all-in-one", **kwargs})


@pytest.mark.parametrize("kind", ["ass", "general", "general_random"])
@pytest.mark.parametrize("target", ["minimax-h3-all-in-one"])
def test_atomic_apply_all_sources_preserves_assets_timeline_and_defaults(client, model_case, kind, target):
    _, headers, task_id = model_case

    async def set_kind():
        async with session_factory() as db:
            task = await db.get(ProjectTaskModel, task_id)
            task.storyboard_type = kind
            await db.commit()

    asyncio.run(set_kind())
    preview = change(client, headers, task_id, model=target)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["count"] == 2 and len(plan["adjustments"]) == 2
    assert not plan["applied"]
    result = change(client, headers, task_id, model=target, apply=True, preview_token=plan["previewToken"])
    assert result.status_code == 200, result.text
    assert all(line["shotOptions"]["videoModel"] == target for line in result.json()["lines"])

    async def verify():
        async with session_factory() as db:
            for i in range(2):
                line = await db.get(StoryboardLineModel, f"{task_id}-{i}")
                assert line.shot_options["resolution"] == "720p"
                assert line.shot_options["wardrobeByCharacter"] == {"one": "服装"}
                assert line.start_time == i * 5 and line.end_time == i * 5 + 5
            asset = await db.get(ShotAssetModel, "asset-" + task_id)
            assert asset.video_url and asset.model_code == "doubao-seedance-2.0"
            task = await db.get(ProjectTaskModel, task_id)
            assert task.storyboard_config["video_model"] == target
            assert task.storyboard_config["season"] == "春"

    asyncio.run(verify())
    line = client.post(f"/api/tasks/{task_id}/storyboard/lines", headers=headers, json={"source": "manual"}).json()
    assert line["shotOptions"]["videoModel"] == target


def test_foreign_user_disabled_unsupported_and_active_jobs(client, model_case):
    user_id, headers, task_id = model_case
    _, foreign = create_and_login_user(client, "other-" + uuid.uuid4().hex[:8])
    assert change(client, foreign, task_id).status_code == 404
    assert change(client, headers, task_id, model="veo-3.1").status_code == 422

    async def queue():
        async with session_factory() as db:
            db.add(GenerationJobModel(id="job-" + task_id, user_id=user_id, project_task_id=task_id, kind="video", status="queued"))
            await db.commit()

    asyncio.run(queue())
    assert change(client, headers, task_id).status_code == 409


def test_stale_preview_and_incompatible_reference_are_atomic(client, model_case):
    _, headers, task_id = model_case
    plan = change(client, headers, task_id).json()

    async def edit():
        async with session_factory() as db:
            line = await db.get(StoryboardLineModel, task_id + "-0")
            line.shot_options = {**line.shot_options, "referenceVideoUrls": ["https://test.tos/ref.mp4"]}
            await db.commit()

    asyncio.run(edit())
    assert change(client, headers, task_id, apply=True, preview_token=plan["previewToken"]).status_code == 409
    blocked = change(client, headers, task_id, model="gemini-omni-1.1-flash-preview-all-in-one").json()
    assert blocked["blockers"]
    assert change(client, headers, task_id, model="gemini-omni-1.1-flash-preview-all-in-one", apply=True, preview_token=blocked["previewToken"]).status_code == 422

    async def verify():
        async with session_factory() as db:
            line = await db.get(StoryboardLineModel, task_id + "-1")
            assert line.shot_options["videoModel"] == "doubao-seedance-2.0"

    asyncio.run(verify())


def test_hidden_model_rejected_and_stale_generation_stopped_before_provider(client, model_case, monkeypatch):
    from sqlalchemy import select

    from app import main
    from app.models import AiModelModel

    _, headers, task_id = model_case

    async def hide(hidden):
        async with session_factory() as db:
            model = (await db.execute(select(AiModelModel).where(AiModelModel.code == "minimax-h3-all-in-one"))).scalar_one()
            model.user_visible = not hidden
            await db.commit()

    asyncio.run(hide(True))
    try:
        assert change(client, headers, task_id).status_code == 422
    finally:
        asyncio.run(hide(False))
    plan = change(client, headers, task_id).json()
    assert change(client, headers, task_id, apply=True, preview_token=plan["previewToken"]).status_code == 200

    async def forbidden(*args, **kwargs):
        raise AssertionError("stale configuration must not enqueue or call supplier")

    monkeypatch.setattr(main.jobs, "create", forbidden)
    response = client.post(
        "/api/generations/videos",
        headers=headers,
        json={
            "model": "doubao-seedance-2.0-all-in-one",
            "prompt": "普通场景",
            "duration": 5,
            "project_task_id": task_id,
            "storyboard_line_id": task_id + "-0",
        },
    )
    assert response.status_code == 409, response.text


def test_preview_handles_duration_and_reference_compatibility():
    from app.models import AiModelModel
    from app.task_video_model import plan_line

    model = AiModelModel(code="minimax-h3", capabilities={"durationOptions": [6, 10], "resolutions": ["720p"], "ratios": ["16:9"]})
    planned, changes, errors = plan_line({"duration": 5, "ratio": "16:9"}, model, 1)
    assert planned["duration"] == 6 and planned["resolution"] == "720p"
    assert len(changes) == 2 and not errors
    _, _, errors = plan_line({"duration": 15, "ratio": "9:16", "h3LastFrameUrl": "https://test.tos/last.png"}, model, 2)
    assert len(errors) == 3
