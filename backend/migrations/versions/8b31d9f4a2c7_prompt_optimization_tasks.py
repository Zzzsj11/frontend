"""prompt optimization tasks

Revision ID: 8b31d9f4a2c7
Revises: 0137ad20eea6
"""

import sqlalchemy as sa
from alembic import op

revision = "8b31d9f4a2c7"
down_revision = "0137ad20eea6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_optimization_tasks",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("user_id", sa.String(80), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("input_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("output_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("ratio", sa.String(16), nullable=False, server_default="16:9"),
        sa.Column("input_media", sa.JSON(), nullable=False),
        sa.Column("provider_task_id", sa.String(160), nullable=True),
        sa.Column("request_id", sa.String(160), nullable=True),
        sa.Column("usage_data", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("generation_origin", sa.String(32), nullable=False, server_default="business"),
        sa.Column("agent_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("agent_run_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in (
        "user_id",
        "provider",
        "status",
        "provider_task_id",
        "request_id",
        "generation_origin",
        "agent_name",
        "agent_run_id",
        "deleted_at",
    ):
        op.create_index(f"ix_prompt_optimization_tasks_{column}", "prompt_optimization_tasks", [column])


def downgrade() -> None:
    op.drop_table("prompt_optimization_tasks")
