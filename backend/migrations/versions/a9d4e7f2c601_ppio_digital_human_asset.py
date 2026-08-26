"""add PPIO digital human asset reference

Revision ID: a9d4e7f2c601
Revises: c8f2a6d1e409
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision = "a9d4e7f2c601"
down_revision = "c8f2a6d1e409"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("digital_humans", sa.Column("ppio_asset_avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("digital_humans", "ppio_asset_avatar_url")
