"""Group rotating refresh credentials for replay revocation."""

import sqlalchemy as sa
from alembic import op

revision = "b28d0f5c7e31"
down_revision = "a17c9e4b6d20"
branch_labels = depends_on = None


def upgrade():
    op.add_column("refresh_tokens", sa.Column("family_id", sa.String(80), nullable=False, server_default=""))
    op.execute(sa.text("UPDATE refresh_tokens SET family_id = id"))
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade():
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "family_id")
