"""admin console v1

Revision ID: ab91d76f502e
Revises: f49c2a7e8d61
"""

import sqlalchemy as sa
from alembic import op

revision = "ab91d76f502e"
down_revision = "f49c2a7e8d61"
branch_labels = None
depends_on = None

LIFE = [
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
]


def table(name, *columns):
    op.create_table(name, *columns, *[sa.Column(c.name, c.type, nullable=c.nullable) for c in LIFE])
    op.create_index(f"ix_{name}_deleted_at", name, ["deleted_at"])


def upgrade():
    table(
        "admin_roles",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("code", sa.String(80), unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    table("admin_permissions", sa.Column("id", sa.String(80), primary_key=True), sa.Column("code", sa.String(120), unique=True), sa.Column("name", sa.String(120), nullable=False))
    table(
        "admin_role_permissions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("role_id", sa.String(80), sa.ForeignKey("admin_roles.id"), nullable=False),
        sa.Column("permission_id", sa.String(80), sa.ForeignKey("admin_permissions.id"), nullable=False),
    )
    table(
        "user_admin_roles",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("user_id", sa.String(80), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_id", sa.String(80), sa.ForeignKey("admin_roles.id"), nullable=False),
    )
    table(
        "admin_operation_logs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("admin_user_id", sa.String(80), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(160)),
        sa.Column("before_data", sa.JSON(), nullable=False),
        sa.Column("after_data", sa.JSON(), nullable=False),
        sa.Column("client_ip", sa.String(80)),
    )
    table(
        "ai_providers",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("code", sa.String(80), unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    table(
        "ai_models",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("provider_id", sa.String(80), sa.ForeignKey("ai_providers.id"), nullable=False),
        sa.Column("code", sa.String(160), unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False),
        sa.Column("provider_model_id", sa.String(200), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("user_visible", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    table(
        "model_price_versions",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("model_id", sa.String(80), sa.ForeignKey("ai_models.id"), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("input_price", sa.Float(), nullable=False),
        sa.Column("output_price", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for name in ["model_price_versions", "ai_models", "ai_providers", "admin_operation_logs", "user_admin_roles", "admin_role_permissions", "admin_permissions", "admin_roles"]:
        op.drop_table(name)
