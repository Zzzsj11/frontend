"""Relax shot direction rules, preserving operator content and prompt history."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "a8c4e2f6b109"
down_revision = "e7a3b9c2f104"
branch_labels = depends_on = None
DATA = json.loads((Path(__file__).parents[1] / "data/shot-direction-20260923.json").read_text())


def transform(key, content):
    values = json.loads(content) if DATA["keys"][key] == "json" else [content]
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError(f"Invalid published prompt: {key}")
    for old, new in DATA["replacements"]:
        values = [v.replace(old, new) for v in values]
    if key != "story_bible.ass.negative_constraints" and not any(DATA["policy"] in v for v in values):
        if DATA["keys"][key] == "json":
            values.append(DATA["policy"])
        else:
            values[0] += DATA["policy"]
    return json.dumps(values, ensure_ascii=False, indent=2) if DATA["keys"][key] == "json" else values[0]


def upgrade():
    db = op.get_bind()
    templates = sa.Table("prompt_templates", sa.MetaData(), autoload_with=db)
    versions = sa.Table("prompt_versions", sa.MetaData(), autoload_with=db)
    stamp = datetime.now(timezone.utc)
    for key in DATA["keys"]:
        template = db.execute(sa.select(templates).where(templates.c.key == key, templates.c.deleted_at.is_(None))).mappings().first()
        if not template or not template["current_version_id"]:
            continue  # Fresh databases are initialized by seed with the new defaults.
        current = db.execute(sa.select(versions).where(versions.c.id == template["current_version_id"], versions.c.deleted_at.is_(None))).mappings().first()
        if not current:
            raise RuntimeError(f"Missing published prompt version: {key}")
        content = transform(key, current["content"])
        fragments = list(template["required_fragments"] or [])
        for old, new in DATA["replacements"]:
            fragments = [fragment.replace(old, new) for fragment in fragments]
        if fragments != template["required_fragments"]:
            db.execute(templates.update().where(templates.c.id == template["id"]).values(required_fragments=fragments, updated_at=stamp))
        if content == current["content"]:
            continue
        if any(fragment not in content for fragment in fragments):
            raise RuntimeError(f"Shot direction upgrade would lose an operator safety constraint: {key}")
        variables = set(re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", content))
        if not variables <= set(template["variables"] or {}):
            raise RuntimeError(f"Shot direction prompt contains undeclared variables: {key}")
        highest = db.scalar(sa.select(sa.func.max(versions.c.version)).where(versions.c.template_id == template["id"])) or 0
        ident = "pv-shot-direction-" + uuid.uuid4().hex[:16]
        db.execute(versions.update().where(versions.c.id == current["id"]).values(status="archived", updated_at=stamp))
        db.execute(
            versions.insert().values(
                id=ident,
                template_id=template["id"],
                version=highest + 1,
                content=content,
                change_note="放开发型与陪衬人物；保留无关运营规则",
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
