"""publish neutral identity reference prompt rules

Revision ID: e9b4c6d8f102
Revises: d7f1a9c4e203
Create Date: 2026-09-01
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9b4c6d8f102"
down_revision: Union[str, None] = "d7f1a9c4e203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTE = "人物参考卡中性化：仅锁定身份，造型优先服从歌曲曲风"

PORTRAIT = (
    "第一张参考图只定义身份参考卡的构图版式：中性灰背景，左侧大幅正面头肩像，右侧依次排列头部正面/侧面/背面和全身正面/侧面/背面，"
    "棚拍柔光，清晰写实。第二张参考图只定义人物身份：必须保持其五官、脸型、肤色、年龄感、发型和身体比例一致。"
    "所有人物统一穿纯白无图案圆领短袖T恤与中性浅灰下装，不佩戴饰品，不持道具。"
    "禁止继承任一参考图中的原服装、配饰、职业、年代、场景、文字、Logo或水印。{{extra}}"
    "附加描述只可影响人物身份特征，不得改变统一服装、背景与排版。"
)

GENERAL_POLICY = (
    "空镜严禁人物；选择人物后，参考卡仅锁定人物面部身份、年龄感、发型和身体比例，必须忽略卡片中的白色T恤、灰色背景和多视图排版。"
    "服装按 wardrobeGroupIndex 每 3 镜成组：同组严格一致，切换组时明显换整套；造型优先服从用户要求和歌曲曲风，再结合歌词情绪、叙事、场景、季节、光线与主色。"
    "未选择人物时，每个人物镜可独立生成人物，不要求跨镜身份或着装一致。"
)

GENERAL_REFERENCE_RULE = (
    "当 source 为 general 且 plannedDigitalHumanIds 非空时，人物参考图会提交给视频模型；参考卡只负责人物面部身份、五官、脸型、肤色、年龄感、发型和身体比例，"
    "必须忽略卡片的白色T恤、灰色背景、多视图排版及任何原始年代或职业暗示。shotPrompt 必须逐字使用 currentShot.outline.wardrobeByCharacter 的本组服装与动作；"
    "服装首先服从用户要求和歌曲曲风，再结合歌词情绪、叙事、场景与光线确定。同一 wardrobeGroupIndex 内服装一致，切换组后必须换装。"
)

WARDROBE_PRIORITY_RULE = (
    "服装决策优先级固定为：用户明确要求 > 歌曲曲风分类 > 歌词情绪与叙事 > 本组三镜场景和动作 > 季节、光线、主色与视觉风格；"
    "不得从人物参考卡、人物库历史描述或原素材推断服装、职业与年代。"
)


def _transform(key: str, content: str) -> str:
    if key == "portrait.digital_human_ref":
        return PORTRAIT
    if key == "story_bible.general.character_policy":
        return GENERAL_POLICY
    if key in {"storyboard_line.requirements", "general.story_outline_v2.rules"}:
        try:
            rules = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            rules = []
        if not isinstance(rules, list):
            rules = []
        if key == "storyboard_line.requirements":
            rules = [rule for rule in rules if not (isinstance(rule, str) and "source 为 general 且 plannedDigitalHumanIds 非空" in rule)]
            rules.append(GENERAL_REFERENCE_RULE)
        elif WARDROBE_PRIORITY_RULE not in rules:
            rules.append(WARDROBE_PRIORITY_RULE)
        return json.dumps(rules, ensure_ascii=False, indent=2)
    return content


def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    for key in ("portrait.digital_human_ref", "storyboard_line.requirements", "general.story_outline_v2.rules", "story_bible.general.character_policy"):
        template = connection.execute(sa.text("SELECT id, current_version_id FROM prompt_templates WHERE key=:key AND deleted_at IS NULL"), {"key": key}).mappings().first()
        if not template or not template["current_version_id"]:
            continue
        current = (
            connection.execute(sa.text("SELECT content, version FROM prompt_versions WHERE id=:id AND deleted_at IS NULL"), {"id": template["current_version_id"]})
            .mappings()
            .first()
        )
        if not current:
            continue
        version_id = f"pv-neutral-identity-{uuid.uuid4().hex[:12]}"
        connection.execute(sa.text("UPDATE prompt_versions SET status='archived', updated_at=:now WHERE id=:id"), {"id": template["current_version_id"], "now": now})
        connection.execute(
            sa.text(
                "INSERT INTO prompt_versions (id, template_id, version, content, change_note, status, created_by, published_at, created_at, updated_at, deleted_at) "
                "VALUES (:id, :template_id, :version, :content, :note, 'published', 'system-migration', :now, :now, :now, NULL)"
            ),
            {"id": version_id, "template_id": template["id"], "version": int(current["version"]) + 1, "content": _transform(key, current["content"]), "note": NOTE, "now": now},
        )
        connection.execute(
            sa.text("UPDATE prompt_templates SET current_version_id=:version_id, updated_at=:now WHERE id=:id"), {"version_id": version_id, "now": now, "id": template["id"]}
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
