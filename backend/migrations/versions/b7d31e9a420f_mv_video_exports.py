"""Persist independent MV exports and immutable input snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "b7d31e9a420f"
down_revision = "a8c4e2f6b109"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("material_exports", sa.Column("export_kind", sa.String(24), nullable=False, server_default="materials"))
    op.add_column("material_exports", sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("material_exports", sa.Column("result_metadata", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("material_exports", "result_metadata")
    op.drop_column("material_exports", "input_snapshot")
    op.drop_column("material_exports", "export_kind")
