"""Support ordered bounded worker scans and per-queue active project counts."""

from alembic import op

revision = "d83108ae269f"
down_revision = "eb617531ca10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_job_queue_fifo", "generation_jobs", ["kind", "status", "created_at", "id"])
    op.create_index("ix_job_queue_project", "generation_jobs", ["kind", "status", "project_task_id"])


def downgrade():
    op.drop_index("ix_job_queue_project", table_name="generation_jobs")
    op.drop_index("ix_job_queue_fifo", table_name="generation_jobs")
