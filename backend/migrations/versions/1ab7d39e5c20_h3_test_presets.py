"""persist H3 test presets and archived media

Revision ID: 1ab7d39e5c20
Revises: f8c2a15d7e09
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1ab7d39e5c20"
down_revision: Union[str, None] = "f8c2a15d7e09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "h3_test_presets",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), server_default="", nullable=False),
        sa.Column("duration", sa.Float(), server_default="8", nullable=False),
        sa.Column("aspect_ratio", sa.String(80), server_default="16:9 (Widescreen)", nullable=False),
        sa.Column("input_media", sa.JSON(), nullable=False),
        sa.Column("output_media", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.String(80), nullable=True),
        sa.Column("task_status", sa.String(32), server_default="READY", nullable=False),
        sa.Column("usage_data", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "mode", "task_id", "task_status", "sort_order", "deleted_at"):
        op.create_index(op.f(f"ix_h3_test_presets_{column}"), "h3_test_presets", [column])


def downgrade() -> None:
    op.drop_table("h3_test_presets")
