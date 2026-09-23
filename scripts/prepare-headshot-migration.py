#!/usr/bin/env python3
"""Compile a prepared system-only asset mapping into a reviewable Alembic revision.

Offline: no uploads, generation or database writes. Never modifies seed files.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

FIELDS = {
    "avatar_url",
    "avatar_thumbnail_url",
    "asset_avatar_url",
    "description",
    "appearance_style",
    "clothing_description",
    "suitable_music_styles",
    "avatar_prompt",
    "system_prompt",
}
TEMPLATE = '''"""Apply reviewed system headshots; preserve history and reject stale/private records."""
import json
from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op

revision = {revision!r}
down_revision = {parent!r}
branch_labels = depends_on = None
ROWS = json.loads({rows!r})

def normalized(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=datetime.fromisoformat(value).tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    return value

def upgrade():
    db = op.get_bind()
    table = sa.Table('digital_humans', sa.MetaData(), autoload_with=db)
    changes = []
    for item in ROWS:
        row = db.execute(sa.select(table).where(table.c.id == item['id']).with_for_update()).mappings().first()
        if not row or row['deleted_at'] is not None or row['scope'] != 'system' or row['user_id'] is not None:
            raise RuntimeError('Headshot target is not an active system human: ' + item['id'])
        if all(row[k] == v for k,v in item['updates'].items()):
            continue
        if any(normalized(row[k]) != normalized(v) for k,v in item['expected_old'].items()):
            raise RuntimeError('Stale headshot mapping; prepare a new reviewed mapping: ' + item['id'])
        changes.append(item)
    for item in changes:
        db.execute(table.update().where(table.c.id == item['id']).values(**item['updates'], updated_at=datetime.now(timezone.utc)))

def downgrade():
    raise RuntimeError('Keep asset history; use a reviewed forward migration based on the saved backup')
'''


def compile_mapping(document, revision, parent):
    if (
        not all(re.fullmatch(r"[a-zA-Z0-9_]{1,32}", v) for v in (revision, parent))
        or revision == parent
    ):
        raise ValueError("Invalid revision identifiers")
    if (
        document.get("schema_version") != 1
        or document.get("status") != "prepared"
        or document.get("committed") is not False
    ):
        raise ValueError(
            "Only a fully prepared, uncommitted mapping can become a migration"
        )
    rows = document.get("humans")
    if (
        not isinstance(rows, list)
        or not rows
        or len({r["id"] for r in rows}) != len(rows)
    ):
        raise ValueError("Expected unique nonempty system human rows")
    clean = []
    for row in rows:
        old = row["expected_old"]
        updates = row["updates"]
        if not {"id", "scope", "user_id", "deleted_at", "updated_at", *FIELDS} <= set(
            old
        ):
            raise ValueError(
                "Expected a complete system asset backup including lifecycle fields"
            )
        if (
            row.get("status") != "prepared"
            or row.get("provider") != "yinghe"
            or old.get("scope") != "system"
            or old.get("user_id") is not None
            or old.get("deleted_at") is not None
            or old.get("id") != row["id"]
        ):
            raise ValueError("Private, deleted or unprepared asset is not permitted")
        if set(updates) != FIELDS or not all(
            isinstance(v, str) for v in updates.values()
        ):
            raise ValueError("Unexpected asset update columns")
        hosts = []
        for field in ("avatar_url", "avatar_thumbnail_url"):
            url = urlsplit(updates[field])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
            ):
                raise ValueError(
                    "Use persistent public TOS HTTPS URLs without credentials or signatures"
                )
            hosts.append(url.hostname)
        if (
            hosts[0] != hosts[1]
            or not updates["asset_avatar_url"].startswith("asset://")
            or len(updates["asset_avatar_url"]) <= 8
        ):
            raise ValueError(
                "Original/thumbnail domains or Yinghe asset identifier are invalid"
            )
        clean.append({"id": row["id"], "expected_old": old, "updates": updates})
    return TEMPLATE.format(
        revision=revision,
        parent=parent,
        rows=json.dumps(clean, ensure_ascii=False, sort_keys=True),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--parent", required=True, help="Current Alembic head")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--seed-output",
        required=True,
        type=Path,
        help="Matching backend/app/headshot-assets.json release artifact",
    )
    args = parser.parse_args()
    data = json.loads(args.mapping.read_text())
    result = compile_mapping(data, args.revision, args.parent)
    if args.output.exists() or args.seed_output.exists():
        raise ValueError("Refusing to overwrite a migration or seed artifact")
    with args.output.open("x") as stream:
        stream.write(result)
    with args.seed_output.open("x") as stream:
        json.dump(
            {row["id"]: row["updates"] for row in data["humans"]},
            stream,
            ensure_ascii=False,
            indent=2,
        )
    print(
        json.dumps(
            {
                "migration": str(args.output),
                "mapping_sha256": hashlib.sha256(args.mapping.read_bytes()).hexdigest(),
                "rows": len(data["humans"]),
                "database_modified": False,
                "seed_artifact": str(args.seed_output),
            }
        )
    )


if __name__ == "__main__":
    main()
