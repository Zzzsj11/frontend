"""project sort order

Revision ID: c812a9e4d501
Revises: b3e8f1a42c07
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c812a9e4d501"
down_revision: Union[str, None] = "b3e8f1a42c07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_index(op.f("ix_projects_sort_order"), "projects", ["sort_order"])
    op.add_column("project_tasks", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_index(op.f("ix_projects_sort_order"), table_name="projects")
    op.drop_column("project_tasks", "sort_order")
    op.drop_column("projects", "sort_order")
