"""Protect current scene selection and shared text execution capacity."""

import sqlalchemy as sa
from alembic import op

revision = "eb617531ca10"
down_revision = "a103e9c7d251"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "text_execution_slots",
        sa.Column("slot", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("owner", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_text_execution_slots_deleted_at", "text_execution_slots", ["deleted_at"])
    # Old image workers may still be writing while the green container migrates.
    # Wait for in-flight writes, then keep new writes out until the index commits.
    if op.get_context().dialect.name == "postgresql":
        op.execute("LOCK TABLE scene_assets IN SHARE ROW EXCLUSIVE MODE")
    # Preserve historical assets; only resolve conflicting selections, newest first.
    op.execute("""
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY storyboard_line_id ORDER BY created_at DESC, id DESC) AS rank
            FROM scene_assets WHERE deleted_at IS NULL AND is_current
        )
        UPDATE scene_assets SET is_current = false, updated_at = CURRENT_TIMESTAMP
        WHERE id IN (SELECT id FROM ranked WHERE rank > 1)
    """)
    clause = sa.text("deleted_at IS NULL AND is_current")
    op.create_index("uq_scene_current_active", "scene_assets", ["storyboard_line_id"], unique=True, postgresql_where=clause, sqlite_where=clause)


def downgrade():
    op.drop_table("text_execution_slots")
    op.drop_index("uq_scene_current_active", table_name="scene_assets")
