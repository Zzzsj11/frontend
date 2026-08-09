"""digital human thumbnails

Revision ID: c3f1a29e6b40
Revises: b7d02d13a9f4
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3f1a29e6b40"
down_revision: Union[str, None] = "b7d02d13a9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("digital_humans", sa.Column("avatar_thumbnail_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("digital_humans", "avatar_thumbnail_url")
