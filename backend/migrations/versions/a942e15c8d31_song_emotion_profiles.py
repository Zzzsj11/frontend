"""song emotion profiles

Revision ID: a942e15c8d31
Revises: e841bf50a62c
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a942e15c8d31"
down_revision: Union[str, None] = "e841bf50a62c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "song_emotion_profiles",
        sa.Column("song_code", sa.String(length=80), nullable=False),
        sa.Column("song_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("artists", sa.Text(), server_default="", nullable=False),
        sa.Column("primary_category", sa.String(length=255), nullable=True),
        sa.Column("secondary_category", sa.String(length=255), nullable=True),
        sa.Column("tertiary_category", sa.String(length=255), nullable=True),
        sa.Column("material_category", sa.Text(), server_default="", nullable=False),
        sa.Column("seasons", sa.String(length=120), server_default="", nullable=False),
        sa.Column("atmosphere", sa.Text(), server_default="", nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("song_code"),
    )
    op.create_index(op.f("ix_song_emotion_profiles_deleted_at"), "song_emotion_profiles", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_table("song_emotion_profiles")
