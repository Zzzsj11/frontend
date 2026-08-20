"""operational workload metrics

Revision ID: d91e3b6c70a4
Revises: a72c91e4b603
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d91e3b6c70a4"
down_revision: Union[str, None] = "a72c91e4b603"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name, column in (
        ("cpu_iowait_percent", sa.Float()),
        ("swap_total_bytes", sa.BigInteger()),
        ("swap_free_bytes", sa.BigInteger()),
        ("disk_read_bps", sa.Float()),
        ("disk_write_bps", sa.Float()),
        ("disk_read_iops", sa.Float()),
        ("disk_write_iops", sa.Float()),
    ):
        op.add_column("server_metric_samples", sa.Column(name, column, nullable=False, server_default="0"))
    op.add_column("server_metric_samples", sa.Column("filesystems", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("server_metric_samples", sa.Column("workloads", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    for name in ("workloads", "filesystems", "disk_write_iops", "disk_read_iops", "disk_write_bps", "disk_read_bps", "swap_free_bytes", "swap_total_bytes", "cpu_iowait_percent"):
        op.drop_column("server_metric_samples", name)
