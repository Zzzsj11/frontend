"""api error logs

Revision ID: b7d02d13a9f4
Revises: a942e15c8d31
Create Date: 2026-08-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b7d02d13a9f4"
down_revision: Union[str, None] = "a942e15c8d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_error_logs",
        sa.Column("id", sa.String(80), nullable=False), sa.Column("user_id", sa.String(80), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=False), sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False), sa.Column("query_string", sa.Text(), server_default="", nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False), sa.Column("error_type", sa.String(160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("traceback", sa.Text(), server_default="", nullable=False), sa.Column("client_ip", sa.String(80), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("error_code"),
    )
    for column in ("user_id", "error_code", "status_code", "error_type", "deleted_at"):
        op.create_index(op.f(f"ix_api_error_logs_{column}"), "api_error_logs", [column])


def downgrade() -> None:
    op.drop_table("api_error_logs")
