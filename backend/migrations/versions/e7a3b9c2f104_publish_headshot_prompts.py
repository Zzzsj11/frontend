"""Publish reviewed headshot rules, preserving unrelated operator content and history."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "e7a3b9c2f104"
down_revision = "d6f2a8c1e903"
branch_labels = depends_on = None
DATA = json.loads((Path(__file__).parents[1] / "data/headshot-prompts-20260922.json").read_text())


def transform(key, content):
    spec = DATA[key]
    values = json.loads(content) if spec["format"] == "json" else [content]
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError(f"Invalid published prompt: {key}")
    for old, new in spec["replacements"]:
        if any(new in v for v in values):
            continue
        known = [candidate for candidate in [old, *spec.get("legacy_alternatives", [])] if sum(v.count(candidate) for v in values) == 1]
        if len(known) != 1:
            raise RuntimeError(f"Custom headshot rule needs an explicit merge before migration: {key}; no content overwritten")
        values = [v.replace(known[0], new) for v in values]
    return json.dumps(values, ensure_ascii=False, indent=2) if spec["format"] == "json" else values[0]


def upgrade():
    db = op.get_bind()
    templates = sa.Table("prompt_templates", sa.MetaData(), autoload_with=db)
    versions = sa.Table("prompt_versions", sa.MetaData(), autoload_with=db)
    stamp = datetime.now(timezone.utc)
    for key in DATA:
        template = db.execute(sa.select(templates).where(templates.c.key == key, templates.c.deleted_at.is_(None))).mappings().first()
        if not template or not template["current_version_id"]:
            continue  # Fresh databases are initialized by seed with the new defaults.
        current = db.execute(sa.select(versions).where(versions.c.id == template["current_version_id"], versions.c.deleted_at.is_(None))).mappings().first()
        if not current:
            raise RuntimeError(f"Missing published prompt version: {key}")
        content = transform(key, current["content"])
        fragments = [fragment for fragment in (template["required_fragments"] or []) if fragment not in DATA[key].get("legacy_required_fragments", []) or fragment in content]
        if fragments != template["required_fragments"]:
            db.execute(templates.update().where(templates.c.id == template["id"]).values(required_fragments=fragments, updated_at=stamp))
        if content == current["content"]:
            continue
        if any(fragment not in content for fragment in fragments):
            raise RuntimeError(f"Headshot upgrade would lose an operator safety constraint: {key}")
        variables = set(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", content))
        if not variables <= set(template["variables"] or {}):
            raise RuntimeError(f"Headshot prompt contains undeclared variables: {key}")
        highest = db.scalar(sa.select(sa.func.max(versions.c.version)).where(versions.c.template_id == template["id"])) or 0
        ident = "pv-headshot-" + uuid.uuid4().hex[:16]
        db.execute(versions.update().where(versions.c.id == current["id"]).values(status="archived", updated_at=stamp))
        db.execute(
            versions.insert().values(
                id=ident,
                template_id=template["id"],
                version=highest + 1,
                content=content,
                change_note="单图头肩照；保留无关运营规则",
                status="published",
                created_by="system-migration",
                published_at=stamp,
                created_at=stamp,
                updated_at=stamp,
                deleted_at=None,
            )
        )
        db.execute(templates.update().where(templates.c.id == template["id"]).values(current_version_id=ident, updated_at=stamp))


def downgrade():
    raise RuntimeError("Retain published prompt history; publish a compatible correction instead")
