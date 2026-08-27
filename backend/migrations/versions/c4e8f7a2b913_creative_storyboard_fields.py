"""creative storyboard fields

Revision ID: c4e8f7a2b913
Revises: 8b31d9f4a2c7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8f7a2b913"
down_revision: Union[str, None] = "8b31d9f4a2c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("storyboard_lines", sa.Column("original_prompt", sa.Text(), nullable=False, server_default=""))
    op.add_column("storyboard_lines", sa.Column("optimized_prompt", sa.Text(), nullable=False, server_default=""))
    op.add_column("storyboard_lines", sa.Column("reference_media", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("storyboard_lines", sa.Column("optimizer_provider", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("storyboard_lines", sa.Column("optimization_task_id", sa.String(length=80), nullable=True))
    op.create_index(op.f("ix_storyboard_lines_optimization_task_id"), "storyboard_lines", ["optimization_task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_storyboard_lines_optimization_task_id"), table_name="storyboard_lines")
    for name in ("optimization_task_id", "optimizer_provider", "reference_media", "optimized_prompt", "original_prompt"):
        op.drop_column("storyboard_lines", name)
