import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_fresh_release_and_replay_preserve_operator_changes(tmp_path):
    database = tmp_path / "catalog.db"
    env = {**os.environ, "DATABASE_URL": "sqlite+aiosqlite:///" + str(database), "PYTHONPATH": str(ROOT / "public-api")}

    def run(*args):
        subprocess.run([sys.executable, *args], cwd=ROOT, env=env, check=True, capture_output=True)

    run("-m", "alembic", "upgrade", "head")
    run("scripts/seed.py")
    check = subprocess.run([sys.executable, "scripts/release-readiness.py"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert check.returncode == 1
    readiness = json.loads(check.stdout)
    assert readiness["generation_ready"] is False and readiness["enabled_routes"] == 0
    assert readiness["routes_with_quotes"] == 39
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from models").fetchone()[0] == 20
        assert db.execute("select count(*) from model_routes").fetchone()[0] == 39
        assert db.execute("select count(*) from model_routes where enabled=1").fetchone()[0] == 0
        assert db.execute("select count(*) from pricing_rules").fetchone()[0] == 0
        pro = db.execute("select provider_model,pricing from model_routes where id='toapis--seedream-5.0-pro'").fetchone()
        assert pro[0] == "doubao-seedream-5-0-pro"
        rules = json.loads(pro[1])["estimate_rules"]
        assert [(r["conditions"]["resolution"], r["rates"][0]["cny"]) for r in rules] == [("1K", "0.29995"), ("2K", "0.59990")]
        rows = db.execute("select pricing from model_routes").fetchall()
        assert all(json.loads(p)["estimate_rules"] for (p,) in rows)
        db.execute(
            "update model_routes set pricing=?,deleted_at='2026-09-22' where id='toapis--gpt-image-2'",
            (json.dumps({"operator": "preserve"}),),
        )
        db.commit()
    run("-m", "alembic", "upgrade", "head")
    run("scripts/seed.py")
    with sqlite3.connect(database) as db:
        row = db.execute("select pricing,deleted_at from model_routes where id='toapis--gpt-image-2'").fetchone()
        assert json.loads(row[0]) == {"operator": "preserve"} and row[1]
        assert db.execute('select count(*) from audits where id="catalog-release-20260922"').fetchone()[0] == 1


def test_price_import_requires_explicit_environment(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "PYTHONPATH"}}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/publish-estimate-rates.py"), "--snapshot-dir", str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "Set the target DATABASE_URL explicitly" in result.stderr


def test_password_migration_preserves_existing_accounts(tmp_path):
    database = tmp_path / "password.db"
    env = {**os.environ, "DATABASE_URL": "sqlite+aiosqlite:///" + str(database)}

    def migrate(revision):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=ROOT, env=env, check=True, capture_output=True)

    migrate("0006")
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO portal_users (id, username, password_hash, enabled, created_at, updated_at) VALUES ('legacy', 'legacy@star-net.cn', 'existing-hash', 1, '2026-09-22', '2026-09-22')"
        )
    migrate("head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT password_hash, password_changed_at FROM portal_users WHERE id='legacy'").fetchone() == (
            "existing-hash",
            None,
        )
        db.execute("UPDATE portal_users SET password_changed_at='2026-09-23' WHERE id='legacy'")
    migrate("head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT password_changed_at FROM portal_users WHERE id='legacy'").fetchone()[0] == "2026-09-23"


def test_account_limit_migration_preserves_existing_key_allowances(tmp_path):
    database = tmp_path / "accounts.db"
    env = {**os.environ, "DATABASE_URL": "sqlite+aiosqlite:///" + str(database)}

    def migrate(revision):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=ROOT, env=env, check=True, capture_output=True)

    migrate("0007")
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO portal_users (id, username, password_hash, enabled, created_at, updated_at) VALUES ('owner', 'owner@star-net.cn', 'preserved', 1, '2026-09-22', '2026-09-22')"
        )
        for ident, points, deleted in (("a", 10, None), ("b", 20, None), ("retired", 100, "2026-09-22")):
            db.execute(
                "INSERT INTO clients (id, name, key_hash, key_prefix, enabled, allowed_models, concurrency, require_agent, user_id, monthly_points, created_at, updated_at, deleted_at) VALUES (?, ?, ?, 'test', 1, '[]', 1, 0, 'owner', ?, '2026-09-22', '2026-09-22', ?)",
                (ident, ident, ident, points, deleted),
            )
    migrate("head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT monthly_points, password_hash FROM portal_users WHERE id='owner'").fetchone() == (30, "preserved")
        db.execute("UPDATE portal_users SET monthly_points=15 WHERE id='owner'")
    migrate("head")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT monthly_points FROM portal_users WHERE id='owner'").fetchone()[0] == 15
