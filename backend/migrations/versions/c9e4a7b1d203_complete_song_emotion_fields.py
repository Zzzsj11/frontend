"""complete song emotion fields

Revision ID: c9e4a7b1d203
Revises: a8f1c2d3e4b5
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4a7b1d203"
down_revision: str | None = "a8f1c2d3e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("song_emotion_profiles", sa.Column("lyrics", sa.Text(), server_default="", nullable=False))
    op.add_column("song_emotion_profiles", sa.Column("character_setting", sa.Text(), server_default="", nullable=False))
    op.add_column("song_emotion_profiles", sa.Column("status", sa.Integer(), server_default="2", nullable=False))
    op.create_index(op.f("ix_song_emotion_profiles_status"), "song_emotion_profiles", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_song_emotion_profiles_status"), table_name="song_emotion_profiles")
    op.drop_column("song_emotion_profiles", "status")
    op.drop_column("song_emotion_profiles", "character_setting")
    op.drop_column("song_emotion_profiles", "lyrics")
