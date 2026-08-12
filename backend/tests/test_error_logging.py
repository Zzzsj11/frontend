"""后台 LLM 错误埋点：log_background_error 落库、逐句生成解析/调用失败的留痕。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import TEST_DB


def _error_log_row(error_code: str) -> dict:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM api_error_logs WHERE error_code = ?", (error_code,)).fetchone()
        assert row is not None, f"error log {error_code} 未落库"
        return dict(row)
    finally:
        connection.close()


def _error_log_by_path(error_type: str, path: str) -> dict:
    """按类型 + 路径精确定位（避免同秒 created_at 并列时取错行）。"""
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM api_error_logs WHERE error_type = ? AND path = ? ORDER BY created_at DESC LIMIT 1",
            (error_type, path),
        ).fetchone()
        assert row is not None, f"没有找到 {error_type} @ {path} 的错误日志"
        return dict(row)
    finally:
        connection.close()


def _latest_error_log(error_type: str) -> dict:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM api_error_logs WHERE error_type = ? ORDER BY created_at DESC LIMIT 1", (error_type,)).fetchone()
        assert row is not None, f"没有找到 {error_type} 类型的错误日志"
        return dict(row)
    finally:
        connection.close()


async def test_log_background_error_persists_row(client) -> None:
    from app.error_logging import log_background_error

    code = await log_background_error(
        user_id="u-test",
        path="/llm/test-op",
        status_code=502,
        error_type="LLMCallError",
        message="LLM 调用失败（test-op）：boom",
        traceback_text="traceback text",
        project_id="proj-1",
        project_task_id="task-1",
    )
    assert code.startswith("ERR-")
    row = _error_log_row(code)
    assert row["method"] == "POST"
    assert row["path"] == "/llm/test-op"
    assert row["status_code"] == 502
    assert row["error_type"] == "LLMCallError"
    assert row["user_id"] == "u-test"
    assert "boom" in row["message"]
    assert json.loads(row["request_payload"]) == {"projectId": "proj-1", "projectTaskId": "task-1"}


class _FakeOpenAI:
    """按顺序吐出预置文本的 AsyncOpenAI 替身。"""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        text = self._texts.pop(0)
        return SimpleNamespace(id="req-fake", usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _FailingOpenAI:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        raise self._error


def _patch_llm(monkeypatch, client_stub) -> None:
    from app import storyboard_prompt

    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_api_key="fake-key"))
    monkeypatch.setattr(storyboard_prompt, "AsyncOpenAI", lambda **kwargs: client_stub)


async def test_storyboard_line_parse_failure_logged_then_repaired(client, monkeypatch) -> None:
    """初次返回不可解析内容：LLMParseError 入库，随后 repair 调用恢复正常返回。"""
    from app import storyboard_prompt

    valid = json.dumps({"scenePrompt": "sunlit room", "shotPrompt": "slow push in", "digitalHumanIds": ["dh-a"]})
    _patch_llm(monkeypatch, _FakeOpenAI(["这段输出完全没有 JSON", valid]))

    result = await storyboard_prompt.generate_storyboard_line(
        source="ass",
        current={"lyrics": "第一句", "plannedDigitalHumanIds": ["dh-a"]},
        full_context={"allLyrics": ["第一句"]},
        allowed_humans=[{"id": "dh-a", "name": "角色A"}],
    )
    assert result["scenePrompt"] == "sunlit room"
    # 首次 + repair 两次调用都有留痕
    assert [record["operation"] for record in result["usageRecords"]] == ["storyboard_line", "storyboard_line_repair"]

    row = _latest_error_log("LLMParseError")
    assert row["path"] == "/api/tasks/storyboard-lines/generate"
    assert "初次解析失败" in row["message"]


async def test_storyboard_line_call_failure_logged(client, monkeypatch) -> None:
    """LLM 调用本身异常：LLMCallError 入库（/llm/{operation} 路径），并向上抛 StoryboardPromptError。"""
    from app import storyboard_prompt

    _patch_llm(monkeypatch, _FailingOpenAI(RuntimeError("连接重置")))

    with pytest.raises(storyboard_prompt.StoryboardPromptError, match="连接重置"):
        await storyboard_prompt.generate_storyboard_line(
            source="ass",
            current={"lyrics": "第一句", "plannedDigitalHumanIds": []},
            full_context={"allLyrics": ["第一句"]},
            allowed_humans=[],
        )

    row = _latest_error_log("LLMCallError")
    assert row["path"] == "/llm/storyboard_line"
    assert row["status_code"] == 502
    assert "连接重置" in row["message"]


async def test_scene_plan_parse_failure_logged_then_retried(client) -> None:
    """场景规划首次输出不可解析：LLMParseError 入库（ass_scene_plan 路径），重试后正常返回。"""
    from app import storyboard_prompt

    valid = json.dumps(
        {
            "globalVisual": {
                "visualStyle": "电影写实",
                "colorPalette": "暖橙",
                "lighting": "柔光",
                "weather": "晴",
                "timeOfDay": "黄昏",
                "continuityRules": ["服装一致"],
            },
            "scenes": [
                {
                    "lineStart": 0,
                    "lineEnd": 1,
                    "locationName": "天台",
                    "mood": "释然",
                    "emotion": "平静",
                    "visualTone": "暖调",
                    "narrativePurpose": "收束",
                }
            ],
        }
    )
    result = await storyboard_prompt._plan_ass_scenes(
        _FakeOpenAI(["抱歉，我无法输出 JSON。", valid]),
        lyric_lines=[{"index": 0, "text": "第一句"}, {"index": 1, "text": "第二句"}],
        structural_notes=[],
        emotion={},
        selected_humans=[],
        extra_requirement="",
        expected_scenes=1,
        usage_records=[],
    )
    assert result["scenes"][0]["locationName"] == "天台"

    row = _error_log_by_path("LLMParseError", "/tasks/ass_scene_plan/ass_scene_plan")
    assert "场景规划第1次解析失败" in row["message"]
    assert row["status_code"] == 502


async def test_scene_segment_parse_failure_logged_then_retried(client) -> None:
    """场景段逐镜规划首次输出不可解析：LLMParseError 入库（ass_scene_segment_{n} 路径），重试后正常返回。"""
    from app import storyboard_prompt

    valid = json.dumps(
        {
            "motifs": [],
            "shots": [
                {
                    "index": 0,
                    "shotType": "character",
                    "intent": "登场",
                    "requiredCharacterIds": ["dh-a"],
                    "characterAction": "回头凝视",
                    "emotionalFocus": "释然",
                    "cameraPurpose": "中景定身",
                    "motifIds": [],
                    "gapAfterAllocation": "none",
                }
            ],
        }
    )
    result = await storyboard_prompt._generate_scene_shots(
        _FakeOpenAI(["先导说明文字", valid]),
        scene={"locationName": "天台", "mood": "释然", "emotion": "平静", "visualTone": "暖调", "narrativePurpose": "收束"},
        scene_segments=[{"start": 0.0, "end": 4.0, "lyrics": "第一句", "segmentType": "lyric", "timelineLabel": "第一句"}],
        global_visual={},
        emotion={},
        selected_humans=[{"id": "dh-a", "name": "角色A"}],
        extra_requirement="",
        scene_index=0,
        role_ids=["dh-a"],
        lyric_total=1,
        usage_records=[],
    )
    assert result["shots"][0]["requiredCharacterIds"] == ["dh-a"]

    row = _error_log_by_path("LLMParseError", "/tasks/ass_scene_segment/ass_scene_segment_1")
    assert "场景段1第1次解析失败" in row["message"]
