from __future__ import annotations

import dataclasses

import pytest


@pytest.mark.asyncio
async def test_disabled_bootstrap_never_recreates_removed_admin(monkeypatch):
    from app import auth

    def forbidden_database_access():
        raise AssertionError("disabled bootstrap must not inspect or recreate accounts")

    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, seed_admin_enabled=False))
    monkeypatch.setattr(auth, "session_factory", forbidden_database_access)
    await auth.seed_admin()
