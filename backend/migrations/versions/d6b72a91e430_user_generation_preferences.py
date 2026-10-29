"""Persist user-wide model and channel preferences."""

import sqlalchemy as sa
from alembic import op

revision = "d6b72a91e430"
down_revision = "c39e6a8d2f40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("generation_preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade():
    op.drop_column("users", "generation_preferences")
