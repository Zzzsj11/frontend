"""generation agent attribution

Revision ID: d3f5a7c9e102
Revises: b7e2f4a1c903
"""

import sqlalchemy as sa
from alembic import op

revision = "d3f5a7c9e102"
down_revision = "b7e2f4a1c903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("generation_origin", sa.String(32), nullable=False, server_default="business"))
    op.add_column("generation_jobs", sa.Column("agent_name", sa.String(80), nullable=False, server_default=""))
    op.add_column("generation_jobs", sa.Column("agent_run_id", sa.String(160), nullable=False, server_default=""))
    op.create_index("ix_generation_jobs_generation_origin", "generation_jobs", ["generation_origin"])
    op.create_index("ix_generation_jobs_agent_name", "generation_jobs", ["agent_name"])
    op.create_index("ix_generation_jobs_agent_run_id", "generation_jobs", ["agent_run_id"])


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_agent_run_id", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_agent_name", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_generation_origin", table_name="generation_jobs")
    op.drop_column("generation_jobs", "agent_run_id")
    op.drop_column("generation_jobs", "agent_name")
    op.drop_column("generation_jobs", "generation_origin")
