"""worker drain instances and job leases

Revision ID: f13c7a9e2b40
Revises: e02a4c7d91b5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f13c7a9e2b40"
down_revision: Union[str, None] = "e02a4c7d91b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_instances",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("hostname", sa.String(length=160), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=160), nullable=False),
        sa.Column("kinds", sa.JSON(), nullable=False),
        sa.Column("providers", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_job_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draining_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("version", "status", "last_heartbeat_at", "deleted_at"):
        op.create_index(op.f(f"ix_worker_instances_{column}"), "worker_instances", [column])
    columns = (
        sa.Column("worker_id", sa.String(length=160), nullable=True),
        sa.Column("phase", sa.String(length=48), nullable=False, server_default="queued"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("generation_jobs", column)
    for column in ("worker_id", "phase", "heartbeat_at", "lease_expires_at"):
        op.create_index(op.f(f"ix_generation_jobs_{column}"), "generation_jobs", [column])


def downgrade() -> None:
    for column in ("lease_expires_at", "heartbeat_at", "phase", "worker_id"):
        op.drop_index(op.f(f"ix_generation_jobs_{column}"), table_name="generation_jobs")
    for column in ("provider_submitted_at", "lease_expires_at", "heartbeat_at", "claimed_at", "phase", "worker_id"):
        op.drop_column("generation_jobs", column)
    for column in ("deleted_at", "last_heartbeat_at", "status", "version"):
        op.drop_index(op.f(f"ix_worker_instances_{column}"), table_name="worker_instances")
    op.drop_table("worker_instances")
