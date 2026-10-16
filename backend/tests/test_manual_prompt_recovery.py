from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import domain
from app.schemas import StoryboardLineUpdate


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,scene,shot,expected",
    [
        ("failed", "酒吧空镜", "两位成年人交谈", "succeeded"),
        ("failed", "", "两位成年人交谈", "failed"),
        ("running", "酒吧空镜", "两位成年人交谈", "running"),
    ],
)
async def test_manual_prompt_recovery_keeps_active_jobs_and_requires_both_prompts(monkeypatch, status, scene, shot, expected):
    line = SimpleNamespace(source="general", generation_status=status, generation_error="历史失败", scene_prompt=scene, shot_prompt="", generated_at=None)
    monkeypatch.setattr(domain, "owned_line", AsyncMock(return_value=line))
    monkeypatch.setattr(domain, "line_json", AsyncMock(return_value={}))
    db = SimpleNamespace(commit=AsyncMock())
    await domain.update_line("line", StoryboardLineUpdate(shot_prompt=shot), SimpleNamespace(id="owner"), db)
    assert line.generation_status == expected
    assert line.generation_error == (None if expected == "succeeded" else "历史失败")
    db.commit.assert_awaited_once()
