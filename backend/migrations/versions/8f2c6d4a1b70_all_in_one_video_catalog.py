"""Move all new video work to the verified all in one model catalog."""

import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "8f2c6d4a1b70"
down_revision = "7e4b9a2c1d60"
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    meta = sa.MetaData()
    models = sa.Table("ai_models", meta, autoload_with=db)
    providers = sa.Table("ai_providers", meta, autoload_with=db)
    tasks = sa.Table("project_tasks", meta, autoload_with=db)
    lines = sa.Table("storyboard_lines", meta, autoload_with=db)
    now = datetime.now(timezone.utc)
    rows = json.loads((Path(__file__).resolve().parents[2] / "app/data/all_in_one_video_models_20261015.json").read_text())
    by_code = {row["code"]: row for row in rows}
    primary = "doubao-seedance-2.0-all-in-one"
    provider_id = db.execute(sa.select(providers.c.id).where(providers.c.code == "all-in-one", providers.c.deleted_at.is_(None))).scalar_one()
    for row in rows:
        existing = db.execute(sa.select(models.c.id).where(models.c.code == row["code"])).scalar_one_or_none()
        values = {key: row[key] for key in ("name", "provider_model_id", "modality", "capabilities", "sort_order")}
        values.update(provider_id=provider_id, status="active", user_visible=True, is_default=row["code"] == primary, deleted_at=None, updated_at=now)
        if existing:
            db.execute(models.update().where(models.c.id == existing).values(**values))
        else:
            db.execute(models.insert().values(id="model-" + row["code"], code=row["code"], created_at=now, **values))
    db.execute(
        models.update()
        .where(models.c.modality == "video", models.c.code.notin_(by_code), models.c.deleted_at.is_(None))
        .values(status="inactive", user_visible=False, is_default=False, deleted_at=now, updated_at=now)
    )

    aliases = {
        "veo-3.1-generate-preview": "veo-3.1",
        "veo-3.1-fast-generate-preview": "veo-3.1-fast",
        "gemini-omni-flash-preview": "gemini-omni-1.1-flash-preview",
        "minimax-h3-runninghub": "minimax-h3",
    }

    def adapted(options, key):
        source = options.get(key)
        if not source:
            return options
        target = source if source in by_code else aliases.get(source, source).removesuffix("-all-in-one") + "-all-in-one"
        if target not in by_code:
            target = primary
        caps = by_code[target]["capabilities"]
        ratio = options.get("ratio", "16:9")
        if ratio not in caps["ratios"] or options.get("h3Mode", "auto") not in caps["referenceModes"]:
            target = primary
            caps = by_code[target]["capabilities"]
        result = {**options, key: target}
        if result.get("resolution") not in caps["resolutions"]:
            result["resolution"] = "720p" if "720p" in caps["resolutions"] else caps["resolutions"][0]
        for field, capability in (("generateAudio", "audioToggle"), ("watermark", "watermarkToggle")):
            if caps.get(capability) is False:
                result[field] = False
        if caps.get("referenceResolutions") and options.get("h3Mode", "auto") in {"auto", "reference"}:
            if result.get("resolution") not in caps["referenceResolutions"]:
                result["resolution"] = "720p"
        if "duration" in options:
            allowed = caps.get("durationOptions") or list(range(caps["durations"]["min"], caps["durations"]["max"] + 1))
            duration = float(options.get("duration") or 5)
            result["duration"] = min(allowed, key=lambda v: (abs(v - duration), -v))
        if target != source:
            result["videoModelMigration"] = {"from": source, "to": target, "revision": revision}
        return result

    for task in db.execute(sa.select(tasks).where(tasks.c.deleted_at.is_(None))).mappings():
        original = task["storyboard_config"] or {}
        config = adapted(adapted(original, "video_model"), "videoModel")
        if isinstance(config.get("videoModelDefaults"), dict):
            config = {**config, "videoModelDefaults": adapted(config["videoModelDefaults"], "videoModel")}
        if config != original:
            db.execute(tasks.update().where(tasks.c.id == task["id"]).values(storyboard_config=config, updated_at=now))
    for line in db.execute(sa.select(lines.c.id, lines.c.shot_options).where(lines.c.deleted_at.is_(None))).mappings():
        original = line["shot_options"] or {}
        options = adapted(original, "videoModel")
        if options != original:
            db.execute(lines.update().where(lines.c.id == line["id"]).values(shot_options=options, updated_at=now))


def downgrade():
    pass  # Do not restore retired routes or rewrite historical media and billing.
