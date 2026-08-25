"""video billing reconciliation

Revision ID: b7e2f4a1c903
Revises: c6a9e1f4b207
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "b7e2f4a1c903"
down_revision = "c6a9e1f4b207"
branch_labels = None
depends_on = None


def _lifecycle() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "video_pricing_rules",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=False),
        sa.Column("usage_type", sa.String(48), nullable=False),
        sa.Column("unit_size", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        *_lifecycle(),
    )
    for column in ("model", "provider", "resolution", "effective_at", "status", "deleted_at"):
        op.create_index(f"ix_video_pricing_rules_{column}", "video_pricing_rules", [column])

    op.create_table(
        "video_billing_records",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("generation_job_id", sa.String(80), sa.ForeignKey("generation_jobs.id"), nullable=False),
        sa.Column("user_id", sa.String(80), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("project_id", sa.String(80), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("project_task_id", sa.String(80), sa.ForeignKey("project_tasks.id"), nullable=True),
        sa.Column("storyboard_line_id", sa.String(80), sa.ForeignKey("storyboard_lines.id"), nullable=True),
        sa.Column("pricing_rule_id", sa.String(80), sa.ForeignKey("video_pricing_rules.id"), nullable=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=False),
        sa.Column("generation_status", sa.String(32), nullable=False),
        sa.Column("is_failed", sa.Boolean(), nullable=False),
        sa.Column("billing_status", sa.String(32), nullable=False),
        sa.Column("usage_type", sa.String(48), nullable=False),
        sa.Column("usage_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("usage_unit", sa.String(48), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("raw_usage", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_lifecycle(),
        sa.UniqueConstraint("generation_job_id", name="uq_video_billing_generation_job"),
    )
    for column in (
        "generation_job_id",
        "user_id",
        "project_id",
        "project_task_id",
        "storyboard_line_id",
        "pricing_rule_id",
        "provider",
        "model",
        "resolution",
        "generation_status",
        "is_failed",
        "billing_status",
        "completed_at",
        "deleted_at",
    ):
        op.create_index(f"ix_video_billing_records_{column}", "video_billing_records", [column])

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    rules = [
        ("vpr-sd20-480p-cny-v1", "doubao-seedance-2.0", "", "480p", "completion_tokens", 1_000_000, 46, "SD2.0 480p 输出Token"),
        ("vpr-sd20-720p-cny-v1", "doubao-seedance-2.0", "", "720p", "completion_tokens", 1_000_000, 46, "SD2.0 720p 输出Token"),
        ("vpr-sd20-1080p-cny-v1", "doubao-seedance-2.0", "", "1080p", "completion_tokens", 1_000_000, 51, "SD2.0 1080p 输出Token"),
        ("vpr-h3-direct-720p-cny-v1", "minimax-h3", "yinghe-h3", "720p", "output_seconds", 1, 0.425, "直连H3 720p 输出视频秒数"),
    ]
    table = sa.table(
        "video_pricing_rules",
        *[
            sa.column(name)
            for name in (
                "id",
                "model",
                "provider",
                "resolution",
                "usage_type",
                "unit_size",
                "unit_price",
                "currency",
                "effective_at",
                "expires_at",
                "status",
                "notes",
                "created_at",
                "updated_at",
                "deleted_at",
            )
        ],
    )
    op.bulk_insert(
        table,
        [
            dict(
                zip(("id", "model", "provider", "resolution", "usage_type", "unit_size", "unit_price", "notes"), row),
                currency="CNY",
                effective_at=epoch,
                expires_at=None,
                status="active",
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            for row in rules
        ],
    )


def downgrade() -> None:
    op.drop_table("video_billing_records")
    op.drop_table("video_pricing_rules")
