"""Durable query-only video reconciliation schedule."""

import sqlalchemy as sa
from alembic import op

revision = "a103e9c7d251"
down_revision = "d6b72a91e430"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_jobs", sa.Column("reconciliation_next_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generation_jobs", sa.Column("reconciliation_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_generation_jobs_reconciliation_next_at", "generation_jobs", ["reconciliation_next_at"])


def downgrade():
    op.drop_index("ix_generation_jobs_reconciliation_next_at", "generation_jobs")
    op.drop_column("generation_jobs", "reconciliation_attempts")
    op.drop_column("generation_jobs", "reconciliation_next_at")
