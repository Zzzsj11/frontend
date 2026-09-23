"""Retire unused suppliers while preserving schema compatibility during rolling deployment."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "b3f7a1c5e902"
down_revision = "a6c9e2f4b801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    stamp = datetime.now(timezone.utc)
    providers = sa.table("ai_providers", sa.column("id"), sa.column("code"), sa.column("status"), sa.column("updated_at"), sa.column("deleted_at"))
    models = sa.table(
        "ai_models",
        sa.column("id"),
        sa.column("provider_id"),
        sa.column("code"),
        sa.column("status"),
        sa.column("user_visible"),
        sa.column("is_default"),
        sa.column("updated_at"),
        sa.column("deleted_at"),
    )
    retired_providers = sa.select(providers.c.id).where(providers.c.code.in_(("ppio", "bfl")))
    retired_models = sa.select(models.c.id).where(
        sa.or_(models.c.provider_id.in_(retired_providers), models.c.code.in_(("doubao-seedance-2.0-ppio", "minimax-h3-ppio", "flux-3-video")))
    )
    prices = sa.table("model_price_versions", sa.column("model_id"), sa.column("updated_at"), sa.column("deleted_at"))
    op.execute(prices.update().where(prices.c.model_id.in_(retired_models), prices.c.deleted_at.is_(None)).values(updated_at=stamp, deleted_at=stamp))
    op.execute(
        models.update()
        .where(models.c.id.in_(retired_models), models.c.deleted_at.is_(None))
        .values(status="disabled", user_visible=False, is_default=False, updated_at=stamp, deleted_at=stamp)
    )
    op.execute(providers.update().where(providers.c.id.in_(retired_providers), providers.c.deleted_at.is_(None)).values(status="disabled", updated_at=stamp, deleted_at=stamp))
    pricing = sa.table("video_pricing_rules", sa.column("provider"), sa.column("model"), sa.column("status"), sa.column("updated_at"), sa.column("deleted_at"))
    op.execute(
        pricing.update()
        .where(
            sa.or_(pricing.c.provider.in_(("ppio", "bfl")), pricing.c.model.in_(("doubao-seedance-2.0-ppio", "minimax-h3-ppio", "flux-3-video"))),
            pricing.c.deleted_at.is_(None),
        )
        .values(status="disabled", updated_at=stamp, deleted_at=stamp)
    )
    # Old API/Worker processes still select this column during the rolling switch.


def downgrade() -> None:
    raise RuntimeError("Retired supplier configuration cannot be restored; use a forward migration")
