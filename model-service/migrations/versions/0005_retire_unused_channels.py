"""Retire unused supplier configuration without deleting usage or billing history."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    stamp = datetime.now(timezone.utc)
    channels = ("ppio", "bfl")
    accounts = sa.table("channel_accounts", sa.column("channel"), sa.column("updated_at"), sa.column("deleted_at"))
    op.execute(
        accounts.update()
        .where(accounts.c.channel.in_(channels), accounts.c.deleted_at.is_(None))
        .values(updated_at=stamp, deleted_at=stamp)
    )
    models = sa.table("models", sa.column("id"), sa.column("channel"))
    prices = sa.table("pricing_rules", sa.column("model_id"), sa.column("updated_at"), sa.column("deleted_at"))
    retired_models = sa.select(models.c.id).where(models.c.channel.in_(channels))
    op.execute(
        prices.update()
        .where(prices.c.model_id.in_(retired_models), prices.c.deleted_at.is_(None))
        .values(updated_at=stamp, deleted_at=stamp)
    )
    for name in ("models", "model_routes"):
        table = sa.table(name, sa.column("channel"), sa.column("enabled"), sa.column("updated_at"), sa.column("deleted_at"))
        op.execute(
            table.update()
            .where(table.c.channel.in_(channels), table.c.deleted_at.is_(None))
            .values(enabled=False, updated_at=stamp, deleted_at=stamp)
        )


def downgrade():
    raise RuntimeError("Retired supplier configuration cannot be restored; use a forward migration")
