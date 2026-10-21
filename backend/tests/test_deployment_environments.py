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
    assert (tmp_path / ".env.production").read_text() == f"APP_CORS_ORIGINS=https://{domain}\n"

    deploy_file = tmp_path / ".env.production"
    deploy_file.write_text(deploy_file.read_text() + f"DEPLOYMENT_TIER={tier}\nTLS_DOMAIN={domain}\n")
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
