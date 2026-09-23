"""Exercise the real Alembic chain using only newly created tmp_path databases."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
REVISION = "0005"
PREVIOUS = "0004"
CREATED = datetime(2020, 1, 1)
UPDATED = datetime(2021, 2, 3)
DELETED = datetime(2022, 3, 4)
KEPT = (
    "yinghe",
    "yseeai",
    "toapis",
    "runninghub",
    "optimizer-gemini",
    "optimizer-minimax",
    "happyhorse",
    "vidu",
    "kling",
    "flux-api",
    "ppio-custom",
    "bfl-custom",
)


def alembic(database, *args):
    # Never inherit a business DATABASE_URL, including from the service fixture.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def snapshot(connection, name):
    return {row["id"]: dict(row) for row in connection.execute(sa.text(f'SELECT * FROM "{name}"')).mappings()}


def insert(connection, metadata, table_name, row_id, **values):
    connection.execute(
        metadata.tables[table_name]
        .insert()
        .values(id=row_id, created_at=CREATED, updated_at=UPDATED, deleted_at=values.pop("deleted_at", None), **values)
    )


@pytest.fixture
def legacy_db(tmp_path):
    database = tmp_path / "retirement.db"
    assert not database.exists()
    alembic(database, "upgrade", PREVIOUS)
    engine = sa.create_engine(sa.URL.create("sqlite", database=str(database)))
    metadata = sa.MetaData()
    try:
        metadata.reflect(engine)
        yield database, engine, metadata
    finally:
        engine.dispose()


def test_retire_exact_channels_without_rewriting_history(legacy_db):
    database, engine, metadata = legacy_db
    targets = {name: set() for name in ("channel_accounts", "models", "model_routes", "pricing_rules")}
    with engine.begin() as connection:
        for channel in ("ppio", "bfl", *KEPT):
            for state in ("live", "disabled", "archived"):
                row_id = f"{channel}-{state}"
                deleted = DELETED if state == "archived" else None
                enabled = state != "disabled"
                insert(
                    connection,
                    metadata,
                    "channel_accounts",
                    row_id,
                    channel=channel,
                    name=row_id,
                    key_env="FAKE_TEST_KEY",
                    currency="USD",
                    usd_cny=6.9,
                    points_currency="CNY",
                    snapshot={"balance": 12.5},
                    next_check_at=CREATED,
                    deleted_at=deleted,
                )
                insert(
                    connection,
                    metadata,
                    "models",
                    row_id,
                    channel=channel,
                    provider_model=f"model-{row_id}",
                    kind="video",
                    protocol="video",
                    enabled=enabled,
                    concurrency=3,
                    capabilities={"duration": [5, 10]},
                    deleted_at=deleted,
                )
                insert(
                    connection,
                    metadata,
                    "model_routes",
                    row_id,
                    model_id=row_id,
                    supplier=channel,
                    channel=channel,
                    provider_model=f"model-{row_id}",
                    protocol="video",
                    enabled=enabled,
                    priority=10,
                    concurrency=2,
                    verification="verified",
                    capabilities={"duration": [5, 10]},
                    pricing={"unit_price": 0.125},
                    deleted_at=deleted,
                )
                if channel in ("ppio", "bfl") and deleted is None:
                    for name in ("channel_accounts", "models", "model_routes"):
                        targets[name].add(row_id)
                for price_state in ("live", "archived"):
                    price_id = f"price-{row_id}-{price_state}"
                    insert(
                        connection,
                        metadata,
                        "pricing_rules",
                        price_id,
                        model_id=row_id,
                        config={"rate": 1.25},
                        actor="fixture",
                        deleted_at=DELETED if price_state == "archived" else None,
                    )
                    if channel in ("ppio", "bfl") and price_state == "live":
                        targets["pricing_rules"].add(price_id)

        # Routes are channel-specific, not a reason to retire all routes of a model.
        for row_id, channel, model_id in (("retired-route", "ppio", "yinghe-live"), ("retained-route", "yinghe", "ppio-live")):
            insert(
                connection,
                metadata,
                "model_routes",
                row_id,
                model_id=model_id,
                supplier=channel,
                channel=channel,
                provider_model="shared",
                protocol="video",
                enabled=True,
                priority=20,
                concurrency=1,
                verification="verified",
                capabilities={},
                pricing={"unit_price": 1},
            )
        targets["model_routes"].add("retired-route")

        insert(
            connection,
            metadata,
            "clients",
            "client",
            name="Fixture client",
            key_hash="fake-hash",
            key_prefix="test",
            enabled=True,
            allowed_models=["ppio-live", "bfl-live"],
            concurrency=1,
            require_agent=True,
            billing_enabled=True,
            monthly_balance=125,
            extra_balance=25,
        )
        for channel in ("ppio", "bfl"):
            insert(connection, metadata, "pricing_rules", channel, model_id=f"{channel}-live", config={"rate": 1.25}, actor="fixture")
            targets["pricing_rules"].add(channel)
            for status in ("succeeded", "running", "queued", "manual_review", "failed"):
                job = f"{channel}-{status}"
                insert(
                    connection,
                    metadata,
                    "jobs",
                    job,
                    client_id="client",
                    user_id="fixture-user",
                    model_id=f"{channel}-live",
                    route_id=f"{channel}-live",
                    routing_snapshot={"channel": channel, "provider_model": "legacy"},
                    kind="video",
                    channel=channel,
                    protocol="video",
                    status=status,
                    payload={"prompt": "historical only"},
                    request_hash=f"hash-{job}",
                    idempotency_key=job,
                    provider_id=f"upstream-{job}",
                    provider_response={"id": f"upstream-{job}"},
                    result={"media": [{"url": "https://tos.example/old.mp4"}]},
                    usage={"output_seconds": 5},
                    origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id="historical-run",
                    test_run_id="historical-run",
                    attempts=1,
                    charged_points=6.25,
                    billing_status="charged",
                    pricing_snapshot={"rule_id": channel, "unit_price": 1.25},
                )
                insert(
                    connection,
                    metadata,
                    "credit_ledger",
                    job,
                    client_id="client",
                    user_id="fixture-user",
                    job_id=job,
                    operation_id=job,
                    kind="charge",
                    points=-6.25,
                    monthly_after=125,
                    extra_after=25,
                    actor="fixture",
                    reason="historical charge",
                    evidence={"provider": channel, "usage": {"output_seconds": 5}},
                )
                insert(connection, metadata, "audits", job, actor="fixture", action="charge", target=job, detail={"points": 6.25})
        before = {name: snapshot(connection, name) for name in metadata.tables if name != "alembic_version"}

    alembic(database, "upgrade", REVISION)
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
        after = {name: snapshot(connection, name) for name in before}
        for name, rows in before.items():
            assert after[name].keys() == rows.keys(), name
            for row_id, old in rows.items():
                if row_id not in targets.get(name, set()):
                    assert after[name][row_id] == old, (name, row_id)
                    continue
                stamp = after[name][row_id]["deleted_at"]
                assert stamp is not None and stamp > str(DELETED)
                expected = {**old, "updated_at": stamp, "deleted_at": stamp}
                if name in ("models", "model_routes"):
                    expected["enabled"] = 0
                assert after[name][row_id] == expected, (name, row_id)

    # An ordinary repeated deployment must not change retirement timestamps.
    alembic(database, "upgrade", REVISION)
    with engine.connect() as connection:
        assert {name: snapshot(connection, name) for name in before} == after


def test_upgrade_without_retired_rows_preserves_seeded_channels(legacy_db):
    database, engine, metadata = legacy_db
    with engine.connect() as connection:
        before = {name: snapshot(connection, name) for name in metadata.tables if name != "alembic_version"}
        assert {row["channel"] for row in before["channel_accounts"].values()} == {
            "yinghe",
            "yseeai",
            "toapis",
            "runninghub",
            "optimizer-gemini",
            "optimizer-minimax",
        }
    alembic(database, "upgrade", REVISION)
    with engine.connect() as connection:
        assert {name: snapshot(connection, name) for name in before} == before
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION


def test_single_head_and_unbroken_history():
    directory = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert directory.get_heads() == ["0008"]
    assert directory.get_revision(REVISION).down_revision == PREVIOUS
    assert {revision.revision for revision in directory.walk_revisions()} == {
        "0001",
        "0002",
        "0003",
        PREVIOUS,
        REVISION,
        "0006",
        "0007",
        "0008",
    }


def test_fresh_database_full_upgrade(tmp_path):
    database = tmp_path / "full-chain.db"
    assert not database.exists()
    alembic(database, "upgrade", REVISION)
    engine = sa.create_engine(sa.URL.create("sqlite", database=str(database)))
    try:
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION
            assert {"channel_accounts", "models", "model_routes", "jobs", "credit_ledger"} <= set(sa.inspect(connection).get_table_names())
            assert not connection.execute(
                sa.text("SELECT id FROM channel_accounts WHERE channel IN ('ppio', 'bfl') AND deleted_at IS NULL")
            ).all()
    finally:
        engine.dispose()
