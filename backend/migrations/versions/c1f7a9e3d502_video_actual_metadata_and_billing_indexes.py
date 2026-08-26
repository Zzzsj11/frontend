"""store actual video metadata and add billing indexes

Revision ID: c1f7a9e3d502
Revises: b4e8c2d7a913
"""

import sqlalchemy as sa
from alembic import op

revision = "c1f7a9e3d502"
down_revision = "b4e8c2d7a913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shot_assets", sa.Column("requested_resolution", sa.String(32), nullable=False, server_default="1080p"))
    op.add_column("shot_assets", sa.Column("provider_resolution", sa.String(32), nullable=False, server_default=""))
    op.add_column("shot_assets", sa.Column("actual_width", sa.Integer(), nullable=True))
    op.add_column("shot_assets", sa.Column("actual_height", sa.Integer(), nullable=True))
    op.add_column("shot_assets", sa.Column("fps", sa.Float(), nullable=True))
    op.add_column("shot_assets", sa.Column("codec", sa.String(32), nullable=False, server_default=""))
    op.add_column("shot_assets", sa.Column("actual_duration", sa.Float(), nullable=True))
    op.add_column("shot_assets", sa.Column("file_size", sa.BigInteger(), nullable=True))
    op.create_index("ix_video_billing_completed_status", "video_billing_records", ["completed_at", "billing_status"], unique=False)
    op.create_index("ix_video_billing_model_completed", "video_billing_records", ["model", "completed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_video_billing_model_completed", table_name="video_billing_records")
    op.drop_index("ix_video_billing_completed_status", table_name="video_billing_records")
    for column in ("file_size", "actual_duration", "codec", "fps", "actual_height", "actual_width", "provider_resolution", "requested_resolution"):
        op.drop_column("shot_assets", column)
