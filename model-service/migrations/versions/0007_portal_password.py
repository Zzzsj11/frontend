"""Require a first password change for new and existing portal accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = depends_on = None


def upgrade():
    op.add_column("portal_users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    raise RuntimeError("Password change history is retained; use a forward migration")
