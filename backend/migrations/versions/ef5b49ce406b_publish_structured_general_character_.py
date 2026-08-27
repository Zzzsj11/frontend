"""publish structured general character prompt rules

Revision ID: ef5b49ce406b
Revises: c1f7a9e3d502
Create Date: 2026-08-26 19:59:20.171374
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ef5b49ce406b"
down_revision: Union[str, None] = "c1f7a9e3d502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    template = (
        connection.execute(
            sa.text("SELECT id, current_version_id FROM prompt_templates WHERE key = :key AND deleted_at IS NULL"),
            {"key": "storyboard_line.requirements"},
        )
        .mappings()
        .first()
    )
    if not template or not template["current_version_id"]:
        return
    current = (
        connection.execute(
            sa.text("SELECT content, version FROM prompt_versions WHERE id = :id AND deleted_at IS NULL"),
            {"id": template["current_version_id"]},
        )
        .mappings()
        .first()
    )
    if not current:
        return
    try:
        rules = json.loads(current["content"])
    except (TypeError, json.JSONDecodeError):
        return
    if not isinstance(rules, list):
        return
    marker = "不得写入生成规模、画幅、清晰度、模型或渠道等运行参数"
    if any(marker in str(rule) for rule in rules):
        return
    rules = [
        rule.replace(
            "shotPrompt 描述人物表演、人数、构图、景别、运镜和镜头内节奏，并写明无字幕、无水印、无 Logo。",
            "shotPrompt 描述人物表演、人数、构图、景别、运镜和镜头内节奏，并写明无字幕、无水印、无 Logo；不得写入生成规模、画幅、清晰度、模型或渠道等运行参数。",
        ).replace(
            "构图必须适配指定画幅比例，动作必须能在 plannedDuration 内完成。",
            "动作必须能在 plannedDuration 内完成；画幅与清晰度由结构化运行参数控制，禁止写入 scenePrompt 或 shotPrompt。",
        )
        for rule in rules
    ]
    rules.extend(
        [
            "通用人物镜开头必须使用【人物镜*人数*年龄性别】和【主角：人物描述】；例如【人物镜*单人*中年女性】【主角：三十多岁女性，短发，穿深色风衣】。",
            "选择人物时年龄、性别及主角描述必须来自 allowedCharacters；未选择人物时依据曲风与配置自由设计。不得输出本镜独立选角编号或 R1-2 一类内部编号。",
            "生成规模、画幅、清晰度、模型和渠道只属于结构化运行参数，不得出现在 scenePrompt 或 shotPrompt。",
        ]
    )
    new_version = int(current["version"]) + 1
    version_id = f"pv-storyboard-line-requirements-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    connection.execute(
        sa.text("UPDATE prompt_versions SET status = 'archived', updated_at = :now WHERE id = :id"),
        {"id": template["current_version_id"], "now": now},
    )
    connection.execute(
        sa.text(
            """INSERT INTO prompt_versions
            (id, template_id, version, content, change_note, status, created_by, published_at, created_at, updated_at)
            VALUES (:id, :template_id, :version, :content, :note, 'published', 'system', :now, :now, :now)"""
        ),
        {
            "id": version_id,
            "template_id": template["id"],
            "version": new_version,
            "content": json.dumps(rules, ensure_ascii=False, indent=2),
            "note": "通用分镜运行参数分离与人物镜结构化标签",
            "now": now,
        },
    )
    connection.execute(
        sa.text("UPDATE prompt_templates SET current_version_id = :version_id, updated_at = :now WHERE id = :id"),
        {"version_id": version_id, "now": now, "id": template["id"]},
    )


def downgrade() -> None:
    connection = op.get_bind()
    published = (
        connection.execute(
            sa.text(
                """SELECT pv.id, pv.template_id FROM prompt_versions pv
            JOIN prompt_templates pt ON pt.id = pv.template_id
            WHERE pt.key = :key AND pv.change_note = :note AND pv.deleted_at IS NULL
            ORDER BY pv.version DESC LIMIT 1"""
            ),
            {"key": "storyboard_line.requirements", "note": "通用分镜运行参数分离与人物镜结构化标签"},
        )
        .mappings()
        .first()
    )
    if not published:
        return
    previous = connection.execute(
        sa.text("SELECT id FROM prompt_versions WHERE template_id = :template_id AND id != :id AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"),
        {"template_id": published["template_id"], "id": published["id"]},
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    connection.execute(
        sa.text("UPDATE prompt_versions SET status = 'draft', deleted_at = :now, updated_at = :now WHERE id = :id"),
        {"id": published["id"], "now": now},
    )
    if previous:
        connection.execute(sa.text("UPDATE prompt_versions SET status = 'published', updated_at = :now WHERE id = :id"), {"id": previous, "now": now})
        connection.execute(
            sa.text("UPDATE prompt_templates SET current_version_id = :previous, updated_at = :now WHERE id = :id"),
            {"previous": previous, "now": now, "id": published["template_id"]},
        )
