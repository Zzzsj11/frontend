"""admin rbac constraints

Revision ID: 8c4f2d1a9e60
Revises: 7b3e4d9a1c52
"""

import sqlalchemy as sa
from alembic import op

revision = "8c4f2d1a9e60"
down_revision = "7b3e4d9a1c52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_admin_role_permission_active",
        "admin_role_permissions",
        ["role_id", "permission_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_user_admin_role_active",
        "user_admin_roles",
        ["user_id", "role_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_admin_role_active", table_name="user_admin_roles")
    op.drop_index("uq_admin_role_permission_active", table_name="admin_role_permissions")
