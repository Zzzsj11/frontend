"""publish season-first wardrobe and identity-reference rules

Revision ID: f2a6d9c4b701
Revises: e9b4c6d8f102
Create Date: 2026-09-02
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a6d9c4b701"
down_revision: Union[str, None] = "e9b4c6d8f102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTE = "人物镜服装必填；季节提升为服装第二优先级；参考卡服装不继承"

GENERAL_POLICY = (
    "空镜严禁人物；所有人物镜的 shotPrompt 必须明确描写人物服装。选择人物后，参考卡仅锁定人物面部身份、年龄感、发型和身体比例，"
    "必须忽略卡片中的白色T恤、灰色背景和多视图排版。服装按 wardrobeGroupIndex 每 3 镜成组：同组严格一致，切换组时明显换整套；"
    "造型优先级固定为用户明确要求 > 季节 > 歌曲曲风 > 歌词情绪与叙事 > 场景和动作 > 光线、色彩与视觉风格，"
    "除非用户明确另有要求，必须严格符合所选季节。未选择人物时，每个人物镜可独立生成人物，不要求跨镜身份或着装一致。"
)

GENERAL_REFERENCE_RULE = (
    "当 source 为 general 且 plannedDigitalHumanIds 非空时，人物参考图会提交给视频模型；参考卡只负责人物面部身份、五官、脸型、肤色、年龄感、发型和身体比例，"
    "必须忽略卡片的白色T恤、灰色背景、多视图排版及任何原始年代或职业暗示。人物镜的 shotPrompt 必须明确描写人物服装，"
    "并逐字使用 currentShot.outline.wardrobeByCharacter 的本组完整服装与动作；优先级固定为用户明确要求 > 季节 > 歌曲曲风 > 歌词情绪与叙事 > 场景和动作 > 光线、色彩与视觉风格。"
    "除非用户明确另有要求，服装必须严格符合所选季节的温度、天气与穿着逻辑。同一 wardrobeGroupIndex 内服装一致，切换组后必须换装。"
)

ASS_REFERENCE_RULE = (
    "当 source 为 ass 且 plannedDigitalHumanIds 非空时，人物镜的 shotPrompt 必须逐一写入对应 allowedCharacters 的面部身份信息，"
    "并逐字写出 currentShot.outline.wardrobeByCharacter 中对应角色的本场完整服装。服装优先级为用户明确要求 > 季节 > 曲风 > 歌词情绪与叙事 > 场景和动作 > 光线、色彩与视觉风格；"
    "除非用户明确另有要求，必须严格符合歌曲季节设定。参考图只用于锁定面部、五官、脸型、肤色、年龄感和发型，必须明确忽略参考图中的原始服装；"
    "同一 sceneIndex 内服装一致，不同 sceneIndex 必须换装。严禁出现未列入本镜的其他人物。"
)

WARDROBE_PRIORITY_RULE = (
    "服装决策优先级固定为：用户明确要求 > 季节 > 歌曲曲风分类 > 歌词情绪与叙事 > 本组三镜场景和动作 > 光线、主色与视觉风格；"
    "wardrobeByCharacter 必须为每个已选人物设计完整服装、鞋履和必要配饰，并严格符合所选季节的温度、天气与穿着逻辑；"
    "不得从人物参考卡、人物库历史描述或原素材推断服装、职业与年代。"
)


def _transform(key: str, content: str) -> str:
    if key == "story_bible.general.character_policy":
        return GENERAL_POLICY
    try:
        rules = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        rules = []
    if not isinstance(rules, list):
        rules = []
    if key == "storyboard_line.requirements":
        rules = [
            rule
            for rule in rules
            if not (isinstance(rule, str) and ("source 为 general 且 plannedDigitalHumanIds 非空" in rule or "source 为 ass 且 plannedDigitalHumanIds 非空" in rule))
        ]
        rules.extend([ASS_REFERENCE_RULE, GENERAL_REFERENCE_RULE])
    elif key == "general.story_outline_v2.rules":
        rules = [rule for rule in rules if not (isinstance(rule, str) and "服装决策优先级固定为" in rule)]
        rules.append(WARDROBE_PRIORITY_RULE)
    return json.dumps(rules, ensure_ascii=False, indent=2)


def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    for key in ("storyboard_line.requirements", "general.story_outline_v2.rules", "story_bible.general.character_policy"):
        template = connection.execute(sa.text("SELECT id, current_version_id FROM prompt_templates WHERE key=:key AND deleted_at IS NULL"), {"key": key}).mappings().first()
        if not template or not template["current_version_id"]:
            continue
        current = (
            connection.execute(
                sa.text("SELECT content, version FROM prompt_versions WHERE id=:id AND deleted_at IS NULL"),
                {"id": template["current_version_id"]},
            )
            .mappings()
            .first()
        )
        if not current:
            continue
        version_id = f"pv-season-wardrobe-{uuid.uuid4().hex[:12]}"
        connection.execute(sa.text("UPDATE prompt_versions SET status='archived', updated_at=:now WHERE id=:id"), {"id": template["current_version_id"], "now": now})
        connection.execute(
            sa.text(
                "INSERT INTO prompt_versions (id, template_id, version, content, change_note, status, created_by, published_at, created_at, updated_at, deleted_at) "
                "VALUES (:id, :template_id, :version, :content, :note, 'published', 'system-migration', :now, :now, :now, NULL)"
            ),
            {"id": version_id, "template_id": template["id"], "version": int(current["version"]) + 1, "content": _transform(key, current["content"]), "note": NOTE, "now": now},
        )
        connection.execute(
            sa.text("UPDATE prompt_templates SET current_version_id=:version_id, updated_at=:now WHERE id=:id"),
            {"version_id": version_id, "now": now, "id": template["id"]},
        )


def downgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = connection.execute(sa.text("SELECT id, template_id FROM prompt_versions WHERE change_note=:note AND deleted_at IS NULL"), {"note": NOTE}).mappings().all()
    for row in rows:
        previous = connection.execute(
            sa.text("SELECT id FROM prompt_versions WHERE template_id=:template_id AND id<>:id AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"),
            {"template_id": row["template_id"], "id": row["id"]},
        ).scalar_one_or_none()
        connection.execute(sa.text("UPDATE prompt_versions SET status='archived', deleted_at=:now, updated_at=:now WHERE id=:id"), {"id": row["id"], "now": now})
        if previous:
            connection.execute(sa.text("UPDATE prompt_versions SET status='published', published_at=:now, updated_at=:now WHERE id=:id"), {"id": previous, "now": now})
            connection.execute(
                sa.text("UPDATE prompt_templates SET current_version_id=:previous, updated_at=:now WHERE id=:id"), {"previous": previous, "now": now, "id": row["template_id"]}
            )
