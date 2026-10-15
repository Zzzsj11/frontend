"""Expose the verified Ark Seedream image capabilities for Nano failover."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "7e4b9a2c1d60"
down_revision = "6d3a8f1c9b20"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    models = sa.Table("ai_models", sa.MetaData(), autoload_with=db)
    row = db.execute(sa.select(models).where(models.c.code == "seedream-5.0-pro-all-in-one", models.c.deleted_at.is_(None))).mappings().one_or_none()
    if row:
        caps = {
            **(row["capabilities"] or {}),
            "ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"],
            "resolutions": ["1K", "1.5K", "2K"],
            "imageToImage": True,
            "referenceImage": {"min": 0, "max": 10},
            "sceneOnly": False,
            "executionPool": "all-in-one:seedream-5.0-pro",
            "executionConcurrency": 5,
        }
        db.execute(models.update().where(models.c.id == row["id"]).values(name="Seedream 5.0 Pro", capabilities=caps, updated_at=datetime.now(timezone.utc)))


def downgrade():
    pass
