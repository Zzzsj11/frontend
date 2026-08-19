"""add user auth version for session revocation

Revision ID: e1a4b6c8d0f2
Revises: c9e4a7b1d203
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a4b6c8d0f2"
down_revision: str | None = "c9e4a7b1d203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "auth_version")
