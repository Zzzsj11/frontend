"""Reproducible initial selected catalog and indicative quotes; never enable generation."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None


def upgrade():
    data = json.loads((Path(__file__).parents[1] / "data/catalog-20260922.json").read_text())
    connection = op.get_bind()
    stamp = datetime.now(timezone.utc)
    for table_name, records in (("models", data["models"]), ("model_routes", data["routes"])):
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        for row in records:
            # Include tombstones in this check: never resurrect or overwrite an operator edit.
            if connection.execute(sa.select(table.c.id).where(table.c.id == row["id"])).first():
                continue
            connection.execute(table.insert().values(**row, created_at=stamp, updated_at=stamp))
    # Record the public artifact identity, not secrets or user data.
    audits = sa.Table("audits", sa.MetaData(), autoload_with=connection)
    ident = "catalog-release-20260922"
    if not connection.execute(sa.select(audits.c.id).where(audits.c.id == ident)).first():
        audits_data = {
            "version": data["version"],
            "sha256": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
            "models": len(data["models"]),
            "routes": len(data["routes"]),
            "enabled": False,
        }
        connection.execute(
            audits.insert().values(
                id=ident,
                actor="alembic",
                action="catalog.release",
                target="model-catalog",
                detail=audits_data,
                created_at=stamp,
                updated_at=stamp,
            )
        )


def downgrade():
    raise RuntimeError("Catalog and quote history are retained; use a forward migration")
