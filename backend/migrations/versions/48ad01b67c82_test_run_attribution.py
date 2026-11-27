"""Preserve the original test run identifier across dispatch and accounting."""

import sqlalchemy as sa
from alembic import op

revision = "48ad01b67c82"
down_revision = "0dc71af19e32"
branch_labels = None
depends_on = None

TABLES = ("generation_jobs", "token_usage_records", "llm_call_logs", "prompt_optimization_tasks")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("test_run_id", sa.String(160), nullable=False, server_default=""))


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, "test_run_id")
