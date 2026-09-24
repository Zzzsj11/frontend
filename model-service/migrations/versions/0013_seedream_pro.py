"""Add distinct Toapis Seedream 5.0 Pro catalog and resolution-specific quotes."""

import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = depends_on = None


def upgrade():
    data = json.loads((Path(__file__).parents[1] / "data/seedream-pro-20260924.json").read_text())
    connection = op.get_bind()
    stamp = datetime.now(timezone.utc)
    for name, rows in (("models", data["models"]), ("model_routes", data["routes"])):
        table = sa.Table(name, sa.MetaData(), autoload_with=connection)
        for row in rows:
            if not connection.execute(sa.select(table.c.id).where(table.c.id == row["id"])).first():
                connection.execute(table.insert().values(**row, created_at=stamp, updated_at=stamp, deleted_at=None))


def downgrade():
    raise RuntimeError("Model history is retained; use a forward migration")
