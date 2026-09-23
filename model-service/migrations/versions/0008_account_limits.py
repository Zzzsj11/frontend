"""Account monthly ceilings; existing balances and ownership are preserved."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = depends_on = None


def upgrade():
    op.add_column("portal_users", sa.Column("monthly_points", sa.Numeric(24, 6), nullable=False, server_default="0"))
    # Preserve existing users' configured aggregate monthly allowance without minting credits.
    op.execute(
        "UPDATE portal_users SET monthly_points = COALESCE((SELECT SUM(monthly_points) FROM clients WHERE clients.user_id = portal_users.id AND clients.deleted_at IS NULL), 0)"
    )


def downgrade():
    raise RuntimeError("Account ceilings must be retained; use a forward migration")
