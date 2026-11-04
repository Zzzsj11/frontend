"""Lifecycle failures must not leave this run's containers behind."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/local_runtime.py"
spec = importlib.util.spec_from_file_location("local_runtime", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize("failure", [None, "startup", "body", "interrupt"])
def test_dependency_cleanup_including_partial_startup(failure):
    calls = []

    def runner(args, **kwargs):
        args = [str(arg) for arg in args]
        calls.append(args)
        if "up" in args and failure == "startup":
            raise RuntimeError("partial startup failed")
        return SimpleNamespace(stdout="127.0.0.1:32123\n")

    def exercise():
        with runtime.dependencies(runner=runner) as env:
            assert "/mv_local_proof" in env["DATABASE_URL"]
            assert env["ALL_IN_ONE_API_KEY"] == ""
            assert env["ALL_IN_ONE_BASE_URL"] == "https://mg-test.epaipix.com"
            if failure == "body":
                raise RuntimeError("verification failed")
            if failure == "interrupt":
                raise KeyboardInterrupt

    if failure:
        with pytest.raises(KeyboardInterrupt if failure == "interrupt" else RuntimeError):
            exercise()
    else:
        exercise()
    assert calls[-1][-5:] == ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
    assert all(args[3].startswith("mv-local-") for args in calls)
    assert all("docker-compose.yml" in " ".join(args) and "docker-compose.local-build.yml" in " ".join(args) for args in calls)
    override = Path(calls[0][calls[0].index("up") - 1])
    assert not override.exists(), "Temporary compose file was not cleaned"


def test_unexpected_public_binding_fails_and_cleans_up():
    calls = []

    def runner(args, **kwargs):
        calls.append([str(arg) for arg in args])
        return SimpleNamespace(stdout="0.0.0.0:5432\n")

    with pytest.raises(RuntimeError, match="loopback"):
        with runtime.dependencies(runner=runner):
            pytest.fail("Public database binding was accepted")
    assert "down" in calls[-1]


def test_temporary_storage_does_not_mount_existing_volumes():
    text = runtime.overlay("mv-local-synthetic")
    assert text.count("volumes: !reset []") == 2
    assert "tmpfs:" in text and "127.0.0.1::5432" in text and "127.0.0.1::6379" in text
    assert "mvagent_postgres:" not in text and "mvagent_redis:" not in text


def test_build_image_cleanup_attempted_even_when_compose_cleanup_fails(monkeypatch):
    cleaned = []
    monkeypatch.setattr(runtime, "remove_build_images", cleaned.append)

    def runner(args, **kwargs):
        if "down" in args:
            raise RuntimeError("daemon disconnected")

    with pytest.raises(RuntimeError, match="daemon disconnected"):
        with runtime.dependencies(build=True, runner=runner):
            pass
    assert len(cleaned) == 1 and cleaned[0].startswith("mv-local-")


def test_image_cleanup_failure_is_reported_instead_of_claiming_success(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="image is in use"))
    with pytest.raises(RuntimeError, match="Could not remove"):
        runtime.remove_build_images("mv-local-synthetic")
