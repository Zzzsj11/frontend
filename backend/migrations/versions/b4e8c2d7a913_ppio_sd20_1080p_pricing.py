"""add PPIO SD2.0 1080p pricing

Revision ID: b4e8c2d7a913
Revises: a9d4e7f2c601
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "b4e8c2d7a913"
down_revision = "a9d4e7f2c601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    table = sa.table(
        "video_pricing_rules",
        sa.column("id"),
        sa.column("model"),
        sa.column("provider"),
        sa.column("resolution"),
        sa.column("usage_type"),
        sa.column("unit_size"),
        sa.column("unit_price"),
        sa.column("currency"),
        sa.column("effective_at"),
        sa.column("expires_at"),
        sa.column("status"),
        sa.column("notes"),
        sa.column("created_at"),
        sa.column("updated_at"),
        sa.column("deleted_at"),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": "vpr-ppio-sd20-1080p-v1",
                "model": "doubao-seedance-2.0-ppio",
                "provider": "ppio",
                "resolution": "1080p",
                "usage_type": "completion_tokens",
                "unit_size": 1_000_000,
                "unit_price": 51,
                "currency": "CNY",
                "effective_at": datetime(1970, 1, 1, tzinfo=timezone.utc),
                "expires_at": None,
                "status": "active",
                "notes": "PPIO SD2.0 1080P；基础价按输出 Token，结算应用 8 折",
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM video_pricing_rules WHERE id = 'vpr-ppio-sd20-1080p-v1'"))
