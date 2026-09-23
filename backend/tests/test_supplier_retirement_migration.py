"""Retirement regression tests use isolated SQLite schemas, not a full PostgreSQL upgrade."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.models import Base

ROOT = Path(__file__).resolve().parents[1]
REVISION = "b3f7a1c5e902"
PREVIOUS = "a6c9e2f4b801"
CREATED = datetime(2020, 1, 1)
UPDATED = datetime(2021, 2, 3)
DELETED = datetime(2022, 3, 4)
RETIRED_CODES = ("doubao-seedance-2.0-ppio", "minimax-h3-ppio", "flux-3-video")
KEPT = ("yinghe", "yseeai", "toapis", "runninghub", "happyhorse", "vidu", "kling", "flux-api", "ppio-custom", "bfl-custom")


def scripts():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def snapshot(connection, name):
    # Raw rows catch changes to all columns, including JSON, money and timestamps.
    return {row["id"]: dict(row) for row in connection.execute(sa.text(f'SELECT * FROM "{name}"')).mappings()}


def insert(connection, table_name, row_id, **values):
    connection.execute(Base.metadata.tables[table_name].insert().values(id=row_id, created_at=CREATED, updated_at=UPDATED, **values))


@pytest.fixture
def legacy_db(tmp_path):
    engine = sa.create_engine(sa.URL.create("sqlite", database=str(tmp_path / "retirement.db")))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            Base.metadata.create_all(connection)
            operations = Operations(MigrationContext.configure(connection))
            operations.add_column("digital_humans", sa.Column("ppio_asset_avatar_url", sa.Text(), nullable=True))
            yield connection
    finally:
        engine.dispose()


def upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
        scripts().get_revision(REVISION).module.upgrade()


@pytest.mark.parametrize("providers_already_deleted", [False, True])
def test_retire_exact_configuration_and_preserve_history(legacy_db, providers_already_deleted):
    connection = legacy_db
    targets = {name: set() for name in ("ai_providers", "ai_models", "model_price_versions", "video_pricing_rules")}
    for provider in ("ppio", "bfl", *KEPT):
        retired = provider in ("ppio", "bfl")
        deleted = DELETED if retired and providers_already_deleted else None
        insert(connection, "ai_providers", provider, code=provider, name=provider, deleted_at=deleted)
        if retired and deleted is None:
            targets["ai_providers"].add(provider)

    model_cases = [(f"custom-{provider}", provider, provider in ("ppio", "bfl")) for provider in ("ppio", "bfl", *KEPT)]
    # Exact legacy codes must retire even when registered under a retained provider.
    model_cases += [(code, "yinghe", True) for code in RETIRED_CODES]
    model_cases += [("flux-3-video-preview", "yinghe", False), ("minimax-h3-ppio-preview", "yinghe", False)]
    model_cases += [("archived-ppio", "ppio", True), ("archived-bfl", "bfl", True)]
    for code, provider, retired in model_cases:
        deleted = DELETED if code.startswith("archived-") else None
        insert(connection, "ai_models", code, provider_id=provider, code=code, name=code, modality="video", provider_model_id=code, is_default=True, deleted_at=deleted)
        if retired and deleted is None:
            targets["ai_models"].add(code)
        # Live prices on already-deleted models must also retire; old versions stay intact.
        for suffix, price_deleted in (("live", None), ("archived", DELETED)):
            price_id = f"{code}-{suffix}"
            insert(connection, "model_price_versions", price_id, model_id=code, unit_price=1.25, deleted_at=price_deleted)
            if retired and price_deleted is None:
                targets["model_price_versions"].add(price_id)

    rule_cases = [(provider, "custom-model", provider in ("ppio", "bfl")) for provider in ("ppio", "bfl", *KEPT)]
    rule_cases += [("yinghe", code, True) for code in RETIRED_CODES]
    rule_cases += [("yinghe", "flux-3-video-preview", False)]
    for index, (provider, model, retired) in enumerate(rule_cases):
        for suffix, deleted in (("live", None), ("archived", DELETED)):
            rule_id = f"rule-{index}-{suffix}"
            insert(
                connection,
                "video_pricing_rules",
                rule_id,
                provider=provider,
                model=model,
                usage_type="seconds",
                unit_size=1,
                unit_price=0.125,
                effective_at=CREATED,
                deleted_at=deleted,
            )
            if retired and deleted is None:
                targets["video_pricing_rules"].add(rule_id)

    for provider, rule_index in (("ppio", 0), ("bfl", 1)):
        for status in ("succeeded", "running", "failed"):
            job = f"{provider}-{status}"
            insert(
                connection,
                "generation_jobs",
                job,
                kind="video",
                provider=provider,
                provider_task_id=f"upstream-{job}",
                status=status,
                request={"model": f"custom-{provider}"},
                result={"url": "https://tos.example/old.mp4"},
            )
            insert(
                connection,
                "token_usage_records",
                job,
                generation_job_id=job,
                operation="video",
                provider=provider,
                model=f"custom-{provider}",
                total_tokens=123,
                raw_usage={"output_seconds": 5},
            )
            insert(
                connection,
                "video_billing_records",
                job,
                generation_job_id=job,
                pricing_rule_id=f"rule-{rule_index}-live",
                provider=provider,
                model=f"custom-{provider}",
                generation_status=status,
                billing_status="priced",
                amount=0.625,
                raw_usage={"output_seconds": 5},
            )
    insert(
        connection,
        "digital_humans",
        "human",
        name="Private fixture",
        avatar_url="https://tos.example/original.png",
        avatar_thumbnail_url="https://tos.example/thumbnail.png",
        asset_avatar_url="asset://retained",
    )
    connection.execute(sa.text("UPDATE digital_humans SET ppio_asset_avatar_url = 'asset://retired' WHERE id = 'human'"))

    history = ("generation_jobs", "token_usage_records", "video_billing_records")
    before = {name: snapshot(connection, name) for name in (*targets, *history, "digital_humans")}
    upgrade(connection)

    for name, changed_ids in targets.items():
        after = snapshot(connection, name)
        assert after.keys() == before[name].keys(), name  # Soft delete, never drop rows.
        for row_id, old in before[name].items():
            if row_id not in changed_ids:
                assert after[row_id] == old, (name, row_id)
                continue
            stamp = after[row_id]["deleted_at"]
            assert stamp is not None and stamp > str(DELETED)
            expected = {**old, "updated_at": stamp, "deleted_at": stamp}
            if name != "model_price_versions":
                expected["status"] = "disabled"
            if name == "ai_models":
                expected.update(user_visible=0, is_default=0)
            assert after[row_id] == expected, (name, row_id)
    for name in history:
        assert snapshot(connection, name) == before[name], name
    assert "ppio_asset_avatar_url" in {column["name"] for column in sa.inspect(connection).get_columns("digital_humans")}
    assert snapshot(connection, "digital_humans") == before["digital_humans"]
    assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_upgrade_without_legacy_rows_preserves_rolling_compatibility(legacy_db):
    upgrade(legacy_db)
    assert "ppio_asset_avatar_url" in {column["name"] for column in sa.inspect(legacy_db).get_columns("digital_humans")}
    for name in ("ai_providers", "ai_models", "model_price_versions", "video_pricing_rules"):
        assert snapshot(legacy_db, name) == {}


def test_single_head_and_unbroken_history():
    directory = scripts()
    assert len(directory.get_heads()) == 1
    assert directory.get_revision(REVISION).down_revision == PREVIOUS
    revisions = {revision.revision for revision in directory.walk_revisions()}
    assert {"0001_initial", PREVIOUS, REVISION, "c8f2a6d1e409", "a9d4e7f2c601", "b4e8c2d7a913"} <= revisions


def test_fresh_database_full_upgrade(tmp_path):
    database = tmp_path / "full-chain.db"
    assert not database.exists()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = result.stdout + result.stderr
    if result.returncode and (
        "d668fb1d8c09_multi_user_persistence_and_soft_delete.py" in output
        and 'op.drop_constraint(op.f("chat_messages_session_id_fkey")' in output
        and "NotImplementedError: No support for ALTER of constraints in SQLite dialect" in output
    ):
        pytest.xfail("Full chain blocked at d668fb1d8c09: SQLite cannot ALTER/drop chat_messages FK; PostgreSQL still required")
    assert result.returncode == 0, output
    engine = sa.create_engine(sa.URL.create("sqlite", database=str(database)))
    try:
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == scripts().get_current_head()
            assert "ppio_asset_avatar_url" not in {column["name"] for column in sa.inspect(connection).get_columns("digital_humans")}
    finally:
        engine.dispose()
