"""Persist administrator hashes and session revocation versions."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "admin_credentials",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("username", sa.String(160), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='model_public') THEN REVOKE ALL ON admin_credentials FROM model_public; END IF; END $$;"
        )


def downgrade():
    raise RuntimeError("Administrator credential history is retained; use a forward migration")
