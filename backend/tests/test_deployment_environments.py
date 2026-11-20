"""Test-server preparation must never inherit production media paths or origins."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("tier,domain", [("test", "mv-test.epaipix.com"), ("production", "mv.epaipix.com")])
def test_server_config_keeps_tier_origin_and_existing_backup_key(tmp_path, monkeypatch, tier, domain):
    spec = importlib.util.spec_from_file_location("configure_server", Path(__file__).resolve().parents[2] / "scripts/configure-single-platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "backend").mkdir()
    runtime = tmp_path / "backend/.runtime_secrets.env"
    runtime.write_text("BACKUP_TOS_ENCRYPTION_KEY=existing-key\nTOS_REFERENCE_PREFIX=old\nALL_IN_ONE_BASE_URL=https://wrong.example\n")
    (tmp_path / ".env.production").write_text("APP_CORS_ORIGINS=https://old.example\n")
    for key, value in {"DEPLOY_ENV": "production", "DEPLOYMENT_TIER": tier, "TLS_DOMAIN": domain, "DEPLOY_TLS": "1", "MAINTENANCE_DATA_DIR": str(tmp_path / "maintenance")}.items():
        monkeypatch.setenv(key, value)
    module.main()
    text = runtime.read_text()
    assert f"TOS_REFERENCE_PREFIX=mv/{tier}/references\n" in text
    assert f"TOS_VIDEO_ARCHIVE_PREFIX=mv/{tier}/videos\n" in text
    assert "BACKUP_TOS_ENCRYPTION_KEY=existing-key\n" in text
    assert "REFRESH_COOKIE_SECURE=true\n" in text
    platform = "https://mg-test.epaipix.com" if tier == "test" else "https://mg.epaipix.com"
    assert f"ALL_IN_ONE_BASE_URL={platform}\n" in text
    assert (tmp_path / ".env.production").read_text().splitlines() == [f"DEPLOYMENT_TIER={tier}", f"TLS_DOMAIN={domain}", f"APP_CORS_ORIGINS=https://{domain}"]
    assert "AGENT_TEST_USERNAMES=dev01" not in text

    deploy_file = tmp_path / ".env.production"
    monkeypatch.delenv("DEPLOYMENT_TIER")
    monkeypatch.delenv("TLS_DOMAIN")
    module.main()
    assert f"TOS_REFERENCE_PREFIX=mv/{tier}/references\n" in runtime.read_text()
    assert f"APP_CORS_ORIGINS=https://{domain}\n" in deploy_file.read_text()
    assert f"ALL_IN_ONE_BASE_URL={platform}\n" in runtime.read_text()


def test_mismatched_tier_domain_aborts_before_secret_changes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("configure_server", Path(__file__).resolve().parents[2] / "scripts/configure-single-platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.setenv("DEPLOYMENT_TIER", "test")
    monkeypatch.setenv("TLS_DOMAIN", "mv.epaipix.com")
    with pytest.raises(SystemExit, match="does not match"):
        module.main()
    assert not (tmp_path / "backend").exists()


@pytest.mark.parametrize("tier,domain,other", [("test", "mv-test.epaipix.com", "mg.epaipix.com"), ("production", "mv.epaipix.com", "mg-test.epaipix.com")])
def test_runtime_rejects_cross_tier_platform(monkeypatch, tier, domain, other):
    from dataclasses import replace

    from app import config

    monkeypatch.setenv("DEPLOYMENT_TIER", tier)
    monkeypatch.setenv("TLS_DOMAIN", domain)
    monkeypatch.setattr(config, "settings", replace(config.settings, app_env="production", jwt_secret="x" * 40, all_in_one_base_url="https://" + other))
    with pytest.raises(RuntimeError, match="DEPLOYMENT_TIER"):
        config.validate_runtime_security()


def test_configure_writes_private_temporary_files_and_keeps_old_bytes(tmp_path, monkeypatch):
    import os
    import stat

    spec = importlib.util.spec_from_file_location("configure_server", Path(__file__).resolve().parents[2] / "scripts/configure-single-platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    file = tmp_path / ".runtime_secrets.env"
    file.write_bytes(b"old")
    file.chmod(0o600)
    owner = file.stat()
    replace = os.replace
    attempts = []

    def checked_replace(src, dst):
        assert src.parent == dst.parent
        assert stat.S_IMODE(src.stat().st_mode) == 0o600
        assert (src.stat().st_uid, src.stat().st_gid) == (owner.st_uid, owner.st_gid)
        attempts.append(src)
        if len(attempts) == 1:
            raise OSError("fixture rename interrupted")
        replace(src, dst)

    monkeypatch.setattr(module.os, "replace", checked_replace)
    with pytest.raises(OSError):
        module.write_private(file, b"new", owner)
    assert file.read_bytes() == b"old" and not attempts[0].exists()
    module.write_private(file, b"new", owner)
    assert file.read_bytes() == b"new" and attempts[1] != attempts[0]
    assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_configure_contends_with_same_deployment_lock_before_reading_secrets(tmp_path, monkeypatch):
    import fcntl

    spec = importlib.util.spec_from_file_location("configure_server", Path(__file__).resolve().parents[2] / "scripts/configure-single-platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("DEPLOY_ENV", "production")
    entered = []
    monkeypatch.setattr(module, "configure", lambda: entered.append(True))
    directory = tmp_path / ".deployment"
    directory.mkdir()
    with (directory / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match="in progress"):
            module.main()
        assert not entered
    module.main()
    assert entered == [True]
