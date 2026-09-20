"""add Yinghe Mini, Fast and Wan 3.0 video pricing

Revision ID: a6c9e2f4b801
Revises: f2a6d9c4b701
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "a6c9e2f4b801"
down_revision = "f2a6d9c4b701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
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
    rows = [
        ("vpr-yh-sd20-mini-480p-v1", "doubao-seedance-2.0-mini", "480p", "completion_tokens", 1_000_000, 23, "英和 SD2.0 Mini；无视频输入输出 Token 基础价"),
        ("vpr-yh-sd20-mini-720p-v1", "doubao-seedance-2.0-mini", "720p", "completion_tokens", 1_000_000, 23, "英和 SD2.0 Mini；无视频输入输出 Token 基础价"),
        ("vpr-yh-sd20-fast-480p-v1", "doubao-seedance-2.0-fast", "480p", "completion_tokens", 1_000_000, 37, "英和 SD2.0 Fast；无视频输入输出 Token 基础价"),
        ("vpr-yh-sd20-fast-720p-v1", "doubao-seedance-2.0-fast", "720p", "completion_tokens", 1_000_000, 37, "英和 SD2.0 Fast；无视频输入输出 Token 基础价"),
        ("vpr-yh-wan30-480p-v1", "wan3.0-video", "480p", "output_seconds", 1, 0.30, "英和 Wan3.0；官方华北2原价，待供应商账单复核"),
        ("vpr-yh-wan30-720p-v1", "wan3.0-video", "720p", "output_seconds", 1, 0.60, "英和 Wan3.0；官方华北2原价，待供应商账单复核"),
        ("vpr-yh-wan30-1080p-v1", "wan3.0-video", "1080p", "output_seconds", 1, 1.20, "英和 Wan3.0；官方华北2原价，待供应商账单复核"),
        ("vpr-yh-wan30-prime-480p-v1", "wan3.0-video-prime", "480p", "output_seconds", 1, 0.45, "英和 Wan3.0 Prime；官方华北2原价，待供应商账单复核"),
        ("vpr-yh-wan30-prime-720p-v1", "wan3.0-video-prime", "720p", "output_seconds", 1, 0.90, "英和 Wan3.0 Prime；官方华北2原价，待供应商账单复核"),
        ("vpr-yh-wan30-prime-1080p-v1", "wan3.0-video-prime", "1080p", "output_seconds", 1, 1.80, "英和 Wan3.0 Prime；官方华北2原价，待供应商账单复核"),
    ]
    op.bulk_insert(
        table,
        [
            {
                "id": item[0],
                "model": item[1],
                "provider": "yinghe",
                "resolution": item[2],
                "usage_type": item[3],
                "unit_size": item[4],
                "unit_price": item[5],
                "currency": "CNY",
                "effective_at": epoch,
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
    ids = (
        "vpr-yh-sd20-mini-480p-v1",
        "vpr-yh-sd20-mini-720p-v1",
        "vpr-yh-sd20-fast-480p-v1",
        "vpr-yh-sd20-fast-720p-v1",
        "vpr-yh-wan30-480p-v1",
        "vpr-yh-wan30-720p-v1",
        "vpr-yh-wan30-1080p-v1",
        "vpr-yh-wan30-prime-480p-v1",
        "vpr-yh-wan30-prime-720p-v1",
        "vpr-yh-wan30-prime-1080p-v1",
    )
    table = sa.table("video_pricing_rules", sa.column("id"))
    op.get_bind().execute(sa.delete(table).where(table.c.id.in_(ids)))
