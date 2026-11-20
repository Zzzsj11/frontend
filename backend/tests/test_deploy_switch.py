"""Exercise the actual Nginx switch script with isolated commands/configuration."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("failure", ["", "health", "syntax", "reload"])
def test_backend_switch_restores_config_on_failure(tmp_path, failure):
    source = Path(__file__).resolve().parents[2] / "scripts/switch-backend.sh"
    config = tmp_path / "default.conf"
    original = "set $backend_upstream http://backend:8000;\n"
    config.write_text(original)
    # Run the real shell body, replacing only the container filesystem path.
    script = tmp_path / "switch.sh"
    script.write_text(source.read_text().replace("/etc/nginx/conf.d/default.conf", str(config)))
    for name, body in {
        "wget": '[ "$FAILURE" != health ]',
        "nginx": 'echo "$*" >> "$CALLS"\nif [ "$1" = -t ]; then [ "$FAILURE" != syntax ]; else [ "$FAILURE" != reload ]; fi',
    }.items():
        executable = tmp_path / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; fake_compose() { shift 3; "$@"; }; compose=(fake_compose); switch_backend mv-backend-green-test', "test", str(script)],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAILURE": failure, "CALLS": str(calls)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (not failure), result.stderr
    assert config.read_text() == (original if failure else original.replace("http://backend:", "http://mv-backend-green-test:"))
    if not failure:
        assert calls.read_text().splitlines() == ["-t", "-s reload"]


@pytest.fixture
def deployment(tmp_path):
    root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ["deploy.sh", "rollback.sh"]:
        shutil.copy(root / "scripts" / name, scripts / name)
    (scripts / "switch-backend.sh").write_text('switch_backend() { echo "switch $1" >> "$CALLS"; [ "$FAILURE" != switchback ] || [ "$1" != backend ]; }\n')
    (tmp_path / ".env.local-build").touch()
    commands = {
        "docker": """echo "docker $*" >> "$CALLS"
case "$*" in
  *"ps --format json"*) echo '{"Health":"healthy"}' ;;
  *"ps --status running -q frontend"*) [ "$EXISTING" = 0 ] || echo old-frontend ;;
  *"redis-cli ping"*) echo PONG ;;
  *"config --format json"*) echo '{"services":{"backend":{"environment":{"JOB_EXECUTION_MODE":"inline"}}}}' ;;
  *"port frontend 80"*) echo '0.0.0.0:5173' ;;
  *"--entrypoint python"*)
      [ "$FAILURE" != preflight ] || exit 12
      if [ "$FAILURE" = hold ]; then
          touch "$WORK/entered"
          while [ ! -f "$WORK/release" ]; do /bin/sleep 0.05; done
      fi ;;
  "exec mv-backend-green-"*) [ "$FAILURE" != green ] || exit 15 ;;
  *"--force-recreate backend"*) [ "$FAILURE" != recreate ] || exit 17 ;;
  *"exec -T frontend nginx -s reload"*) [ "$FAILURE" != tls-reload ] || exit 18 ;;
esac
""",
        "curl": """echo "curl $*" >> "$CALLS"
case "$*" in
    *"%{http_code}"*) [ "$FAILURE" != frontend ] || exit 22; echo 200 ;;
