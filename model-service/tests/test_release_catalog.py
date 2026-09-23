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
    assert readiness["routes_with_quotes"] == 38
    with sqlite3.connect(database) as db:
        assert db.execute("select count(*) from models").fetchone()[0] == 19
        assert db.execute("select count(*) from model_routes").fetchone()[0] == 38
        assert db.execute("select count(*) from model_routes where enabled=1").fetchone()[0] == 0
        assert db.execute("select count(*) from pricing_rules").fetchone()[0] == 0
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
