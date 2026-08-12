"""digital human asset avatar url

Revision ID: d4f2b8e6a1c0
Revises: c812a9e4d501
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f2b8e6a1c0"
down_revision: Union[str, None] = "c812a9e4d501"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("digital_humans", sa.Column("asset_avatar_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("digital_humans", "asset_avatar_url")
