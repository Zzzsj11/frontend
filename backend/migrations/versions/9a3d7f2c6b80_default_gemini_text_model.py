"""Register Gemini 3.8 Flash as the default All in one text model."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "9a3d7f2c6b80"
down_revision = "8f2c6d4a1b70"
branch_labels = depends_on = None
CODE = "gemini-3.8-flash-all-in-one"


def upgrade():
    db = op.get_bind()
    meta = sa.MetaData()
    models = sa.Table("ai_models", meta, autoload_with=db)
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    now = datetime.now(timezone.utc)
    provider_id = db.execute(sa.select(providers.c.id).where(providers.c.code == "all-in-one", providers.c.deleted_at.is_(None))).scalar_one()
    db.execute(models.update().where(models.c.modality == "chat", models.c.is_default.is_(True)).values(is_default=False, updated_at=now))
    values = dict(
        provider_id=provider_id,
        provider_model_id="gemini-3.8-flash",
        name="Gemini 3.8 Flash",
        modality="chat",
        capabilities={"structuredOutput": True, "providerCode": "all-in-one"},
        status="active",
        user_visible=True,
        is_default=True,
        sort_order=0,
        updated_at=now,
        deleted_at=None,
    )
    existing = db.execute(sa.select(models.c.id).where(models.c.code == CODE)).scalar_one_or_none()
    if existing:
        db.execute(models.update().where(models.c.id == existing).values(**values))
    else:
        db.execute(models.insert().values(id="model-" + CODE, code=CODE, created_at=now, **values))

    # Keep historic model/provider IDs for billing and audit joins; prevent new use.
    retired = sa.select(providers.c.id).where(providers.c.code != "all-in-one")
    db.execute(
        models.update()
        .where(models.c.provider_id.in_(retired), models.c.deleted_at.is_(None))
        .values(status="inactive", user_visible=False, is_default=False, deleted_at=now, updated_at=now)
    )
    db.execute(providers.update().where(providers.c.code != "all-in-one", providers.c.deleted_at.is_(None)).values(status="inactive", deleted_at=now, updated_at=now))


def downgrade():
    raise RuntimeError("Retired external suppliers must not be restored; use a forward migration")
