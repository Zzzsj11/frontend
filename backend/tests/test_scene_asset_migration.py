"""Upgrade an existing selection set, including a write already in flight on PostgreSQL."""

import asyncio
import importlib
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import ProjectModel, ProjectTaskModel, SceneAssetModel, StoryboardLineModel, UserModel, utcnow

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = importlib.import_module("migrations.versions.eb617531ca10_one_current_scene_asset")


def test_sqlite_upgrade_cleans_only_live_duplicate_selections():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE scene_assets(id TEXT PRIMARY KEY, storyboard_line_id TEXT, is_current BOOLEAN, created_at TEXT, updated_at TEXT, deleted_at TEXT)")
        db.exec_driver_sql("""INSERT INTO scene_assets VALUES
            ('first','line',1,'2026-01-01','2026-01-01',NULL),
            ('latest','line',1,'2026-01-02','2026-01-02',NULL),
            ('gone','line',1,'2026-01-03','2026-01-03','2026-01-04')""")
        with Operations.context(MigrationContext.configure(db)):
            MIGRATION.upgrade()
        assert db.exec_driver_sql("SELECT id,is_current FROM scene_assets ORDER BY id").all() == [("first", 0), ("gone", 1), ("latest", 1)]
        with pytest.raises(sa.exc.IntegrityError):
            db.exec_driver_sql("UPDATE scene_assets SET is_current=1 WHERE id='first'")
        with Operations.context(MigrationContext.configure(db)):
            MIGRATION.downgrade()
        assert db.exec_driver_sql("SELECT count(*) FROM scene_assets").scalar_one() == 3
    engine.dispose()


@pytest.mark.skipif(os.getenv("MV_RUN_DISPOSABLE_SCENE_MIGRATION") != "1", reason="uses an exclusive temporary PostgreSQL container")
def test_postgres_upgrade_waits_for_old_writer_before_deduplication():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import local_runtime
    finally:
        sys.path.pop(0)
    with local_runtime.dependencies(redis=False) as env:
        command = [local_runtime.PYTHON, "-m", "alembic", "upgrade"]
        local_runtime.run([*command, MIGRATION.down_revision], cwd=ROOT / "backend", env=env)
        asyncio.run(verify_postgres_upgrade(env, command))


async def verify_postgres_upgrade(env, command):
    engine = create_async_engine(env["DATABASE_URL"])
    now = utcnow()

    def image(asset_id, timestamp, **fields):
        return dict(id=asset_id, storyboard_line_id="scene-test-line", image_url="synthetic", prompt="", is_current=True, created_at=timestamp, updated_at=timestamp, **fields)

    try:
        async with async_sessionmaker(engine).begin() as db:
            db.add(UserModel(id="scene-test-user", username="scene-test-user", password_hash="synthetic"))
            await db.flush()
            db.add(ProjectModel(id="scene-test-project", user_id="scene-test-user", name="synthetic"))
            await db.flush()
            db.add(ProjectTaskModel(id="scene-test-task", project_id="scene-test-project", title="synthetic"))
            await db.flush()
            db.add(StoryboardLineModel(id="scene-test-line", project_task_id="scene-test-task"))
            await db.flush()
            db.add(SceneAssetModel(**image("first", now)))
            db.add(SceneAssetModel(**image("gone", now + timedelta(seconds=2), deleted_at=now)))

        async with engine.connect() as writer, engine.connect() as observer:
            await writer.execute(sa.insert(SceneAssetModel).values(**image("inflight", now + timedelta(seconds=1))))
            process = await asyncio.create_subprocess_exec(*command, MIGRATION.revision, cwd=ROOT / "backend", env=env)
            try:
                # Inspect locks without taking a scene_assets table lock ourselves.
                async with asyncio.timeout(10):
                    while not await observer.scalar(
                        sa.text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE relation='scene_assets'::regclass AND mode='ShareRowExclusiveLock' AND NOT granted)")
                    ):
                        await asyncio.sleep(0.02)
                assert await observer.scalar(sa.text("SELECT count(*) FROM scene_assets")) == 2
                await observer.commit()
                await writer.commit()
                assert await asyncio.wait_for(process.wait(), 15) == 0
            finally:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
        async with engine.connect() as db:
            assert (await db.execute(sa.text("SELECT id,is_current FROM scene_assets ORDER BY id"))).all() == [("first", False), ("gone", True), ("inflight", True)]
            assert await db.scalar(sa.text("SELECT version_num FROM alembic_version")) == MIGRATION.revision
            with pytest.raises(sa.exc.IntegrityError):
                await db.execute(sa.update(SceneAssetModel).where(SceneAssetModel.id == "first").values(is_current=True))
    finally:
        await engine.dispose()
