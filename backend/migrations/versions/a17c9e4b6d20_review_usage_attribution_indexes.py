"""Preserve source attribution on every usage/log and index asset lookups."""

import sqlalchemy as sa
from alembic import op

revision = "a17c9e4b6d20"
down_revision = "9a3d7f2c6b80"
branch_labels = depends_on = None


ATTRIBUTION_TABLES = ("token_usage_records", "llm_call_logs")
ASSET_TABLES = ("scene_assets", "shot_assets", "voice_assets")


def upgrade():
    for table in ATTRIBUTION_TABLES:
        for name, length, default in (("generation_origin", 32, "business"), ("agent_name", 80, ""), ("agent_run_id", 160, "")):
            op.add_column(table, sa.Column(name, sa.String(length), nullable=False, server_default=default))
            op.create_index(f"ix_{table}_{name}", table, [name])
        # Historic unlinked calls cannot be reliably classified from missing headers.
        op.execute(sa.text(f"UPDATE {table} SET generation_origin = 'legacy_unknown'"))
        for name in ("generation_origin", "agent_name", "agent_run_id"):
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {name} = (SELECT g.{name} FROM generation_jobs g WHERE g.id = {table}.generation_job_id) WHERE EXISTS (SELECT 1 FROM generation_jobs g WHERE g.id = {table}.generation_job_id)"
                )
            )
    for table in ASSET_TABLES:
        for name in ("generation_job_id", "is_current"):
            op.create_index(f"ix_{table}_{name}", table, [name])


def downgrade():
    for table in reversed(ASSET_TABLES):
        for name in ("generation_job_id", "is_current"):
            op.drop_index(f"ix_{table}_{name}", table_name=table)
    for table in reversed(ATTRIBUTION_TABLES):
        for name in ("agent_run_id", "agent_name", "generation_origin"):
            op.drop_index(f"ix_{table}_{name}", table_name=table)
            op.drop_column(table, name)
