"""add shot asset model code

Revision ID: a4d7c2e9f103
Revises: b8e5f3a1d2c4
"""

import sqlalchemy as sa
from alembic import op

revision = "a4d7c2e9f103"
down_revision = "b8e5f3a1d2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shot_assets", sa.Column("model_code", sa.String(length=160), nullable=True))
    op.create_index("ix_shot_assets_model_code", "shot_assets", ["model_code"])
    op.execute(
        """
        UPDATE shot_assets AS asset
        SET model_code = job.request ->> 'model'
        FROM generation_jobs AS job
        WHERE asset.generation_job_id = job.id
          AND asset.model_code IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_shot_assets_model_code", table_name="shot_assets")
    op.drop_column("shot_assets", "model_code")
