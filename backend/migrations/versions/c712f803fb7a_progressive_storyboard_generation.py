"""progressive storyboard generation

Revision ID: c712f803fb7a
Revises: fb942da7380f
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c712f803fb7a"
down_revision: Union[str, None] = "fb942da7380f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("storyboard_lines", sa.Column("generation_status", sa.String(length=32), server_default="succeeded", nullable=False))
    op.add_column("storyboard_lines", sa.Column("generation_error", sa.Text(), nullable=True))
    op.add_column("storyboard_lines", sa.Column("generation_attempt", sa.Integer(), server_default="0", nullable=False))
    op.add_column("storyboard_lines", sa.Column("prompt_context_hash", sa.String(length=64), nullable=True))
    op.add_column("storyboard_lines", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_storyboard_lines_generation_status"), "storyboard_lines", ["generation_status"], unique=False)
    op.create_index(op.f("ix_storyboard_lines_prompt_context_hash"), "storyboard_lines", ["prompt_context_hash"], unique=False)
    # Upgrade the legacy bootstrap account in place so ownership and refresh tokens remain intact.
    op.execute("UPDATE users SET username = 'admin', updated_at = now() WHERE username = 'admin01' AND NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin')")


def downgrade() -> None:
    op.drop_index(op.f("ix_storyboard_lines_prompt_context_hash"), table_name="storyboard_lines")
    op.drop_index(op.f("ix_storyboard_lines_generation_status"), table_name="storyboard_lines")
    op.drop_column("storyboard_lines", "generated_at")
    op.drop_column("storyboard_lines", "prompt_context_hash")
    op.drop_column("storyboard_lines", "generation_attempt")
    op.drop_column("storyboard_lines", "generation_error")
    op.drop_column("storyboard_lines", "generation_status")
