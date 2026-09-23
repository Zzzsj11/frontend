"""Portal ownership and append-only credit ledger."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("billing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    for name in ("monthly_points", "monthly_balance", "extra_balance"):
        op.add_column("clients", sa.Column(name, sa.Numeric(24, 6), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("user_id", sa.String(160), nullable=True))
    op.create_index("ix_clients_user_id", "clients", ["user_id"])
    op.add_column("clients", sa.Column("billing_month", sa.String(7), nullable=False, server_default=""))
    op.add_column("jobs", sa.Column("reserved_points", sa.Numeric(24, 6), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("charged_points", sa.Numeric(24, 6), nullable=True))
    op.add_column("jobs", sa.Column("billing_status", sa.String(40), nullable=False, server_default="pending"))
    op.add_column("jobs", sa.Column("pricing_snapshot", sa.JSON(), nullable=False, server_default="{}"))
    spec = importlib.util.spec_from_file_location("portal_contract", Path(__file__).parents[1] / "portal_contract.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("portal_users", "portal_sessions", "pricing_rules", "credit_ledger"):
        module.Base.metadata.tables[name].create(op.get_bind())


def downgrade():
    raise RuntimeError("Financial records cannot be deleted; use forward migrations")
