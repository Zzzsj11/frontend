"""Align headshot publishing metadata; preserve operator additions and all content versions."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "d6f2a8c1e903"
down_revision: str = "b3f7a1c5e902"
branch_labels = None
depends_on = None

KEY = "portrait.digital_human_ref"

# Frozen metadata: never import mutable application defaults into migrations.
LEGACY_METADATA = {
    "name": "数字人定妆照提示词",
    "description": "数字人三视图定妆照的图生图提示词模板；extra 段由后端按描述/风格拼装。",
    "variables": {"extra": "角色描述与画面风格附加段（代码拼装，可为空串）"},
    "required_fragments": ["第一张参考图", "第二张参考图", "禁止继承"],
}
HEADSHOT_METADATA = {
    "name": "数字人单人正面头肩大头照提示词",
    "description": "1024x1536 竖版单人身份照；有图时只参考一张身份图，无图时按 description 生成，style 仅用于资产分类、不入画。",
    "variables": {"extra": "仅由 description 拼装的角色身份描述附加段，可为空串；不含资产分类 style"},
    "required_fragments": [
        "单人正面头肩大头照",
        "五官、脸型、肤色、年龄感和发型",
        "无身份参考图时",
        "不得成人化",
        "纯白无图案圆领短袖T恤",
        "不佩戴饰品",
        "中性灰",
        "棚拍柔光",
        "禁止继承",
        "无边框、无文字、无Logo、无水印",
    ],
}


def _replace_base_metadata(source: dict, target: dict) -> None:
    # Typed JSON columns work with both PostgreSQL and isolated SQLite tests.
    templates = sa.table(
        "prompt_templates",
        sa.column("id", sa.String(80)),
        sa.column("key", sa.String(120)),
        sa.column("name", sa.String(160)),
        sa.column("description", sa.Text()),
        sa.column("variables", sa.JSON()),
        sa.column("required_fragments", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    active_portrait = sa.and_(templates.c.key == KEY, templates.c.deleted_at.is_(None))
    rows = connection.execute(sa.select(templates).where(active_portrait)).mappings().all()
    for row in rows:
        # Only exact known base fragments are replaced. Never substring-filter:
        # an operator safety rule may itself mention a legacy reference image.
        additional_fragments = [
            fragment for fragment in (row["required_fragments"] or []) if fragment not in source["required_fragments"] and fragment not in target["required_fragments"]
        ]
        values = {
            "name": target["name"],
            "description": target["description"],
            "variables": {**(row["variables"] or {}), **target["variables"]},
            "required_fragments": [*target["required_fragments"], *additional_fragments],
        }
        # Replays are no-ops, including updated_at. Never insert a missing key.
        if all(row[field] == value for field, value in values.items()):
            continue
        connection.execute(templates.update().where(active_portrait, templates.c.id == row["id"]).values(**values, updated_at=datetime.now(timezone.utc)))


def upgrade() -> None:
    _replace_base_metadata(LEGACY_METADATA, HEADSHOT_METADATA)


def downgrade() -> None:
    _replace_base_metadata(HEADSHOT_METADATA, LEGACY_METADATA)