esac
""",
        "openssl": "cat >/dev/null; echo stub\n",
        "sleep": "exit 0\n",
    }
    for name, body in commands.items():
        command = tmp_path / name
        command.write_text("#!/bin/sh\n" + body)
        command.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "WORK": str(tmp_path),
        "CALLS": str(tmp_path / "calls"),
        "FAILURE": "",
        "EXISTING": "1",
        "DEPLOY_ENV": "local-build",
        "DEPLOY_TLS": "0",
        "DEPLOY_SKIP_PULL": "1",
    }


def deploy(tmp_path, env, version="test-only", script="deploy.sh"):
    return subprocess.run(["bash", str(tmp_path / "scripts" / script), version], env=env, capture_output=True, text=True, timeout=12)


@pytest.mark.parametrize("failure", ["", "recreate", "switchback", "green"])
def test_deploy_keeps_green_until_backend_is_serving(tmp_path, deployment, failure):
    result = deploy(tmp_path, {**deployment, "FAILURE": failure})
    assert (result.returncode == 0) == (not failure), result.stderr
    events = Path(deployment["CALLS"]).read_text().splitlines()
    if failure == "green":
        assert not any(line.startswith("switch ") or "up -d --remove-orphans" in line for line in events)
        assert not (tmp_path / ".deployment/info.json").exists()
        return
    switched = next(i for i, line in enumerate(events) if line.startswith("switch mv-backend-green-"))
    recreated = next(i for i, line in enumerate(events) if "--force-recreate backend" in line)
    assert switched < recreated
    if failure:
        assert not any(line.startswith("docker stop --time 60 mv-backend-green-") for line in events)
        assert "remains serving traffic" in result.stderr
        assert not (tmp_path / ".deployment/info.json").exists()
    else:
        back = events.index("switch backend")
        stopped = next(i for i, line in enumerate(events) if line.startswith("docker stop --time 60 mv-backend-green-"))
        assert recreated < back < stopped
        assert (tmp_path / ".deployed-version").read_text().strip() == "test-only"


@pytest.mark.parametrize("failure", ["", "frontend", "tls-reload"])
def test_first_deployment_waits_for_actual_frontend_and_tls_reload(tmp_path, deployment, failure):
    certs = tmp_path / "certs"
    certs.mkdir()
    for name in ("fullchain.pem", "privkey.pem"):
        (certs / name).touch()
    env = {**deployment, "EXISTING": "0", "FAILURE": failure, "DEPLOY_TLS": "1", "TLS_DOMAIN": "fixture.example", "TLS_CERT_DIR": str(certs)}
    result = deploy(tmp_path, env)
    assert (result.returncode == 0) == (not failure), result.stderr
    events = Path(env["CALLS"]).read_text().splitlines()
    assert not any(line.startswith("switch ") for line in events)
    new_frontend = next(i for i, event in enumerate(events) if "up -d --remove-orphans" in event)
    reload_frontend = next(i for i, event in enumerate(events) if "exec -T frontend nginx -s reload" in event)
    assert new_frontend < reload_frontend
    info = tmp_path / ".deployment/info.json"
    assert info.exists() == (not failure)
    if not failure:
        assert reload_frontend < next(i for i, event in enumerate(events) if event.endswith("https://fixture.example/"))
        assert events[-1].endswith("https://fixture.example/api/health")
        assert json.loads(info.read_text())["version"] == "test-only"


def test_rollback_uses_last_successful_atomic_record(tmp_path, deployment):
    assert deploy(tmp_path, deployment, "A").returncode == 0
    assert deploy(tmp_path, deployment, "B").returncode == 0
    info = tmp_path / ".deployment/info.json"
    initial = info.read_bytes()
    (tmp_path / ".deployed-version").write_text("stale-current")
    (tmp_path / ".previous-version").write_text("stale-previous")
    assert deploy(tmp_path, {**deployment, "FAILURE": "preflight"}, "C").returncode != 0
    assert info.read_bytes() == initial
    assert deploy(tmp_path, deployment, "B").returncode == 0
    assert json.loads(info.read_text())["previous"] == "A"
    result = subprocess.run([str(tmp_path / "scripts/rollback.sh")], env=deployment, capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr
    entry = json.loads(info.read_text())
    assert (entry["version"], entry["previous"]) == ("A", "B")
    assert "docker-compose.rollback.yml" in Path(deployment["CALLS"]).read_text()


def test_previous_empty_is_authoritative_and_legacy_upgrade_keeps_pointer(tmp_path, deployment):
    info = tmp_path / ".deployment/info.json"
    info.parent.mkdir()
    info.write_text('{"version":"A","previous":""}')
    (tmp_path / ".previous-version").write_text("stale")
    result = deploy(tmp_path, deployment, "--previous")
    assert result.returncode and "no rollback version" in result.stderr
    info.write_text('{"version":"A","deployedAt":"legacy"}')
    (tmp_path / ".previous-version").write_text("old")
    assert deploy(tmp_path, deployment, "A").returncode == 0
    assert json.loads(info.read_text())["previous"] == "old"


def test_contending_deploy_fails_before_switch(tmp_path, deployment):
    held = subprocess.Popen(["bash", str(tmp_path / "scripts/deploy.sh"), "A"], env={**deployment, "FAILURE": "hold"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "entered").exists()
        second = deploy(tmp_path, deployment, "B")
        assert second.returncode and "another deployment" in second.stderr
        assert not (tmp_path / ".deployment/info.json").exists()
    finally:
        (tmp_path / "release").touch()
        _, error = held.communicate(timeout=12)
    assert held.returncode == 0, error
    assert json.loads((tmp_path / ".deployment/info.json").read_text())["version"] == "A"
