"""Exercise the restore entry points using isolated CLI fixtures and an opt-in real temporary PostgreSQL."""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def backup_host(tmp_path):
    host = tmp_path / "host"
    scripts = host / "scripts"
    scripts.mkdir(parents=True)
    for name in ["restore-postgres.sh", "verify-backup.sh"]:
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        """#!/bin/sh
echo "$*" >> "$CALLS"
if [ -n "${SEEN_RELEASE:-}" ]; then echo "${RELEASE_VERSION:-}" >> "$SEEN_RELEASE"; fi
case "$*" in
    *createdb*) [ "$FAILURE" != create ] ;;
    *dropdb*) exit 0 ;;
    *pg_restore*) cat >> "$RESTORED"; [ "$FAILURE" != restore ] ;;
    *"count(*)"*) echo 3 ;;
    *"select version_num"*) echo test-revision ;;
    *) exit 19 ;;
esac
"""
    )
    docker.chmod(0o755)
    dump = tmp_path / "backup with spaces.dump"
    dump.write_bytes(b"synthetic fixture")
    sign(dump)
    return (
        scripts,
        dump,
        {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAILURE": "",
            "CALLS": str(tmp_path / "calls"),
            "RESTORED": str(tmp_path / "restored"),
            "CONFIRM_RESTORE": "RESTORE",
        },
    )


def sign(dump):
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    Path(f"{dump}.sha256").write_text(f"{digest}  {dump.name}\n")


def run_backup(scripts, dump, env, command="verify-backup.sh"):
    return subprocess.run([str(scripts / command), dump.name], cwd=dump.parent, env=env, capture_output=True, text=True, timeout=40)


@pytest.mark.parametrize("command", ["verify-backup.sh", "restore-postgres.sh"])
def test_invalid_checksum_is_rejected_before_connecting(backup_host, command):
    scripts, dump, env = backup_host
    dump.write_bytes(b"damaged")
    result = run_backup(scripts, dump, env, command)
    assert result.returncode and "checksum mismatch" in result.stderr
    assert not Path(env["CALLS"]).exists()


def test_precheck_uses_relative_path_and_restores_target_in_one_transaction(backup_host):
    scripts, dump, env = backup_host
    result = run_backup(scripts, dump, env, "restore-postgres.sh")
    assert result.returncode == 0, result.stderr
    events = Path(env["CALLS"]).read_text().splitlines()
    target = [i for i, e in enumerate(events) if "pg_restore" in e and "$POSTGRES_DB" in e]
    assert len(target) == 1 and " --clean --if-exists --exit-on-error --single-transaction" in events[target[0]]
    assert next(i for i, e in enumerate(events) if "select version_num" in e) < next(i for i, e in enumerate(events) if "dropdb" in e) < target[0]
    assert Path(env["RESTORED"]).read_bytes() == dump.read_bytes() * 2


@pytest.mark.parametrize("current", [None, "ledger-release"])
def test_recovery_picks_release_from_ledger_or_fresh_server_override(backup_host, current):
    scripts, dump, env = backup_host
    host = scripts.parent
    (host / ".env.production").touch()
    (host / ".deployment").mkdir()
    if current:
        (host / ".deployment/info.json").write_text('{"version":"ledger-release","previous":"older"}')
        (host / ".deployed-version").write_text("stale")
    marker = host / "seen-release"
    result = run_backup(scripts, dump, {**env, "RELEASE_VERSION": "fresh-server", "SEEN_RELEASE": str(marker)})
    assert result.returncode == 0, result.stderr
    assert set(marker.read_text().splitlines()) == {current or "fresh-server"}


@pytest.mark.parametrize("failure", ["create", "restore"])
def test_verification_failure_only_cleans_its_own_database(backup_host, failure):
    scripts, dump, env = backup_host
    result = run_backup(scripts, dump, {**env, "FAILURE": failure}, "restore-postgres.sh")
    assert result.returncode
    events = Path(env["CALLS"]).read_text().splitlines()
    assert not any("pg_restore" in e and "$POSTGRES_DB" in e for e in events)
    assert any("dropdb" in e for e in events) == (failure == "restore")


def test_concurrent_verification_uses_distinct_databases(backup_host):
    scripts, dump, env = backup_host
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(run_backup, scripts, dump, env) for _ in range(2)]
        assert all(task.result().returncode == 0 for task in tasks)
    events = Path(env["CALLS"]).read_text().splitlines()
    database = re.compile(r"mvagent_restore_verify_[0-9a-f]{32}")
    owned = {database.search(e)[0] for e in events if "createdb" in e}
    dropped = {database.search(e)[0] for e in events if "dropdb" in e}
    assert len(owned) == 2 and owned == dropped


@pytest.mark.skipif(os.getenv("MV_RUN_DISPOSABLE_RESTORE") != "1", reason="requires an exclusive temporary PostgreSQL container")
def test_real_restore_rolls_back_changes_in_exclusive_postgres(backup_host):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import local_runtime
    finally:
        sys.path.pop(0)
    scripts, dump, env = backup_host
    with local_runtime.dependencies(redis=False) as private:
        project = urlsplit(private["DATABASE_URL"]).password.removeprefix("synthetic-")
        assert re.fullmatch(r"mv-local-[a-f0-9]{12}", project)
        compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "docker-compose.yml"), "-f", str(ROOT / "docker-compose.local-build.yml")]
        # Route the restore script's Compose calls exclusively into the new project's container.
        wrapper = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
        wrapper.write_text(
            """#!/bin/sh
set -eu
while [ "$#" -gt 0 ] && [ "$1" != exec ]; do shift; done
[ "$#" -gt 0 ]
exec "$REAL_DOCKER" compose -p "$PRIVATE_PROJECT" -f "$COMPOSE_BASE" -f "$COMPOSE_LOCAL" "$@"
"""
        )
        real_docker = shutil.which("docker")
        env.update(REAL_DOCKER=real_docker, PRIVATE_PROJECT=project, COMPOSE_BASE=compose[5], COMPOSE_LOCAL=compose[7])
        pg = [*compose, "exec", "-T", "postgres"]

        def sql(statement):
            return subprocess.check_output([*pg, "psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-U", "mv_local_proof", "-d", "mv_local_proof", "-c", statement], text=True).strip()

        sql(
            "CREATE TABLE a_guard(v int); CREATE TABLE z_sentinel(v int); CREATE TABLE users(id int); CREATE TABLE alembic_version(version_num text); INSERT INTO alembic_version VALUES ('fixture'); INSERT INTO z_sentinel VALUES (1)"
        )
        dump.write_bytes(subprocess.check_output([*pg, "pg_dump", "-Fc", "-U", "mv_local_proof", "-d", "mv_local_proof"]))
        sign(dump)
        sql("UPDATE z_sentinel SET v=42; CREATE VIEW hold_guard AS SELECT * FROM a_guard")
        result = run_backup(scripts, dump, env, "restore-postgres.sh")
        assert result.returncode and "a_guard" in result.stderr and "hold_guard" in result.stderr, result
        assert "[PASS]" in result.stdout
        assert sql("SELECT v FROM z_sentinel") == "42"
        assert sql("SELECT count(*) FROM pg_database WHERE datname LIKE 'mvagent_restore_verify_%'") == "0"
        sql("DROP VIEW hold_guard")
        success = run_backup(scripts, dump, env, "restore-postgres.sh")
        assert success.returncode == 0, success.stderr
        assert sql("SELECT v FROM z_sentinel") == "1"
