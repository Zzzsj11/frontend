"""Register the explicitly scoped ALL IN ONE catalogue; no credentials or invented rates."""

from copy import deepcopy
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

TEXT_MODELS = (("gpt-6.1-sol", "GPT 6.1 Sol"), ("gpt-6-astra", "GPT 6 Astra"), ("gpt-6-sol", "GPT 6.0 Sol"))
MEDIA_MODELS = (
    ("gpt-image-2", "gpt-image-2", "Img2", "image"),
    ("gpt-image-2.5-sunburst", "gpt-image-2.5-sunburst", "精细", "image"),
    ("gpt-image-2.5-flare", "gpt-image-2.5-flare", "快速", "image"),
    ("doubao-seedance-2.0", "seedance-2.0", "SD2.0", "video"),
    ("wan3.0-video", "wan3.0-video", "Wan3.0", "video"),
    ("minimax-h3", "MiniMax-H3", "H3", "video"),
)


def rows(source_capabilities: dict[str, dict]) -> list[dict]:
    result = []
    for order, (code, name) in enumerate(TEXT_MODELS):
        result.append(
            {
                "code": code + "-all-in-one",
                "provider_model_id": code,
                "name": name + "（all in one）",
                "modality": "chat",
                "capabilities": {"structuredOutput": True, "providerCode": "all-in-one"},
                "sort_order": 100 + order,
            }
        )
    for order, (code, upstream, name, modality) in enumerate(MEDIA_MODELS):
        ratios = ["16:9", "9:16", "4:3", "1:1"]
        caps = (
            {"ratios": ratios, "imageToImage": True, "referenceImage": {"min": 0, "max": 15}}
            if modality == "image"
            else {"ratios": ratios, "durations": {"min": 4, "max": 15}, "resolutions": ["480p", "720p", "1080p"]}
        )
        caps.update(deepcopy(source_capabilities.get(code, {})))
        if code == "doubao-seedance-2.0":
            caps.update(resolutions=["480p", "720p"], referenceImage={"min": 0, "max": 9}, referenceVideo={"min": 0, "max": 3}, referenceAudio={"min": 0, "max": 3})
        elif code == "minimax-h3":
            caps.update(
                resolutions=["720p", "1080p"],
                providerResolutionMap={"720p": "768P", "1080p": "2K"},
                h3Modes=["auto", "text", "first_frame", "first_last", "reference"],
                referenceImage={"min": 0, "max": 6},
                referenceVideo={"min": 0, "max": 1},
                referenceAudio={"min": 0, "max": 3},
                referenceTotalMax=10,
                referenceAudioRequiresVisual=True,
            )
        elif code == "wan3.0-video":
            caps.update(referenceImage={"min": 0, "max": 10}, referenceVideo={"min": 0, "max": 5}, referenceAudio={"min": 0, "max": 5})
        caps.update(providerCode="all-in-one", providerProtocol="all-in-one", executionPool=f"all-in-one:{code}", executionConcurrency=2)
        # Yinghe asset:// belongs to its own account; this channel receives original TOS URLs.
        caps.pop("billing", None)
        if code != "minimax-h3":
            caps.pop("providerResolutionMap", None)
        caps.pop("systemManaged", None)
        caps["sortOrder"] = 100 + order
        result.append(
            {"code": code + "-all-in-one", "provider_model_id": upstream, "name": name + "（all in one）", "modality": modality, "capabilities": caps, "sort_order": 100 + order}
        )
    return result


revision = "c9d52e8b310a"
down_revision = "b7d31e9a420f"
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    meta = sa.MetaData()
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    models = sa.Table("ai_models", meta, autoload_with=db)
    now = datetime.now(timezone.utc)
    provider_id = "provider-all-in-one"
    if not db.execute(sa.select(providers.c.id).where(providers.c.code == "all-in-one")).scalar():
        db.execute(
            providers.insert().values(
                id=provider_id, code="all-in-one", name="all in one", base_url="https://mg.epaipix.com", status="active", created_at=now, updated_at=now, deleted_at=None
            )
        )
    else:
        provider_id = db.execute(sa.select(providers.c.id).where(providers.c.code == "all-in-one")).scalar_one()
    source = {r.code: r.capabilities for r in db.execute(sa.select(models.c.code, models.c.capabilities))}
    for row in rows(source):
        if not db.execute(sa.select(models.c.id).where(models.c.code == row["code"])).scalar():
            db.execute(
                models.insert().values(
                    id="model-" + row["code"], provider_id=provider_id, **row, status="active", user_visible=True, is_default=False, created_at=now, updated_at=now, deleted_at=None
                )
            )


def downgrade():
    now = datetime.now(timezone.utc)
    meta = sa.MetaData()
    db = op.get_bind()
    models = sa.Table("ai_models", meta, autoload_with=db)
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    db.execute(models.update().where(models.c.provider_id == "provider-all-in-one").values(status="disabled", user_visible=False, deleted_at=now, updated_at=now))
    db.execute(providers.update().where(providers.c.code == "all-in-one").values(status="disabled", deleted_at=now, updated_at=now))
