"""Exercise the actual Nginx switch script with isolated commands/configuration."""

import os
import subprocess
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


@pytest.mark.parametrize("failure", ["", "recreate", "switchback"])
def test_deploy_keeps_green_until_backend_is_serving(tmp_path, failure):
    root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy.sh").write_text((root / "scripts/deploy.sh").read_text())
    (scripts / "switch-backend.sh").write_text('switch_backend() { echo "switch $1" >> "$CALLS"; [ "$FAILURE" != switchback ] || [ "$1" != backend ]; }\n')
    (tmp_path / ".env.local-build").touch()
    commands = {
        "docker": """echo "docker $*" >> "$CALLS"
case "$*" in
  *"ps --format json"*) echo '{"Health":"healthy"}' ;;
  *"redis-cli ping"*) echo PONG ;;
  *"config --format json"*) echo '{"services":{"backend":{"environment":{"JOB_EXECUTION_MODE":"inline"}}}}' ;;
  *"--force-recreate backend"*) [ "$FAILURE" != recreate ] || exit 17 ;;
esac
""",
        "curl": "exit 0\n",
    }
    for name, body in commands.items():
        command = tmp_path / name
        command.write_text("#!/bin/sh\n" + body)
        command.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", str(scripts / "deploy.sh"), "test-only"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "CALLS": str(calls),
            "FAILURE": failure,
            "DEPLOY_ENV": "local-build",
            "DEPLOY_TLS": "0",
            "DEPLOY_SKIP_PULL": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (not failure), result.stderr
    events = calls.read_text().splitlines()
    switched = next(i for i, line in enumerate(events) if line.startswith("switch mv-backend-green-"))
    recreated = next(i for i, line in enumerate(events) if "--force-recreate backend" in line)
    assert switched < recreated
    if failure:
        assert not any(line.startswith("docker stop --time 60 mv-backend-green-") for line in events)
        assert "remains serving traffic" in result.stderr
        assert not (tmp_path / ".deployed-version").exists()
    else:
        back = events.index("switch backend")
        stopped = next(i for i, line in enumerate(events) if line.startswith("docker stop --time 60 mv-backend-green-"))
        assert recreated < back < stopped
        assert (tmp_path / ".deployed-version").read_text().strip() == "test-only"
