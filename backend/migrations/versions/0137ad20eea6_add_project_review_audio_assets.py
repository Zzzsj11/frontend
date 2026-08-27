"""add project review audio assets

Revision ID: 0137ad20eea6
Revises: ef5b49ce406b
Create Date: 2026-08-26 21:58:41.400518
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0137ad20eea6"
down_revision: Union[str, None] = "ef5b49ce406b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_audio_assets",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("project_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", sa.String(length=80), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("audio_url", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_audio_assets_project_id"), "project_audio_assets", ["project_id"], unique=False)
    op.create_index(op.f("ix_project_audio_assets_user_id"), "project_audio_assets", ["user_id"], unique=False)
    op.create_index(op.f("ix_project_audio_assets_is_current"), "project_audio_assets", ["is_current"], unique=False)
    op.create_index(op.f("ix_project_audio_assets_deleted_at"), "project_audio_assets", ["deleted_at"], unique=False)
    op.create_index(
        "uq_project_audio_current_active",
        "project_audio_assets",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND is_current = true"),
        sqlite_where=sa.text("deleted_at IS NULL AND is_current = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_audio_current_active", table_name="project_audio_assets")
    op.drop_index(op.f("ix_project_audio_assets_deleted_at"), table_name="project_audio_assets")
    op.drop_index(op.f("ix_project_audio_assets_is_current"), table_name="project_audio_assets")
    op.drop_index(op.f("ix_project_audio_assets_user_id"), table_name="project_audio_assets")
    op.drop_index(op.f("ix_project_audio_assets_project_id"), table_name="project_audio_assets")
    op.drop_table("project_audio_assets")
