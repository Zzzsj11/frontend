"""storyboard option items

通用分镜选项全量可配：storyboard_option_items 表承载曲风三级分类树（genre）与
季节（season）/ 年龄段（age_group）/ 画面风格（visual_style）选项，
由管理后台维护，公开端点组装 GeneralStoryboardOptions 给生成弹窗。

Revision ID: f8c2a15d7e09
Revises: e5b81f3a9c72
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8c2a15d7e09"
down_revision: Union[str, None] = "e5b81f3a9c72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storyboard_option_items",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("parent_id", sa.String(80), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["storyboard_option_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("kind", "parent_id", "sort_order", "deleted_at"):
        op.create_index(op.f(f"ix_storyboard_option_items_{column}"), "storyboard_option_items", [column])


def downgrade() -> None:
    op.drop_table("storyboard_option_items")
