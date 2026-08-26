"""add PPIO video pricing rules

Revision ID: c8f2a6d1e409
Revises: a4c8e2f6b109
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "c8f2a6d1e409"
down_revision = "a4c8e2f6b109"
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
    rows = [
        ("vpr-ppio-sd20-480p-v1", "doubao-seedance-2.0-ppio", "480p", "completion_tokens", 1_000_000, 46, "PPIO SD2.0 标准版；基础价按输出 Token，结算应用 8 折"),
        ("vpr-ppio-sd20-720p-v1", "doubao-seedance-2.0-ppio", "720p", "completion_tokens", 1_000_000, 46, "PPIO SD2.0 标准版；基础价按输出 Token，结算应用 8 折"),
        ("vpr-ppio-h3-720p-v1", "minimax-h3-ppio", "720p", "output_seconds", 1, 0.5, "PPIO H3 768P；基础价按输出秒数，结算应用 85 折"),
        ("vpr-ppio-h3-1080p-v1", "minimax-h3-ppio", "1080p", "output_seconds", 1, 0.5, "PPIO H3 2K；基础价按输出秒数，结算应用 85 折"),
    ]
    op.bulk_insert(
        table,
        [
            {
                "id": item[0],
                "model": item[1],
                "provider": "ppio",
                "resolution": item[2],
                "usage_type": item[3],
                "unit_size": item[4],
                "unit_price": item[5],
                "currency": "CNY",
                "effective_at": datetime(1970, 1, 1, tzinfo=timezone.utc),
                "expires_at": None,
                "status": "active",
                "notes": item[6],
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
            for item in rows
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM video_pricing_rules WHERE id LIKE 'vpr-ppio-%'"))
