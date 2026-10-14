"""Use ToAPIs Nano Banana 2.1 for new image generation.

Revision ID: d28f6b1a4c90
Revises: b4f1a9d2c803
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d28f6b1a4c90"
down_revision = "b4f1a9d2c803"
branch_labels = None
depends_on = None

MODEL = "gemini-nano-banana-2.1"
CAPABILITIES = {
    "ratios": ["16:9", "9:16", "4:3", "1:1"],
    "resolutions": ["1K", "2K", "4K"],
    "imageToImage": True,
    "referenceImage": {"min": 0, "max": 14},
    "providerCode": "toapis",
    "providerProtocol": "toapis-image",
    "sortOrder": 10,
}


def upgrade() -> None:
    db = op.get_bind()
    meta = sa.MetaData()
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    models = sa.Table("ai_models", meta, autoload_with=db)
    tasks = sa.Table("project_tasks", meta, autoload_with=db)
    lines = sa.Table("storyboard_lines", meta, autoload_with=db)
    now = datetime.now(timezone.utc)
    provider_id = db.execute(sa.select(providers.c.id).where(providers.c.code == "toapis")).scalar_one_or_none()
    if provider_id is None:
        provider_id = "provider-toapis"
        db.execute(
            providers.insert().values(id=provider_id, code="toapis", name="ToAPIs", base_url="https://toapis.cn", status="active", created_at=now, updated_at=now, deleted_at=None)
        )
    existing = db.execute(sa.select(models.c.id).where(models.c.code == MODEL)).scalar_one_or_none()
    values = dict(
        provider_id=provider_id,
        name="Nano Banana 2.1（ToAPIs）",
        modality="image",
        provider_model_id=MODEL,
        capabilities=CAPABILITIES,
        status="active",
        user_visible=True,
        is_default=True,
        sort_order=10,
        updated_at=now,
    )
    if existing:
        db.execute(models.update().where(models.c.id == existing).values(**values))
    else:
        db.execute(models.insert().values(id="model-nano-banana-21", code=MODEL, created_at=now, deleted_at=None, **values))
    db.execute(
        models.update()
        .where(models.c.modality == "image", models.c.code != MODEL, models.c.deleted_at.is_(None))
        .values(status="inactive", user_visible=False, is_default=False, updated_at=now)
    )

    for task_id, config in db.execute(sa.select(tasks.c.id, tasks.c.storyboard_config).where(tasks.c.deleted_at.is_(None))):
        if isinstance(config, dict) and config.get("image_model") and config["image_model"] != MODEL:
            changed = {**config, "image_model": MODEL, "image_resolution": config.get("image_resolution") or "1K"}
            db.execute(tasks.update().where(tasks.c.id == task_id).values(storyboard_config=changed, updated_at=now))
    for line_id, options in db.execute(sa.select(lines.c.id, lines.c.shot_options).where(lines.c.deleted_at.is_(None))):
        if isinstance(options, dict) and options.get("imageModel") and options["imageModel"] != MODEL:
            changed = {**options, "imageModel": MODEL, "imageResolution": options.get("imageResolution") or "1K"}
            db.execute(lines.update().where(lines.c.id == line_id).values(shot_options=changed, updated_at=now))


def downgrade() -> None:
    # Preserve generated assets and historical model attribution. Rollback is an
    # operational model-selection change, not a destructive data rewrite.
    pass
