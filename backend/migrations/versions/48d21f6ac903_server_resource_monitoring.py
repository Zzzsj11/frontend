"""server resource monitoring and traffic ledger

Revision ID: 48d21f6ac903
Revises: 1ab7d39e5c20
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "48d21f6ac903"
down_revision: Union[str, None] = "1ab7d39e5c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def lifecycle() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "server_metric_samples",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("boot_id", sa.String(80), nullable=False),
        sa.Column("interface", sa.String(80), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("load_1", sa.Float(), nullable=False),
        sa.Column("load_5", sa.Float(), nullable=False),
        sa.Column("load_15", sa.Float(), nullable=False),
        sa.Column("memory_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_available_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("disk_available_bytes", sa.BigInteger(), nullable=False),
        sa.Column("network_tx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("network_rx_bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("network_tx_bps", sa.Float(), nullable=False),
        sa.Column("network_rx_bps", sa.Float(), nullable=False),
        sa.Column("containers", sa.JSON(), nullable=False),
        *lifecycle(),
    )
    op.create_table(
        "server_traffic_months",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("egress_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_counter_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_boot_id", sa.String(80), nullable=False),
        *lifecycle(),
        sa.UniqueConstraint("source", "month", name="uq_server_traffic_source_month"),
    )
    op.create_table(
        "server_alert_events",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("alert_key", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("first_triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("details", sa.JSON(), nullable=False),
        *lifecycle(),
    )
    op.create_table(
        "server_maintenance_runs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("requested_by", sa.String(80)),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        *lifecycle(),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
    )
    for table, columns in {
        "server_metric_samples": ("source", "captured_at", "deleted_at"),
        "server_traffic_months": ("source", "month", "deleted_at"),
        "server_alert_events": ("source", "alert_key", "severity", "status", "deleted_at"),
        "server_maintenance_runs": ("requested_by", "source", "action", "trigger", "status", "deleted_at"),
    }.items():
        for column in columns:
            op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def downgrade() -> None:
    for table in ("server_maintenance_runs", "server_alert_events", "server_traffic_months", "server_metric_samples"):
        op.drop_table(table)
