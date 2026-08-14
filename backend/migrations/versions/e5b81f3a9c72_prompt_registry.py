"""prompt registry

提示词注册中心：prompt_templates + prompt_versions 两张表，
llm_call_logs 增加 prompt_key / prompt_version 用于调用留痕关联提示词版本。

Revision ID: e5b81f3a9c72
Revises: d4f2b8e6a1c0
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b81f3a9c72"
down_revision: Union[str, None] = "d4f2b8e6a1c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("engine", sa.String(32), server_default="llm", nullable=False),
        sa.Column("format", sa.String(16), server_default="text", nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("required_fragments", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prompt_templates_key"), "prompt_templates", ["key"], unique=True)
    for column in ("engine", "status", "deleted_at"):
        op.create_index(op.f(f"ix_prompt_templates_{column}"), "prompt_templates", [column])

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("template_id", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_note", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("created_by", sa.String(80), server_default="", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version", name="uq_prompt_versions_template_version"),
    )
    for column in ("template_id", "status", "deleted_at"):
        op.create_index(op.f(f"ix_prompt_versions_{column}"), "prompt_versions", [column])

    op.add_column("llm_call_logs", sa.Column("prompt_key", sa.String(120), server_default="", nullable=False))
    op.add_column("llm_call_logs", sa.Column("prompt_version", sa.Integer(), server_default="0", nullable=False))
    op.create_index(op.f("ix_llm_call_logs_prompt_key"), "llm_call_logs", ["prompt_key"])


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_call_logs_prompt_key"), table_name="llm_call_logs")
    op.drop_column("llm_call_logs", "prompt_version")
    op.drop_column("llm_call_logs", "prompt_key")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
