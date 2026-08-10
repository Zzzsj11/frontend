"""material export progress and job isolation

Revision ID: 7a31c9de204f
Revises: 2d57abce7091
"""

import sqlalchemy as sa
from alembic import op

revision = "7a31c9de204f"
down_revision = "2d57abce7091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("material_exports", sa.Column("generation_job_id", sa.String(length=80), nullable=True))
    op.add_column("material_exports", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("material_exports", sa.Column("stage", sa.String(length=120), nullable=False, server_default="等待导出"))
    op.add_column("material_exports", sa.Column("total_assets", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("material_exports", sa.Column("processed_assets", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("material_exports", sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("material_exports", sa.Column("processed_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("material_exports", sa.Column("archive_size", sa.BigInteger(), nullable=True))
    op.add_column("material_exports", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("material_exports", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_material_exports_generation_job_id", "material_exports", "generation_jobs", ["generation_job_id"], ["id"])
    op.create_index(op.f("ix_material_exports_generation_job_id"), "material_exports", ["generation_job_id"])
    op.create_index(op.f("ix_material_exports_status"), "material_exports", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_material_exports_status"), table_name="material_exports")
    op.drop_index(op.f("ix_material_exports_generation_job_id"), table_name="material_exports")
    op.drop_constraint("fk_material_exports_generation_job_id", "material_exports", type_="foreignkey")
    for column in (
        "finished_at",
        "started_at",
        "archive_size",
        "processed_bytes",
        "total_bytes",
        "processed_assets",
        "total_assets",
        "stage",
        "progress",
        "generation_job_id",
    ):
        op.drop_column("material_exports", column)
