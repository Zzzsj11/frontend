"""generation result observation

Revision ID: e02a4c7d91b5
Revises: d91e3b6c70a4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e02a4c7d91b5"
down_revision: Union[str, None] = "d91e3b6c70a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("first_result_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_generation_jobs_first_result_observed_at"), "generation_jobs", ["first_result_observed_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_jobs_first_result_observed_at"), table_name="generation_jobs")
    op.drop_column("generation_jobs", "first_result_observed_at")
