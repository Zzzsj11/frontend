"""raise media generation daily limits

Revision ID: a8f1c2d3e4b5
Revises: 8c4f2d1a9e60
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8f1c2d3e4b5"
down_revision: str | None = "8c4f2d1a9e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "daily_image_limit", server_default="1000", existing_type=sa.Integer(), nullable=False)
    op.alter_column("users", "daily_video_limit", server_default="1000", existing_type=sa.Integer(), nullable=False)
    op.execute("UPDATE users SET daily_image_limit = 1000 WHERE daily_image_limit = 100")
    op.execute("UPDATE users SET daily_video_limit = 1000 WHERE daily_video_limit = 100")


def downgrade() -> None:
    op.execute("UPDATE users SET daily_image_limit = 100 WHERE daily_image_limit = 1000")
    op.execute("UPDATE users SET daily_video_limit = 100 WHERE daily_video_limit = 1000")
    op.alter_column("users", "daily_image_limit", server_default="100", existing_type=sa.Integer(), nullable=False)
    op.alter_column("users", "daily_video_limit", server_default="100", existing_type=sa.Integer(), nullable=False)
