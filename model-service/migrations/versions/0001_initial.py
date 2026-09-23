"""Initial service schema, frozen independently from application models."""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    spec = importlib.util.spec_from_file_location("initial_contract", Path(__file__).parents[1] / "initial_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for table in module.Base.metadata.sorted_tables:
        table.create(op.get_bind(), checkfirst=False)


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore backup or deploy a forward migration")
