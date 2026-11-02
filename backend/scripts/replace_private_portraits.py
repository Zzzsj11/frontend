"""Apply a reviewed data-only Alembic operation; never generate or delete media.

Manifest contains run_id, user_id, environment, and items with id, before/after
avatar_url and avatar_thumbnail_url. Original URLs remain in the operation log.
The application schema revision is unchanged by this data-only operation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.database import engine
from app.models import AdminOperationLogModel, DigitalHumanModel
from app.storage import is_user_owned_tos_url


def apply(connection, manifest):
    humans = DigitalHumanModel.__table__
    logs = AdminOperationLogModel.__table__
    user_id, run_id = manifest["user_id"], manifest["run_id"]
    items = manifest["items"]
    if not items or len({item["id"] for item in items}) != len(items):
        raise ValueError("Empty or duplicate replacement manifest")
    prepared = []
    for item in items:
        row = connection.execute(sa.select(humans).where(humans.c.id == item["id"]).with_for_update()).mappings().one()
        if row["user_id"] != user_id or row["scope"] != "private" or row["deleted_at"] is not None:
            raise ValueError("Replacement is restricted to live assets belonging to the authorized user")
        before, after = item["before"], item["after"]
        keys = {"avatar_url", "avatar_thumbnail_url"}
        if "avatar_prompt" in before or "avatar_prompt" in after:
            keys.add("avatar_prompt")
        if set(before) != keys or set(after) != keys:
            raise ValueError("Only portrait URLs and the corresponding generation prompt can be replaced")
        if not all(is_user_owned_tos_url(after[key], user_id) for key in {"avatar_url", "avatar_thumbnail_url"}):
            raise ValueError("Both replacement files must be in the user TOS prefix")
        if all(row[key] == after[key] for key in keys):
            continue
        if any(row[key] != before[key] for key in keys):
            raise ValueError("Asset changed after inventory; refusing to overwrite newer work")
        prepared.append((item, before, after))
    operations = Operations(MigrationContext.configure(connection))
    now = datetime.now(timezone.utc)
    for item, before, after in prepared:
        operations.execute(humans.update().where(humans.c.id == item["id"], humans.c.user_id == user_id).values(**after, updated_at=now))
        operations.execute(
            logs.insert().values(
                id="portrait-" + uuid.uuid4().hex,
                admin_user_id=user_id,
                action="agent.private_portrait.replace",
                target_type="digital_human",
                target_id=item["id"],
                before_data=before,
                after_data={**after, "agent_name": "code-agent", "agent_run_id": run_id, "platform_job_id": item["platform_job_id"]},
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
        )
    return len(prepared)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    tier = os.getenv("DEPLOYMENT_TIER")
    if tier != manifest["environment"] or tier not in {"test", "production"}:
        raise ValueError("Environment mismatch")
    if not args.apply:
        print(json.dumps({"environment": tier, "count": len(manifest["items"]), "applied": False}))
        return
    async with engine.begin() as connection:
        count = await connection.run_sync(apply, manifest)
    print(json.dumps({"run": manifest["run_id"], "updated": count, "environment": tier}))


if __name__ == "__main__":
    asyncio.run(main())
