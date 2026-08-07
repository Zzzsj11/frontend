"""system humans and token ledger

Revision ID: e841bf50a62c
Revises: c712f803fb7a
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e841bf50a62c"
down_revision: Union[str, None] = "c712f803fb7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("digital_humans", sa.Column("asset_code", sa.String(length=32), nullable=True))
    op.add_column("digital_humans", sa.Column("gender", sa.String(length=32), nullable=True))
    op.add_column("digital_humans", sa.Column("age_description", sa.String(length=255), server_default="", nullable=False))
    op.add_column("digital_humans", sa.Column("appearance_style", sa.Text(), server_default="", nullable=False))
    op.add_column("digital_humans", sa.Column("clothing_description", sa.Text(), server_default="", nullable=False))
    op.add_column("digital_humans", sa.Column("suitable_music_styles", sa.Text(), server_default="", nullable=False))
    op.add_column("digital_humans", sa.Column("system_prompt", sa.Text(), server_default="", nullable=False))
    op.create_index(op.f("ix_digital_humans_asset_code"), "digital_humans", ["asset_code"], unique=False)
    op.create_index("uq_digital_human_asset_code_active", "digital_humans", ["asset_code"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"))
    op.create_table(
        "token_usage_records",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=True),
        sa.Column("project_id", sa.String(length=80), nullable=True),
        sa.Column("project_task_id", sa.String(length=80), nullable=True),
        sa.Column("storyboard_line_id", sa.String(length=80), nullable=True),
        sa.Column("generation_job_id", sa.String(length=80), nullable=True),
        sa.Column("chat_session_id", sa.String(length=80), nullable=True),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("request_id", sa.String(length=160), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("raw_usage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["project_task_id"], ["project_tasks.id"]),
        sa.ForeignKeyConstraint(["storyboard_line_id"], ["storyboard_lines.id"]),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.ForeignKeyConstraint(["chat_session_id"], ["chat_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "project_id", "project_task_id", "storyboard_line_id", "generation_job_id", "chat_session_id", "operation", "request_id", "deleted_at"):
        op.create_index(op.f(f"ix_token_usage_records_{column}"), "token_usage_records", [column], unique=False)


def downgrade() -> None:
    op.drop_table("token_usage_records")
    op.drop_index("uq_digital_human_asset_code_active", table_name="digital_humans")
    op.drop_index(op.f("ix_digital_humans_asset_code"), table_name="digital_humans")
    for column in ("system_prompt", "suitable_music_styles", "clothing_description", "appearance_style", "age_description", "gender", "asset_code"):
        op.drop_column("digital_humans", column)
