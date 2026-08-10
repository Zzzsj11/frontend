"""daily per-user generation quotas

Revision ID: 2d57abce7091
Revises: ab91d76f502e
"""

import sqlalchemy as sa
from alembic import op

revision = "2d57abce7091"
down_revision = "ab91d76f502e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_usage_quotas",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "usage_date", "category", name="uq_daily_usage_quota_user_date_category"),
    )
    op.create_index(op.f("ix_daily_usage_quotas_user_id"), "daily_usage_quotas", ["user_id"])
    op.create_index(op.f("ix_daily_usage_quotas_usage_date"), "daily_usage_quotas", ["usage_date"])
    op.create_index(op.f("ix_daily_usage_quotas_category"), "daily_usage_quotas", ["category"])
    op.create_index(op.f("ix_daily_usage_quotas_deleted_at"), "daily_usage_quotas", ["deleted_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_usage_quotas_deleted_at"), table_name="daily_usage_quotas")
    op.drop_index(op.f("ix_daily_usage_quotas_category"), table_name="daily_usage_quotas")
    op.drop_index(op.f("ix_daily_usage_quotas_usage_date"), table_name="daily_usage_quotas")
    op.drop_index(op.f("ix_daily_usage_quotas_user_id"), table_name="daily_usage_quotas")
    op.drop_table("daily_usage_quotas")
