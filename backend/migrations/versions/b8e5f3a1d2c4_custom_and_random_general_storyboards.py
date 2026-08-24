"""publish customized and random general storyboard prompt policy

Revision ID: b8e5f3a1d2c4
Revises: a7d4e2f9c1b8
Create Date: 2026-08-24
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e5f3a1d2c4"
down_revision: Union[str, None] = "a7d4e2f9c1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RELEASE_NOTE = "定制通用分镜按手选人物传参考图、随机通用分镜直出视频"
OLD_RULE = "当 source 为 general 且 plannedDigitalHumanIds 非空时，人物参考图不会提交给视频模型；shotPrompt 应按本镜独立设计人物外貌与服装，不要求不同镜头是同一个人，禁止要求沿用固定脸或固定服装。"
NEW_RULES = [
    "当 source 为 general 且 plannedDigitalHumanIds 非空时，人物参考图会提交给视频模型；shotPrompt 必须明确保持参考人物的面部身份、五官、脸型、肤色、年龄感和发型一致，并严格使用本镜规划的服装与动作。",
    "当 source 为 general、shotType 为 character 且 plannedDigitalHumanIds 为空时，digitalHumanIds 必须为空，但 shotPrompt 应依据曲风、性别、年龄、场景和动作自由设计本镜人物，不要求跨镜为同一个人。",
]


def _upgrade_requirements(content: str) -> str:
    rules = json.loads(content)
    rules = [rule for rule in rules if rule != OLD_RULE and "人物参考图不会提交给视频模型" not in rule]
    for rule in NEW_RULES:
        if rule not in rules:
            rules.append(rule)
    return json.dumps(rules, ensure_ascii=False, indent=2)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    template = bind.execute(sa.text("SELECT id, current_version_id FROM prompt_templates WHERE key='storyboard_line.requirements' AND deleted_at IS NULL")).mappings().first()
    if not template or not template["current_version_id"]:
        return
    current = bind.execute(
        sa.text("SELECT content FROM prompt_versions WHERE id=:id AND deleted_at IS NULL"),
        {"id": template["current_version_id"]},
    ).scalar_one_or_none()
    if not current:
        return
    version = (
        int(
            bind.execute(
                sa.text("SELECT COALESCE(MAX(version), 0) FROM prompt_versions WHERE template_id=:id"),
                {"id": template["id"]},
            ).scalar_one()
        )
        + 1
    )
    version_id = f"pv-storyboard_line.requirements-custom-general-v{version}"
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
            "content": _upgrade_requirements(current),
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
    row = (
        bind.execute(
            sa.text("SELECT id, template_id FROM prompt_versions WHERE change_note=:note AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"),
            {"note": RELEASE_NOTE},
        )
        .mappings()
        .first()
    )
    if not row:
        return
    previous = bind.execute(
        sa.text("SELECT id FROM prompt_versions WHERE template_id=:template_id AND id<>:id AND deleted_at IS NULL ORDER BY version DESC LIMIT 1"),
        {"template_id": row["template_id"], "id": row["id"]},
    ).scalar_one_or_none()
    bind.execute(
        sa.text("UPDATE prompt_versions SET deleted_at=:now, status='archived', updated_at=:now WHERE id=:id"),
        {"id": row["id"], "now": now},
    )
    if previous:
        bind.execute(
            sa.text("UPDATE prompt_versions SET status='published', published_at=:now, updated_at=:now WHERE id=:id"),
            {"id": previous, "now": now},
        )
        bind.execute(
            sa.text("UPDATE prompt_templates SET current_version_id=:previous, updated_at=:now WHERE id=:template_id"),
            {"previous": previous, "now": now, "template_id": row["template_id"]},
        )
