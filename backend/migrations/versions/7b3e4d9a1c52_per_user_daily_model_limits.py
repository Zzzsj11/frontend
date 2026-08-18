"""per-user daily model call limits

Revision ID: 7b3e4d9a1c52
Revises: 48d21f6ac903
"""

import sqlalchemy as sa
from alembic import op

revision = "7b3e4d9a1c52"
down_revision = "48d21f6ac903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("daily_chat_limit", sa.Integer(), server_default="1000", nullable=False))
    op.add_column("users", sa.Column("daily_image_limit", sa.Integer(), server_default="100", nullable=False))
    op.add_column("users", sa.Column("daily_video_limit", sa.Integer(), server_default="100", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "daily_video_limit")
    op.drop_column("users", "daily_image_limit")
    op.drop_column("users", "daily_chat_limit")
