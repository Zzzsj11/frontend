"""llm call logs

Revision ID: 9c1e5a7b2d34
Revises: 7a31c9de204f
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c1e5a7b2d34"
down_revision: Union[str, None] = "7a31c9de204f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("user_id", sa.String(80), nullable=True),
        sa.Column("project_id", sa.String(80), nullable=True),
        sa.Column("project_task_id", sa.String(80), nullable=True),
        sa.Column("storyboard_line_id", sa.String(80), nullable=True),
        sa.Column("generation_job_id", sa.String(80), nullable=True),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(80), server_default="", nullable=False),
        sa.Column("model", sa.String(160), server_default="", nullable=False),
        sa.Column("request_id", sa.String(160), nullable=True),
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_messages", sa.JSON(), nullable=False),
        sa.Column("response_text", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["project_task_id"], ["project_tasks.id"]),
        sa.ForeignKeyConstraint(["storyboard_line_id"], ["storyboard_lines.id"]),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "project_id", "project_task_id", "storyboard_line_id", "operation", "request_id", "status", "deleted_at"):
        op.create_index(op.f(f"ix_llm_call_logs_{column}"), "llm_call_logs", [column])


def downgrade() -> None:
    op.drop_table("llm_call_logs")
