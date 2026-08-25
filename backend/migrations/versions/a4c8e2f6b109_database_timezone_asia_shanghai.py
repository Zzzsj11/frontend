"""set database display timezone to Asia/Shanghai

Revision ID: a4c8e2f6b109
Revises: d3f5a7c9e102
"""

from alembic import op
from sqlalchemy import text

revision = "a4c8e2f6b109"
down_revision = "d3f5a7c9e102"
branch_labels = None
depends_on = None


def _set_database_timezone(timezone_name: str) -> None:
    bind = op.get_bind()
    database_name = bind.execute(text("SELECT current_database()")).scalar_one()
    quoted_name = bind.dialect.identifier_preparer.quote(database_name)
    escaped_timezone = timezone_name.replace("'", "''")
    op.execute(f"ALTER DATABASE {quoted_name} SET timezone TO '{escaped_timezone}'")
    op.execute(f"SET timezone TO '{escaped_timezone}'")


def upgrade() -> None:
    _set_database_timezone("Asia/Shanghai")


def downgrade() -> None:
    _set_database_timezone("UTC")
