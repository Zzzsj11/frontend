"""Apply confirmed Yinghe video route limits without enabling retired models."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = depends_on = None

LIMITS = {"dreamina-seedance-2.5": 50}


def upgrade():
    metadata = sa.MetaData()
    db = op.get_bind()
    routes = sa.Table("model_routes", metadata, autoload_with=db)
    models = sa.Table("models", metadata, autoload_with=db)
    audits = sa.Table("audits", metadata, autoload_with=db)
    stamp = datetime.now(timezone.utc)
    query = (
        sa.select(routes)
        .join(models, models.c.id == routes.c.model_id)
        .where(
            routes.c.model_id.in_(LIMITS),
            routes.c.supplier.in_(("yinghe", "yseeai")),
            routes.c.channel.in_(("yinghe", "yseeai")),
            routes.c.deleted_at.is_(None),
            models.c.deleted_at.is_(None),
            models.c.kind == "video",
        )
    )
    for row in db.execute(query).mappings().all():
        limit = LIMITS[row["model_id"]]
        db.execute(routes.update().where(routes.c.id == row["id"]).values(concurrency=limit, updated_at=stamp))
        db.execute(
            audits.insert().values(
                id="concurrency-0011-" + row["id"],
                actor="migration:0011",
                action="route.concurrency",
                target=row["id"],
                detail={"before": row["concurrency"], "after": limit, "source": "用户提供 Seedance 2.5 并发范围 50–150，取下限 50"},
                created_at=stamp,
                updated_at=stamp,
                deleted_at=None,
            )
        )


def downgrade():
    raise RuntimeError("Preserve manual concurrency edits; use a forward migration")
