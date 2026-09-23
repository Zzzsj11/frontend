"""Independent supplier routes and immutable per-job selection."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_routes",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("model_id", sa.String(160), nullable=False, index=True),
        sa.Column("supplier", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("provider_model", sa.String(160), nullable=False),
        sa.Column("protocol", sa.String(40), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("concurrency", sa.Integer, nullable=False),
        sa.Column("verification", sa.String(40), nullable=False),
        sa.Column("capabilities", sa.JSON, nullable=False),
        sa.Column("pricing", sa.JSON, nullable=False),
    )
    op.add_column("jobs", sa.Column("route_id", sa.String(160)))
    op.add_column("jobs", sa.Column("routing_snapshot", sa.JSON, nullable=False, server_default="{}"))
    op.create_index("ix_jobs_route_id", "jobs", ["route_id"])


def downgrade():
    raise RuntimeError("Preserve route and billing history; use a forward migration")
