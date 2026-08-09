"""scene and shot thumbnails

Revision ID: f49c2a7e8d61
Revises: c3f1a29e6b40
"""
from alembic import op
import sqlalchemy as sa

revision = "f49c2a7e8d61"
down_revision = "c3f1a29e6b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scene_assets", sa.Column("image_thumbnail_url", sa.Text(), nullable=True))
    op.add_column("shot_assets", sa.Column("cover_thumbnail_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shot_assets", "cover_thumbnail_url")
    op.drop_column("scene_assets", "image_thumbnail_url")
