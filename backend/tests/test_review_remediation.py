"""深度评审中跨用户资源引用的回归，不触发真实供应商。"""

from unittest.mock import AsyncMock

import pytest
from test_image_download import configure
from test_multi_user import create_and_login_user

from app import domain, image_download


@pytest.fixture(autouse=True)
def preserve_login_cookies(client):
    import httpx

    cookies = httpx.Cookies(client.cookies)
    yield
    client.cookies.clear()
    client.cookies.update(cookies)


def test_private_character_cannot_reference_another_users_images_or_style(client, monkeypatch):
    configure(monkeypatch)
    owner, headers = create_and_login_user(client, "review-avatar-owner")
    other, other_headers = create_and_login_user(client, "review-avatar-other")
    monkeypatch.setattr(domain, "_sync_human_asset_avatar", AsyncMock())
    base = "https://preview-media.tos-cn-beijing.volces.com"
    own = f"{base}/users/{owner}/face.png"
    foreign = f"{base}/users/{other}/face.png"
    body = {"name": "私有人物", "description": "", "avatar_url": own, "source": "uploaded"}
    assert client.post("/api/digital-humans", headers=headers, json={**body, "avatar_url": foreign}).status_code == 422
    assert client.post("/api/digital-humans", headers=headers, json={**body, "avatar_thumbnail_url": foreign}).status_code == 422
    created = client.post("/api/digital-humans", headers=headers, json=body)
    assert created.status_code == 201, created.text
    path = f"/api/digital-humans/{created.json()['id']}"
    for field in ("avatar_url", "avatar_thumbnail_url"):
        assert client.patch(path, headers=headers, json={field: foreign}).status_code == 422
    style = client.post("/api/digital-human-styles", headers=other_headers, json={"name": "私有分类"}).json()
    assert client.patch(path, headers=headers, json={"style_id": style["id"]}).status_code == 422
    # 即使历史数据中已存在被污染的私有头像引用，也不能签发其他用户的对象。
    import sqlite3

    from conftest import TEST_DB

    with sqlite3.connect(TEST_DB) as connection:
        connection.execute("UPDATE digital_humans SET avatar_url = ? WHERE id = ?", (foreign, created.json()["id"]))
    signer = AsyncMock()
    monkeypatch.setattr(image_download, "sign_download_url", signer)
    assert client.get("/api/media/image-download", headers=headers, params={"src": foreign}).status_code == 403
    signer.assert_not_awaited()


@pytest.mark.asyncio
async def test_pool_renewal_refreshes_ttl_without_resurrecting_lost_tokens():
    from app import redis_store

    pool = "review-renewal"
    key = f"execution-pool:{pool}"
    await redis_store.redis.delete(key)
    token = await redis_store.acquire_execution_lease(pool, 1, 180)
    assert token and token != "redis-unavailable"
    await redis_store.redis.expire(key, 1)
    await redis_store.renew_execution_lease(pool, token, 180)
    assert await redis_store.redis.ttl(key) > 170
    await redis_store.redis.delete(key)
    await redis_store.renew_execution_lease(pool, token, 180)
    assert not await redis_store.redis.exists(key)


