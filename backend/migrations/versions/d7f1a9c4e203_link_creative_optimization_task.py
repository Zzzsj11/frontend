"""link creative storyboard lines to prompt optimization tasks

Revision ID: d7f1a9c4e203
Revises: c4e8f7a2b913
"""

from alembic import op

revision = "d7f1a9c4e203"
down_revision = "c4e8f7a2b913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_storyboard_lines_optimization_task_id",
        "storyboard_lines",
        "prompt_optimization_tasks",
        ["optimization_task_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_storyboard_lines_optimization_task_id",
        "storyboard_lines",
        type_="foreignkey",
    )
