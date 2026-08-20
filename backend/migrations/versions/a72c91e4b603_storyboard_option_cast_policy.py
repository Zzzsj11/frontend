"""add inheritable cast policy to storyboard genre options

Revision ID: a72c91e4b603
Revises: e1a4b6c8d0f2
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a72c91e4b603"
down_revision: str | None = "e1a4b6c8d0f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("storyboard_option_items", sa.Column("cast_policy", sa.String(length=32), nullable=True))
    op.execute(sa.text("UPDATE storyboard_option_items SET cast_policy = 'required' WHERE kind = 'genre' AND name IN ('爱情积极', '爱情消极') AND deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_column("storyboard_option_items", "cast_policy")
