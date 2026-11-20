"""Focused, offline regression checks for API ownership, admission and resource bounds."""

import asyncio
import base64
import io
import json
import sqlite3
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest
from conftest import TEST_DB
from fastapi import HTTPException
from PIL import Image
from test_multi_user import create_and_login_user

from app import ass_storyboard, chat, error_logging, export_space, main, redis_store, storage


@pytest.fixture(autouse=True)
def restore_login_cookie(client):
    saved = httpx.Cookies(client.cookies)
    yield
    client.cookies.clear()
    client.cookies.update(saved)


def test_chat_rejects_foreign_delete_before_cancel(client, monkeypatch):
    _, owner = create_and_login_user(client, "review-chat-owner")
    _, other = create_and_login_user(client, "review-chat-peer")
    session = client.post("/api/chat/sessions", json={}, headers=owner).json()["id"]
    stop = AsyncMock()
    monkeypatch.setattr(chat.chat_manager, "interrupt", stop)
    assert client.delete("/api/chat/" + session, headers=other).status_code == 404
    stop.assert_not_awaited()
    assert client.get("/api/chat/" + session, headers=owner).status_code == 200


def test_empty_chat_and_failed_enqueue_preserve_quota_and_idle(client, monkeypatch):
    user_id, headers = create_and_login_user(client, "review-chat-accept")
    session = client.post("/api/chat/sessions", headers=headers, json={}).json()["id"]
    path = f"/api/chat/{session}/messages"
    assert client.post(path, headers=headers, json={"text": "  "}).status_code == 422
    monkeypatch.setattr(chat.jobs, "enqueue", AsyncMock(side_effect=RuntimeError("queue unavailable")))
    assert client.post(path, headers=headers, json={"text": "hello"}).status_code == 409
    with sqlite3.connect(TEST_DB) as db:
        assert db.execute("select status from chat_sessions where id=?", [session]).fetchone() == ("idle",)
        assert db.execute("select count(*) from chat_messages where session_id=?", [session]).fetchone() == (0,)
        assert db.execute("select count(*) from daily_usage_quotas where user_id=?", [user_id]).fetchone() == (0,)


def test_client_validation_is_sanitized_and_coalesced(client, monkeypatch):
    monkeypatch.setattr(error_logging, "_client_errors", {})
    marker = "not-a-real-credential-" * 12
    path = "/api/auth/login"
    first = client.post(path, params={"token": marker}, json={"username": "admin", "password": marker})
    assert first.status_code == 422
    duplicate = client.post(path, params={"token": marker}, json={"username": "admin", "password": marker})
    assert duplicate.json()["errorCode"] == first.json()["errorCode"]
    with sqlite3.connect(TEST_DB) as db:
        row = db.execute("select query_string,traceback,message,request_payload from api_error_logs where error_code=?", [first.json()["errorCode"]]).fetchone()
        assert row and marker not in repr(row)
        assert parse_qs(row[0])["token"] == ["***"]


@pytest.mark.asyncio
async def test_login_reservations_enforce_limit_until_own_release():
    token = uuid.uuid4().hex
    identities = (token, token + "-user")
    reservations = await asyncio.gather(*(redis_store.reserve_login_attempt(identities, 2, 60) for _ in range(5)))
    accepted = [r for r in reservations if r]
    assert len(accepted) == 2
    await redis_store.release_login_attempt(identities, accepted[0])
    assert await redis_store.reserve_login_attempt(identities, 2, 60)
    assert not await redis_store.reserve_login_attempt(identities, 2, 60)


@pytest.mark.asyncio
async def test_incremental_chat_events_follow_cursor():
    session = uuid.uuid4().hex
    await redis_store.append_chat_event(session, "state", {"status": "running"})
    await redis_store.append_chat_event(session, "state", {"status": "idle"})
    assert [item["seq"] for item in await redis_store.chat_events_after(session, 1)] == [2]
    assert not await redis_store.chat_events_after(session, 2)


def test_ass_duration_and_export_budget_fail_before_large_allocations(tmp_path, monkeypatch):
    assert ass_storyboard.parse_time("1:00:00.00") == 3600
    with pytest.raises(ValueError, match="1 小时"):
        ass_storyboard.parse_time("1:00:00.01")
    monkeypatch.setattr(export_space, "settings", replace(export_space.settings, export_temp_limit_mb=2, export_temp_reserve_mb=1))
    budget = export_space.ExportSpace(tmp_path)
    budget.download(0, 1024**2, 1024**2)
    assert budget.output_limit() <= 1024**2
    with pytest.raises(ValueError, match="素材总量"):
        budget.download(1, 5, 2 * 1024**2)


