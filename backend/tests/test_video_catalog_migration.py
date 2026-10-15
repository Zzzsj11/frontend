import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from test_supplier_retirement_migration import insert, scripts, snapshot
from test_supplier_retirement_migration import legacy_db as legacy_db


def test_video_catalog_migration_preserves_financial_and_media_history(legacy_db):
    db = legacy_db
    insert(db, "ai_providers", "all-in-one", code="all-in-one", name="all in one")
    insert(db, "ai_providers", "yinghe", code="yinghe", name="英和")
    insert(db, "ai_models", "old", provider_id="yinghe", code="minimax-h3", name="H3 英和", modality="video", provider_model_id="MiniMax-H3", is_default=True)
    insert(db, "users", "owner", username="owner", password_hash="synthetic")
    insert(db, "projects", "project", user_id="owner", name="migration")
    insert(
        db,
        "project_tasks",
        "task",
        project_id="project",
        title="legacy",
        storyboard_config={"video_model": "minimax-h3", "ratio": "16:9", "resolution": "720p", "unrelated": "preserved"},
    )
    insert(
        db,
        "storyboard_lines",
        "line",
        project_task_id="task",
        source="manual",
        shot_options={"videoModel": "minimax-h3", "duration": 5, "resolution": "720p", "ratio": "16:9"},
        planned_duration=5,
    )
    insert(db, "shot_assets", "asset", storyboard_line_id="line", video_url="https://tos.test/historical.mp4", cover_url="", model_code="minimax-h3", duration=5)
    insert(db, "generation_jobs", "job", user_id="owner", kind="video", status="succeeded", request={"model": "minimax-h3"}, result={"videoUrl": "https://tos.test/historical.mp4"})
    insert(
        db,
        "token_usage_records",
        "usage",
        user_id="owner",
        operation="generation_video",
        provider="yinghe",
        model="minimax-h3",
        raw_usage={"platformBilling": {"points": "123.45"}},
    )
    history = {name: snapshot(db, name) for name in ["generation_jobs", "token_usage_records", "shot_assets"]}
    with Operations.context(MigrationContext.configure(db)):
        scripts().get_revision("8f2c6d4a1b70").module.upgrade()
    for name, expected in history.items():
        assert snapshot(db, name) == expected
    old = db.execute(sa.text("select status,deleted_at from ai_models where id='old'")).mappings().one()
    assert old["status"] == "inactive" and old["deleted_at"] is not None
    active = db.execute(sa.text("select count(*) from ai_models where modality='video' and status='active' and deleted_at is null")).scalar_one()
    assert active == 12
    task = sa.Table("project_tasks", sa.MetaData(), autoload_with=db)
    config = db.execute(sa.select(task.c.storyboard_config).where(task.c.id == "task")).scalar_one()
    assert config["video_model"] == "minimax-h3-all-in-one" and config["unrelated"] == "preserved"
    assert snapshot(db, "storyboard_lines")["line"]["planned_duration"] == 5
