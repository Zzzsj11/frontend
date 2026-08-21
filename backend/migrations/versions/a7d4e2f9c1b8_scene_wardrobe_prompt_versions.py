"""publish scene wardrobe and general random-cast prompt versions

Revision ID: a7d4e2f9c1b8
Revises: f13c7a9e2b40
Create Date: 2026-08-20
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4e2f9c1b8"
down_revision: Union[str, None] = "f13c7a9e2b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RELEASE_NOTE = "ASS按大场景换装、通用MV逐镜人物自由生成"

JSON_ADDITIONS = {
    "ass.scene_plan.rules": [
        "每个 scenes 条目必须在 wardrobeByCharacter 中为每个 selectedCharacters 的 id 设计一套符合地点、季节、时代与情绪的完整服装；同一大场景内保持该套服装一致，切换到相邻大场景时必须明显更换整套服装，禁止沿用定妆参考图服装。",
        "人物的面部、五官、脸型、肤色、年龄感和发型作为身份锚点全片一致；服装不属于身份锚点，必须按大场景变化。",
    ],
    "ass.scene_shots.rules": ["sceneContext.wardrobeByCharacter 是本大场景唯一有效的服装设定；本场景所有人物镜必须使用对应服装，不得沿用人物定妆参考图中的原始服装。"],
    "storyboard_line.requirements": [
        "当 source 为 ass 且 plannedDigitalHumanIds 非空时，参考图只用于锁定面部身份和发型；shotPrompt 必须逐字写出 currentShot.outline.wardrobeByCharacter 对应服装，明确忽略参考图原始服装，同一 sceneIndex 内服装一致、不同 sceneIndex 必须换装。",
        "当 source 为 general 且 plannedDigitalHumanIds 非空时，人物参考图不会提交给视频模型；shotPrompt 应按本镜独立设计人物外貌与服装，不要求不同镜头是同一个人，禁止要求沿用固定脸或固定服装。",
    ],
    "story_bible.ass.negative_constraints": [
        "不得改变人物面部身份",
        "不得沿用参考图原始服装，必须执行本大场景服装方案",
    ],
}

TEXT_ADDITIONS = {
    "storyboard_line.system": "角色面部身份与场景服装是不同约束：ASS 保护面部身份并按大场景换装；通用 MV 人物镜逐镜自由生成，不要求跨镜身份或服装一致。",
    "story_bible.ass.character_policy": "参考图仅用于保护人物面部身份、年龄感和发型；服装不跟随参考图。同一大场景必须使用 wardrobeByCharacter 规划服装，切换大场景必须更换明显不同的整套服装。",
    "story_bible.ass.location_rule": "同一大场景内服装连续，切换大场景时服装必须变化。",
    "story_bible.ass.style_priority_default": "统一人物面部身份；同一大场景内服装连续、切换大场景明显换装。",
    "story_bible.general.character_policy": "人物镜不向视频模型提交人物参考图，每个镜头可独立生成不同人物外貌与服装，不要求跨镜头身份或着装一致。",
}


def _upgraded_content(key: str, content: str) -> str:
    if key in JSON_ADDITIONS:
        try:
            rules = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            rules = []
        if not isinstance(rules, list):
            rules = []
        if key == "story_bible.ass.negative_constraints":
            rules = [rule for rule in rules if rule != "不得改变人物服装与身份"]
        for rule in JSON_ADDITIONS[key]:
            if rule not in rules:
                rules.append(rule)
        return json.dumps(rules, ensure_ascii=False, indent=2)
    addition = TEXT_ADDITIONS[key]
    return content if addition in content else f"{content}\n{addition}"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    for key in [*JSON_ADDITIONS, *TEXT_ADDITIONS]:
        template = (
            bind.execute(
                sa.text("SELECT id, current_version_id FROM prompt_templates WHERE key=:key AND deleted_at IS NULL"),
                {"key": key},
            )
            .mappings()
            .first()
        )
        if not template or not template["current_version_id"]:
            continue
        current = (
            bind.execute(
                sa.text("SELECT content FROM prompt_versions WHERE id=:id AND deleted_at IS NULL"),
                {"id": template["current_version_id"]},
            )
            .mappings()
            .first()
        )
        if not current:
            continue
        version = (
            int(
                bind.execute(
                    sa.text("SELECT COALESCE(MAX(version), 0) FROM prompt_versions WHERE template_id=:template_id"),
                    {"template_id": template["id"]},
                ).scalar_one()
            )
            + 1
        )
        version_id = f"pv-{key}-wardrobe-v{version}"
        bind.execute(
            sa.text("UPDATE prompt_versions SET status='archived', updated_at=:now WHERE id=:id AND status='published'"),
            {"id": template["current_version_id"], "now": now},
        )
        bind.execute(
            sa.text(
                "INSERT INTO prompt_versions "
                "(id, template_id, version, content, change_note, status, created_by, published_at, created_at, updated_at, deleted_at) "
                "VALUES (:id, :template_id, :version, :content, :note, 'published', 'system-migration', :now, :now, :now, NULL)"
            ),
            {
                "id": version_id,
                "template_id": template["id"],
                "version": version,
                "content": _upgraded_content(key, current["content"]),
                "note": RELEASE_NOTE,
                "now": now,
            },
        )
        bind.execute(
            sa.text("UPDATE prompt_templates SET current_version_id=:version_id, updated_at=:now WHERE id=:id"),
            {"version_id": version_id, "now": now, "id": template["id"]},
        )


def downgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = (
        bind.execute(
            sa.text("SELECT id, template_id FROM prompt_versions WHERE change_note=:note AND deleted_at IS NULL"),
            {"note": RELEASE_NOTE},
        )
        .mappings()
        .all()
    )
    for row in rows:
        previous = bind.execute(
            sa.text("SELECT id FROM prompt_versions WHERE template_id=:template_id AND id<>:id AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"),
            {"template_id": row["template_id"], "id": row["id"]},
        ).scalar_one_or_none()
        bind.execute(sa.text("UPDATE prompt_versions SET deleted_at=:now, status='archived', updated_at=:now WHERE id=:id"), {"id": row["id"], "now": now})
        if previous:
            bind.execute(sa.text("UPDATE prompt_versions SET status='published', published_at=:now, updated_at=:now WHERE id=:id"), {"id": previous, "now": now})
            bind.execute(
                sa.text("UPDATE prompt_templates SET current_version_id=:previous, updated_at=:now WHERE id=:template_id"),
                {"previous": previous, "now": now, "template_id": row["template_id"]},
            )
