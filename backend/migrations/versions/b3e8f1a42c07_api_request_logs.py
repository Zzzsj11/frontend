"""api request logs

Revision ID: b3e8f1a42c07
Revises: 9c1e5a7b2d34
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8f1a42c07"
down_revision: Union[str, None] = "9c1e5a7b2d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_request_logs",
        sa.Column("id", sa.String(80), nullable=False),
        sa.Column("run_id", sa.String(120), server_default="", nullable=False),
        sa.Column("user_id", sa.String(80), nullable=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("query_string", sa.Text(), server_default="", nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("client_ip", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("run_id", "user_id", "status_code", "deleted_at"):
        op.create_index(op.f(f"ix_api_request_logs_{column}"), "api_request_logs", [column])


def downgrade() -> None:
    op.drop_table("api_request_logs")