@pytest.mark.asyncio
async def test_public_download_connects_to_validated_ip_and_preserves_tls_identity(monkeypatch, tmp_path):
    import socket

    import httpx

    from app.storage import download_public_url_to_path

    resolutions = []

    def resolve(host, port, *_args, **_kwargs):
        resolutions.append(host)
        address = "93.184.216.34" if len(resolutions) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    async def serve(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.org"
        assert request.extensions["sni_hostname"] == "example.org"
        assert request.headers["connection"] == "close"
        return httpx.Response(200, content=b"streamed", headers={"content-type": "image/png"})

    target = tmp_path / "download"
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as http:
        source, mime, size = await download_public_url_to_path("https://example.org/a.png", target, client=http)
    assert source == "https://example.org/a.png"
    assert target.read_bytes() == b"streamed"
    assert (mime, size) == ("image/png", 8)
    assert resolutions == ["example.org"]


def test_login_fails_closed_when_rate_limit_storage_is_unavailable(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "login_attempt_count", AsyncMock(side_effect=ConnectionError("redis unavailable")))
    response = client.post("/api/auth/login", json={"username": "admin", "password": "secure-admin-123"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"


@pytest.mark.asyncio
async def test_reclaimed_worker_cannot_renew_or_write_provider_task_or_assets(client):
    import sqlite3

    from conftest import TEST_DB
    from test_generation_jobs import _insert_job

    from app.jobs import Job, JobExpiredError, jobs

    _insert_job("review-stolen-lease", kind="image", status="running")
    with sqlite3.connect(TEST_DB) as connection:
        connection.execute("UPDATE generation_jobs SET worker_id = 'new-owner' WHERE id = 'review-stolen-lease'")
    stale = Job(id="review-stolen-lease", kind="image", worker_id="old-owner", result={"urls": []})
    with pytest.raises(JobExpiredError):
        await jobs.heartbeat(stale)
    with pytest.raises(JobExpiredError):
        await jobs.set_provider_task(stale, "all-in-one", "must-not-persist")
    with pytest.raises(JobExpiredError):
        await jobs._persist_asset(stale)
    with sqlite3.connect(TEST_DB) as connection:
        assert connection.execute("SELECT provider_task_id FROM generation_jobs WHERE id = 'review-stolen-lease'").fetchone()[0] is None
        assert connection.execute("SELECT count(*) FROM token_usage_records WHERE generation_job_id = 'review-stolen-lease'").fetchone()[0] == 0


def test_production_agent_attribution_requires_an_authorized_account(client, monkeypatch):
    from dataclasses import replace

    from app import auth

    _, headers = create_and_login_user(client, "review-untrusted-agent")
    monkeypatch.setattr(auth, "settings", replace(auth.settings, app_env="production", agent_test_usernames=()))
    assert client.get("/api/auth/me", headers=headers).status_code == 403
    monkeypatch.setattr(auth, "settings", replace(auth.settings, agent_test_usernames=("review-untrusted-agent",)))
    assert client.get("/api/auth/me", headers=headers).status_code == 200


@pytest.mark.asyncio
async def test_unlinked_usage_and_llm_logs_preserve_agent_source():
    from types import SimpleNamespace

    from app.agent_attribution import attribution_context
    from app.token_usage import add_llm_call_log, add_token_usage

    records = []
    session = SimpleNamespace(add=records.append)
    with attribution_context("agent_test", "code-agent", "review-origin-regression"):
        usage, _ = add_token_usage(session, operation="chat", provider="all-in-one", model="test", usage={"total_tokens": 4})
        log = add_llm_call_log(session, operation="chat", provider="all-in-one", model="test", usage={})
    for record in (usage, log):
        assert record.generation_origin == "agent_test"
        assert record.agent_name == "code-agent"
        assert record.agent_run_id == "review-origin-regression"
        assert record.generation_job_id is None


@pytest.mark.asyncio
async def test_content_rejections_do_not_trip_global_image_failover(monkeypatch):
    from app import all_in_one, image_failover
    from app.jobs import Job, jobs
    from app.providers import ProviderError

    task = Job(id="review-moderation", kind="image", provider_task_id="moderated", request={"_provider": "all-in-one", "model": image_failover.PRIMARY_MODEL})
    monkeypatch.setattr(all_in_one, "query_task", AsyncMock(return_value={"status": "FAILED", "failReason": {"code": "ContentPolicyViolation"}, "usage": {}}))
    monkeypatch.setattr(jobs, "record_provider_response", AsyncMock())
    outcome = AsyncMock()
    monkeypatch.setattr(image_failover, "record_outcome", outcome)
    with pytest.raises(ProviderError):
        await all_in_one.resume(task)
    outcome.assert_not_awaited()


def test_admin_user_changes_revoke_sessions_and_protect_self(client):
    owner, headers = create_and_login_user(client, "review-session-owner")
    changed = client.patch(f"/api/admin/users/{owner}", json={"status": "disabled"})
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    admin = client.get("/api/auth/me").json()
    assert client.patch(f"/api/admin/users/{admin['id']}", json={"status": "disabled"}).status_code == 422
    assert client.patch(f"/api/admin/users/{admin['id']}", json={"role": "user"}).status_code == 422
    # 相同角色的幂等保存不应把当前超级管理员踢出登录。
    assert client.put(f"/api/admin/users/{admin['id']}/admin-role", json={"admin_role_code": "super_admin"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    logs = client.get("/api/admin/audit-logs").json()["items"]
    assert any(log["action"] == "user.update" and log["targetId"] == owner for log in logs)


def test_rotated_refresh_reuse_revokes_its_family(client):
    import sqlite3
    from datetime import timedelta

    from conftest import TEST_DB

    from app.auth import REFRESH_COOKIE, _token_hash
    from app.models import utcnow

    owner, _ = create_and_login_user(client, "review-refresh-family")
    old = client.cookies.get(REFRESH_COOKIE)
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    with sqlite3.connect(TEST_DB) as connection:
        family_ids = connection.execute("SELECT DISTINCT family_id FROM refresh_tokens WHERE user_id = ? AND family_id <> ''", (owner,)).fetchall()
        # 首次修改密码前的会话已经撤销，比较本次旧凭证与新凭证。
        active_family = connection.execute("SELECT family_id FROM refresh_tokens WHERE token_hash = ?", (_token_hash(old),)).fetchone()[0]
        assert any(row[0] == active_family for row in family_ids)
        assert connection.execute("SELECT count(*) FROM refresh_tokens WHERE family_id = ? AND revoked_at IS NULL", (active_family,)).fetchone()[0] == 1
        connection.execute("UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ?", ((utcnow() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S.%f"), _token_hash(old)))
    client.cookies.set(REFRESH_COOKIE, old, domain="testserver.local", path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer " + refreshed.json()["accessToken"]}).status_code == 401
    with sqlite3.connect(TEST_DB) as connection:
        assert connection.execute("SELECT count(*) FROM refresh_tokens WHERE family_id = ? AND revoked_at IS NULL", (active_family,)).fetchone()[0] == 0


@pytest.mark.parametrize("limit, second_model, expected", [(1, None, 429), (10, "missing-model", 422)])
def test_batch_video_failure_rolls_back_all_jobs_and_quota(client, monkeypatch, limit, second_model, expected):
    import sqlite3

    from conftest import TEST_DB

    from app import main
    from app.jobs import jobs

    owner, headers = create_and_login_user(client, f"review-batch-{limit}")
    assert client.patch(f"/api/admin/users/{owner}", json={"daily_video_limit": limit}).status_code == 200
    dispatch = AsyncMock()
    monkeypatch.setattr(jobs, "dispatch", dispatch)
    monkeypatch.setattr(main, "ensure_video_batch_balance", AsyncMock(return_value={}))
    second = {"prompt": "second", "duration": 5}
    if second_model:
        second["model"] = second_model
    response = client.post("/api/generations/videos/batch", headers=headers, json={"items": [{"prompt": "first", "duration": 5}, second]})
    assert response.status_code == expected, response.text
    dispatch.assert_not_awaited()
    with sqlite3.connect(TEST_DB) as connection:
        assert connection.execute("SELECT count(*) FROM generation_jobs WHERE user_id = ?", (owner,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM daily_usage_quotas WHERE user_id = ?", (owner,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_running_worker_recovers_newly_expired_job_after_transient_claim_failure(client, monkeypatch):
    import asyncio
    from dataclasses import replace
    from datetime import timedelta

    from sqlalchemy import select, update

    from app import worker
    from app.database import session_factory
    from app.models import GenerationJobModel, WorkerInstanceModel, utcnow

    owner = client.get("/api/auth/me").json()["id"]
    job_id = "review-periodic-recovery"
    async with session_factory() as session:
        session.add(
            GenerationJobModel(
                id=job_id,
                kind="billing_reconcile",
                user_id=owner,
                status="running",
                worker_id="dead-worker",
                lease_expires_at=utcnow() + timedelta(minutes=1),
                request={"_provider": "review-only"},
            )
        )
        await session.commit()
    handlers = []
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda _signal, callback: handlers.append(callback))
    monkeypatch.setattr(worker, "STALE_RECOVERY_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "settings", replace(worker.settings, worker_poll_seconds=0.01))
    monkeypatch.setattr(worker, "close_redis", AsyncMock())
    monkeypatch.setattr(worker, "close_database", AsyncMock())
    monkeypatch.setenv("RELEASE_VERSION", "review-periodic-recovery")
    claim = worker._claim
    claims = 0
    expired = False

    async def transient_claim(*args):
        nonlocal claims
        claims += 1
        if claims == 1:
            raise ConnectionError("temporary database failure")
        return await claim(*args)

    async def wakeup(_timeout):
        nonlocal expired
        if not expired:
            expired = True
            async with session_factory() as session:
                await session.execute(update(GenerationJobModel).where(GenerationJobModel.id == job_id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
                await session.commit()
        await asyncio.sleep(0.01)

    async def recovered(job):
        assert job.id == job_id
        handlers[0]()
        return {"recovered": True}

    monkeypatch.setattr(worker, "_claim", transient_claim)
    monkeypatch.setattr(worker, "wait_for_worker_wakeup", wakeup)
    monkeypatch.setattr(worker, "_runner", lambda _job: recovered)
    await asyncio.wait_for(worker.serve(("billing_reconcile",), ("review-only",), 1), timeout=5)
    async with session_factory() as session:
        job = await session.get(GenerationJobModel, job_id)
        instance = await session.scalar(select(WorkerInstanceModel).where(WorkerInstanceModel.version == "review-periodic-recovery"))
        assert job.status == "succeeded"
        assert job.attempt == 2
        assert instance.status == "drained"
        assert instance.last_heartbeat_at is not None
    assert claims >= 2


def test_production_runtime_requires_secure_refresh_cookie(monkeypatch, tmp_path):
    from dataclasses import replace

    from app import config

    secret_file = tmp_path / "runtime_secrets"
    secret_file.write_text("")
    secret_file.chmod(0o600)
    monkeypatch.setattr(config, "RUNTIME_SECRETS_FILE", secret_file)
    monkeypatch.delenv("MODEL_GATEWAY_URL", raising=False)
    secure = replace(
        config.settings,
        app_env="production",
        jwt_secret="review-runtime-secret-longer-than-32-bytes",
        llm_channel="all-in-one",
        llm_model="gemini-3.8-flash-all-in-one",
        general_outline_llm_model="gemini-3.8-flash-all-in-one",
        refresh_cookie_secure=True,
    )
    monkeypatch.setattr(config, "settings", replace(secure, refresh_cookie_secure=False))
    with pytest.raises(RuntimeError, match="HTTPS"):
        config.validate_runtime_security()
    monkeypatch.setattr(config, "settings", secure)
    config.validate_runtime_security()


def test_remote_backup_requires_private_policy_and_validates_encrypted_object(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.backup_archive import archive_backup

    path = tmp_path / "snapshot.dump"
    path.write_bytes(b"isolated-backup-fixture")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    client = Mock()
    client.get_bucket_acl.return_value = SimpleNamespace(owner=SimpleNamespace(id="owner"), grants=[])
    client.get_bucket_policy.return_value = SimpleNamespace(policy='{"Statement": []}')
    client.head_object.return_value = SimpleNamespace(content_length=path.stat().st_size, meta={"sha256": digest}, header={"x-tos-server-side-encryption": "AES256"})
    result = archive_backup(client, "private-backup", "database", path, digest)
    assert result["sha256"] == digest
    assert client.upload_file.call_args.kwargs["server_side_encryption"] == "AES256"
    assert client.put_object.call_args.args[1] == "database/snapshot.dump.sha256"
    client.upload_file.reset_mock()
    client.get_bucket_policy.return_value.policy = '{"Statement": [{"Effect":"Allow","Principal":"*"}]}'
    with pytest.raises(RuntimeError, match="公开"):
        archive_backup(client, "private-backup", "database", path, digest)
    client.upload_file.assert_not_called()


def test_remote_backup_rejects_wrong_checksum_before_any_network_access(tmp_path):
    from unittest.mock import Mock

    from app.backup_archive import archive_backup

    path = tmp_path / "snapshot.dump"
    path.write_bytes(b"isolated-backup-fixture")
    client = Mock()
    with pytest.raises(ValueError, match="SHA-256"):
        archive_backup(client, "private-backup", "database", path, "0" * 64)
    assert client.mock_calls == []


@pytest.mark.asyncio
async def test_manual_storyboard_cannot_reference_another_users_optimization(client):
    from app.database import session_factory
    from app.models import PromptOptimizationTaskModel

    _, owner_headers = create_and_login_user(client, "review-line-owner")
    other, _ = create_and_login_user(client, "review-line-other")
    async with session_factory() as session:
        session.add(PromptOptimizationTaskModel(id="review-foreign-optimization", user_id=other, provider="all-in-one"))
        await session.commit()
    project = client.post("/api/projects", headers=owner_headers, json={"name": "private reference"}).json()
    task = client.post(f"/api/projects/{project['id']}/tasks", headers=owner_headers, json={"title": "manual", "storyboard_type": "general"}).json()
    line_path = f"/api/tasks/{task['id']}/storyboard/lines"
    line = client.post(line_path, headers=owner_headers, json={"lyrics": "manual"})
    assert line.status_code == 201, line.text
    foreign = {"optimization_task_id": "review-foreign-optimization"}
    assert client.patch(f"/api/storyboard-lines/{line.json()['id']}", headers=owner_headers, json=foreign).status_code == 422
    assert client.post(line_path, headers=owner_headers, json={"lyrics": "manual", **foreign}).status_code == 422


@pytest.mark.asyncio
async def test_media_upload_probe_accepts_wav_but_cannot_follow_embedded_network_urls():
    import asyncio
    import io
    import shutil
    import wave

    from fastapi import HTTPException

    from app.upload_validation import validate_av_content

    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is required for the media decoder boundary regression")
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    await validate_av_content("valid.wav", "audio/wav", output.getvalue())
    connections = []

    async def receive(_reader, writer):
        connections.append(True)
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(receive, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    playlist = (f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10,\nhttp://127.0.0.1:{port}/private.ts\n#EXT-X-ENDLIST\n").encode()
    try:
        with pytest.raises(HTTPException) as failure:
            await validate_av_content("disguised.mp4", "video/mp4", playlist)
        assert failure.value.status_code == 422
        # FFmpeg versions can reject HLS sniffing or its HTTP protocol. Neither may connect.
        assert connections == []
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_shared_provider_scheduler_isolates_expired_job_and_restarts_after_client_failure(monkeypatch):
    import asyncio

    from app import providers
    from app.jobs import Job, JobExpiredError, jobs

    async def update(job, _progress):
        if job.id == "expired":
            raise JobExpiredError("expired job")

    monkeypatch.setattr(jobs, "update_progress", update)
    monkeypatch.setattr(providers, "_query_task", AsyncMock(return_value={"status": "SUCCEEDED"}))
    scheduler = providers.ProviderPollScheduler(tick_seconds=0.001)
    results = await asyncio.wait_for(
        asyncio.gather(
            scheduler.watch("https://test", {}, Job(id="expired", kind="video"), timeout_seconds=1),
            scheduler.watch("https://test", {}, Job(id="healthy", kind="video"), timeout_seconds=1),
            return_exceptions=True,
        ),
        timeout=2,
    )
    assert isinstance(results[0], JobExpiredError)
    assert results[1]["status"] == "SUCCEEDED"
    if scheduler._runner:
        await scheduler._runner
    client = providers.httpx.AsyncClient
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("client initialization failed")
        return client(*args, **kwargs)

    monkeypatch.setattr(providers.httpx, "AsyncClient", fail_once)
    with pytest.raises(providers.ProviderError, match="调度异常"):
        await asyncio.wait_for(scheduler.watch("https://test", {}, Job(id="broken-client", kind="video"), timeout_seconds=1), timeout=2)
    recovered = await asyncio.wait_for(scheduler.watch("https://test", {}, Job(id="recovered-client", kind="video"), timeout_seconds=1), timeout=2)
    assert recovered["status"] == "SUCCEEDED"
    assert scheduler.active_count == 0
    if scheduler._runner:
        await scheduler._runner


def test_shared_bucket_backup_requires_customer_key_and_environment_directory(tmp_path):
    import base64
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.backup_archive import archive_backup

    path = tmp_path / "snapshot.dump"
    path.write_bytes(b"private-shared-bucket-backup")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    key = base64.b64encode(b"a" * 32).decode()
    client = Mock()
    client.head_object.return_value = SimpleNamespace(
        content_length=path.stat().st_size, meta={"sha256": digest}, header={"x-tos-server-side-encryption-customer-algorithm": "AES256"}
    )
    archive_backup(client, "shared-media", "mv/production/backups/database", path, digest, encryption_key=key)
    assert client.upload_file.call_args.kwargs["ssec_key"] == key
    assert client.put_object.call_args.kwargs["ssec_key"] == key
    client.get_bucket_acl.assert_not_called()
    client.reset_mock()
    for prefix, bad_key in (("public", key), ("mv/test/backups/database", "bad-key")):
        with pytest.raises(ValueError):
            archive_backup(client, "shared-media", prefix, path, digest, encryption_key=bad_key)
    client.upload_file.assert_not_called()