@pytest.mark.asyncio
async def test_inline_image_archived_as_validated_user_object(monkeypatch):
    stream = io.BytesIO()
    Image.new("RGB", (10, 8)).save(stream, format="PNG")
    raw = stream.getvalue()
    client = SimpleNamespace(put_bytes=AsyncMock(side_effect=["https://example.test/original", "https://example.test/thumb"]))
    monkeypatch.setattr(storage, "get_storage", lambda: client)
    reference = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert await main.store_inline_reference(reference, "owner") == "https://example.test/original"
    assert client.put_bytes.await_args_list[0].args[0].startswith("users/owner/")
    assert client.put_bytes.await_count == 2
    with pytest.raises(HTTPException):
        await main.store_inline_reference(reference.replace("image/png", "image/jpeg"), "owner")
    assert client.put_bytes.await_count == 2


@pytest.mark.asyncio
async def test_platform_references_authorize_system_or_owner_only(monkeypatch):
    monkeypatch.setattr(storage, "settings", replace(storage.settings, tos_public_domain="asset.example.test"))
    db = AsyncMock()
    system = "https://asset.example.test/system/ref.png"
    db.execute.return_value = SimpleNamespace(all=lambda: [(system, None)])
    await main.validate_platform_references(db, "owner", [system, "https://asset.example.test/users/owner/file", "https://external.example.test/ref"])
    for suffix in ["mp4", "png", "mp3"]:
        with pytest.raises(HTTPException):
            await main.validate_platform_references(db, "owner", ["https://asset.example.test/users/other/file." + suffix])


def test_error_sampler_does_not_persist_full_upload(client):
    run_id = "media-log-" + uuid.uuid4().hex
    client.post("/api/uploads", headers={"X-Test-Run-Id": run_id}, files={"file": ("sample.txt", b"a" * 12000, "text/plain")})
    with sqlite3.connect(TEST_DB) as db:
        payload = json.loads(db.execute("select request_payload from api_request_logs where run_id=?", [run_id]).fetchone()[0])
    assert set(payload) == {"contentType"}


def test_batch_fetches_one_catalog_for_same_channel(client, monkeypatch):
    from app import generation_preferences
    from app.jobs import jobs

    user_id, headers = create_and_login_user(client, "review-catalog-batch")
    catalog = AsyncMock(return_value={"channels": [{"channel": "test-channel", "available": True}]})
    monkeypatch.setattr(generation_preferences, "fetch_channels", catalog)
    monkeypatch.setattr(jobs, "dispatch", AsyncMock())
    monkeypatch.setattr(main, "ensure_video_batch_balance", AsyncMock(return_value={}))
    model = "doubao-seedance-2.0-all-in-one"
    body = {"model": model, "prompt": "offline", "channel": "test-channel", "duration": 5}
    items = [{**body, "request_id": name} for name in ["first", "second"]]
    result = client.post("/api/generations/videos/batch", headers=headers, json={"items": items})
    assert result.status_code == 202, result.text
    assert catalog.await_count == 1
    assert catalog.await_args.args[1] == user_id
    replay = client.post("/api/generations/videos/batch", headers=headers, json={"items": items})
    assert replay.status_code == 202
    assert catalog.await_count == 1


def test_username_remains_reserved_after_soft_delete(client):
    user_id, _ = create_and_login_user(client, "review-name-reserved")
    assert client.delete("/api/admin/users/" + user_id).status_code == 200
    response = client.post("/api/admin/users", json={"username": "review-name-reserved", "password": "temporary-test-password"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_stream_identity_stops_after_revocation(client):
    import jwt
    from starlette.requests import Request

    from app.auth import stream_session_active

    user, headers = create_and_login_user(client, "review-stream-session")
    identity = jwt.decode(headers["Authorization"].removeprefix("Bearer "), options={"verify_signature": False})
    request = Request({"type": "http", "headers": []})
    request.state.access_expiry = identity["exp"]
    request.state.auth_version = identity["ver"]
    request.state.session_family = identity["sid"]
    assert await stream_session_active(request, user)
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert not await stream_session_active(request, user)


@pytest.mark.asyncio
async def test_remote_import_checks_file_before_tos(monkeypatch):
    async def download(_url, path):
        path.write_text("ordinary plain text")
        return "https://external.example.test/sample.txt", "text/plain", 19

    monkeypatch.setattr(storage, "download_public_url_to_path", download)
    monkeypatch.setattr(storage, "get_storage", lambda: pytest.fail("invalid input reached TOS"))
    with pytest.raises(ValueError, match="媒体格式"):
        await storage.import_remote("https://external.example.test/sample.txt", "users/test/imports", validate_media=True)
