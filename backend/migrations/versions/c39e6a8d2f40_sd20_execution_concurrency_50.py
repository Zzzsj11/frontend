"""Set the MV SD2.0 execution pool ceiling to 50."""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "c39e6a8d2f40"
down_revision = "b28d0f5c7e31"
branch_labels = depends_on = None


def upgrade():
    db = op.get_bind()
    models = sa.Table("ai_models", sa.MetaData(), autoload_with=db)
    rows = db.execute(sa.select(models.c.id, models.c.capabilities).where(models.c.code == "doubao-seedance-2.0-all-in-one", models.c.deleted_at.is_(None))).mappings()
    for row in rows:
        capabilities = {**(row["capabilities"] or {}), "executionConcurrency": 50}
        db.execute(models.update().where(models.c.id == row["id"]).values(capabilities=capabilities, updated_at=datetime.now(timezone.utc)))


def downgrade():
    raise RuntimeError("Preserve the operator-approved concurrency ceiling; use a forward migration")
