"""Remove a stale refresh-token auth_version column from older local schemas.

Revision ID: b4f1a9d2c803
Revises: c9d52e8b310a
"""

import sqlalchemy as sa
from alembic import op

revision = "b4f1a9d2c803"
down_revision = "c9d52e8b310a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("refresh_tokens")}
    if "auth_version" in columns:
        op.drop_column("refresh_tokens", "auth_version")


def downgrade() -> None:
    # The column was never part of the maintained schema. Recreating it would
    # introduce the same login failure on databases that never had it.
    pass
