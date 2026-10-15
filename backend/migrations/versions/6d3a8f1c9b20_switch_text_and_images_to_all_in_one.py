"""Use all in one text fallback and image models for new MV work.

Revision ID: 6d3a8f1c9b20
Revises: d28f6b1a4c90
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "6d3a8f1c9b20"
down_revision = "d28f6b1a4c90"
branch_labels = None
depends_on = None

NANO = "nano-banana-2.1-all-in-one"
SEEDREAM = "seedream-5.0-pro-all-in-one"
TEXT_BACKUP = "doubao-seed-2-1-pro-260915-all-in-one"
BILLING = {"provider": "all-in-one", "balanceCheck": False, "billingMode": "platform_points", "currency": "points"}


def upgrade() -> None:
    db = op.get_bind()
    meta = sa.MetaData()
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    models = sa.Table("ai_models", meta, autoload_with=db)
    tasks = sa.Table("project_tasks", meta, autoload_with=db)
    lines = sa.Table("storyboard_lines", meta, autoload_with=db)
    now = datetime.now(timezone.utc)
    provider_id = db.execute(sa.select(providers.c.id).where(providers.c.code == "all-in-one", providers.c.deleted_at.is_(None))).scalar_one()
    specs = (
        (
            NANO,
            "nano-banana-2.1",
            "Nano Banana 2.1（all in one）",
            "image",
            {
                "ratios": ["16:9", "9:16", "4:3", "1:1", "3:2", "2:3", "3:4"],
                "resolutions": ["1K", "2K", "4K"],
                "imageToImage": True,
                "referenceImage": {"min": 0, "max": 14},
                "providerCode": "all-in-one",
                "providerProtocol": "all-in-one",
                "executionPool": "all-in-one:nano-banana-2.1",
                "executionConcurrency": 32,
                "billing": BILLING,
                "sortOrder": 10,
            },
            True,
            10,
        ),
        (
            SEEDREAM,
            "seedream-5.0-pro",
            "Seedream 5.0 Pro（仅 1:1 · 2K 空镜）",
            "image",
            {
                "ratios": ["1:1"],
                "resolutions": ["2K"],
                "imageToImage": False,
                "referenceImage": {"min": 0, "max": 0},
                "sceneOnly": True,
                "providerCode": "all-in-one",
                "providerProtocol": "all-in-one",
                "executionPool": "all-in-one:seedream-5.0-pro",
                "executionConcurrency": 32,
                "billing": BILLING,
                "sortOrder": 11,
            },
            False,
            11,
        ),
        (
            TEXT_BACKUP,
            "doubao-seed-2-1-pro-260915",
            "Doubao Seed 2.1 Pro（all in one）",
            "chat",
            {"structuredOutput": True, "providerCode": "all-in-one"},
            False,
            101,
        ),
    )
    for code, provider_model_id, name, modality, capabilities, is_default, sort_order in specs:
        existing = db.execute(sa.select(models.c.id).where(models.c.code == code)).scalar_one_or_none()
        values = dict(
            provider_id=provider_id,
            provider_model_id=provider_model_id,
            name=name,
            modality=modality,
            capabilities=capabilities,
            status="active",
            user_visible=True,
            is_default=is_default,
            sort_order=sort_order,
            deleted_at=None,
            updated_at=now,
        )
        if existing:
            db.execute(models.update().where(models.c.id == existing).values(**values))
        else:
            db.execute(models.insert().values(id="model-" + code, code=code, created_at=now, **values))
    db.execute(
        models.update()
        .where(models.c.modality == "image", models.c.code.notin_((NANO, SEEDREAM)), models.c.deleted_at.is_(None))
        .values(status="inactive", user_visible=False, is_default=False, updated_at=now)
    )
    db.execute(
        models.update()
        .where(models.c.code == "gpt-6-sol-all-in-one", models.c.deleted_at.is_(None))
        .values(status="inactive", user_visible=False, is_default=False, updated_at=now)
    )
    for task_id, config in db.execute(sa.select(tasks.c.id, tasks.c.storyboard_config).where(tasks.c.deleted_at.is_(None))):
        if isinstance(config, dict) and config.get("image_model") not in (None, NANO, SEEDREAM):
            db.execute(tasks.update().where(tasks.c.id == task_id).values(storyboard_config={**config, "image_model": NANO}, updated_at=now))
    for line_id, options in db.execute(sa.select(lines.c.id, lines.c.shot_options).where(lines.c.deleted_at.is_(None))):
        if isinstance(options, dict) and options.get("imageModel") not in (None, NANO, SEEDREAM):
            db.execute(lines.update().where(lines.c.id == line_id).values(shot_options={**options, "imageModel": NANO}, updated_at=now))


def downgrade() -> None:
    # Preserve generated media and historical task attribution.
    pass
