"""Channel currency, conversion policy and last successful balance snapshot."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "channel_accounts",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("key_env", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("usd_cny", sa.Numeric(24, 8), nullable=False),
        sa.Column("points_per_unit", sa.Numeric(24, 8)),
        sa.Column("points_currency", sa.String(10), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("queried_at", sa.DateTime(timezone=True)),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text()),
    )
    stamp = datetime.now(timezone.utc)
    defaults = [
        ("yinghe", "英和国内", "CNY"),
        ("yseeai", "英和海外", "USD"),
        ("runninghub", "RunningHub", "POINTS"),
        ("toapis", "ToAPIs", "USD"),
        ("optimizer-gemini", "Gemini 提示词渠道", "UNKNOWN"),
        ("optimizer-minimax", "MiniMax 提示词渠道", "UNKNOWN"),
    ]
    op.bulk_insert(
        table,
        [
            dict(
                id=code,
                channel=code,
                name=name,
                key_env=code.upper().replace("-", "_") + "_API_KEY",
                currency=currency,
                usd_cny=6.9,
                points_currency="CNY",
                snapshot={},
                created_at=stamp,
                updated_at=stamp,
                next_check_at=stamp,
            )
            for code, name, currency in defaults
        ],
    )


def downgrade():
    raise RuntimeError("Balance records are retained; use a forward migration")
