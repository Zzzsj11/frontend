import pytest

from app import model_gateway, providers


def test_gateway_opt_in_and_user_attribution(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://model-service:8011")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "internal-key")
    monkeypatch.setattr(model_gateway, "current_agent_attribution", lambda: ("agent_test", "code-agent", "gateway-test"))
    model_gateway.set_owner("user-test")
    for config, channel in [(providers._image_config, "yinghe"), (providers._video_config, "yinghe"), (providers._yseeai_config, "yseeai"), (providers._toapis_config, "toapis")]:
        base, headers = config()
        assert base == "http://model-service:8011/providers/" + channel
        assert headers["Authorization"] == "Bearer internal-key"
        assert headers["X-User-Id"] == "user-test"
        assert headers["X-Agent-Run-Id"] == headers["X-Test-Run-Id"] == "gateway-test"
    model_gateway.set_owner("")
    with pytest.raises(RuntimeError, match="用户归因"):
        model_gateway.request_headers()


def test_gateway_disabled_keeps_direct_config(monkeypatch):
    monkeypatch.delenv("MODEL_GATEWAY_URL", raising=False)
    assert not model_gateway.enabled()
    client = model_gateway.AsyncOpenAI(api_key="direct-test", base_url="https://upstream.example/v1")
    assert str(client.base_url) == "https://upstream.example/v1/"


def test_unmigrated_channels_fall_back_to_direct(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://model-service:8011")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "internal-key")
    assert model_gateway.routed("yinghe")
    assert not model_gateway.routed("unknown-channel")


@pytest.mark.asyncio
async def test_worker_context_derives_stable_idempotency_key(monkeypatch):
    from types import SimpleNamespace

    from app import database

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, *_args):
            return SimpleNamespace(agent_name="", agent_run_id="")

        async def commit(self):
            pass

    monkeypatch.setattr(database, "session_factory", Session)
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://model-service:8011")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "internal-key")
    job = SimpleNamespace(id="mv-job-1", kind="image", user_id="owner-1", provider_task_id="", request={})

    async def runner(_job):
        first = model_gateway.request_headers()["Idempotency-Key"]
        second = model_gateway.request_headers()["Idempotency-Key"]
        assert first == second == "mv-mv-job-1"
        return "ok"

    assert await model_gateway.run_with_context(job, runner) == "ok"
    model_gateway.set_owner("owner-1")
    outside = model_gateway.request_headers()["Idempotency-Key"]
    assert outside.startswith("mv-") and outside != "mv-mv-job-1"
    model_gateway.set_owner("")


@pytest.mark.asyncio
async def test_llm_gateway_headers_are_per_call(monkeypatch):
    import httpx

    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://model-service:8011")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "internal-key")
    model_gateway.set_owner("user-test")
    monkeypatch.setattr(model_gateway, "current_agent_attribution", lambda: ("agent_test", "code-agent", "test-run"))
    client = model_gateway.AsyncOpenAI(api_key="unused", base_url="https://upstream.example/v1")
    hook = client._client.event_hooks["request"][0]
    a = httpx.Request("POST", "http://model-service:8011/v1/chat/completions")
    b = httpx.Request("POST", "http://model-service:8011/v1/chat/completions")
    await hook(a)
    await hook(b)
    assert a.headers["Idempotency-Key"] != b.headers["Idempotency-Key"]
    assert a.headers["X-Agent-Name"] == "code-agent"
    assert client.max_retries == 0
    await client.close()


@pytest.mark.asyncio
async def test_worker_context_preserves_owner_and_keeps_legacy_tasks_direct(monkeypatch):
    from types import SimpleNamespace

    from app import database

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, *_args):
            return SimpleNamespace(agent_name="code-agent", agent_run_id="persisted-run")

    monkeypatch.setattr(database, "session_factory", Session)
    monkeypatch.setenv("MODEL_GATEWAY_URL", "http://model-service:8011")
    monkeypatch.setenv("MODEL_GATEWAY_API_KEY", "internal-key")
    model_gateway.set_owner("admin-user")
    job = SimpleNamespace(id="mv-job", kind="video", user_id="real-owner", provider_task_id="job-gateway", request={"_modelGateway": True})

    async def runner(_job):
        assert model_gateway.enabled()
        headers = model_gateway.request_headers()
        assert headers["X-User-Id"] == "real-owner"
        assert headers["X-Agent-Run-Id"] == "persisted-run"
        return "ok"

    assert await model_gateway.run_with_context(job, runner) == "ok"
    assert model_gateway._owner.get() == "admin-user"
    job.provider_task_id = "legacy-provider-id"
    job.request = {}

    async def legacy_runner(_job):
        assert not model_gateway.enabled()
        return "legacy"

    assert await model_gateway.run_with_context(job, legacy_runner) == "legacy"
    assert model_gateway.enabled()


@pytest.mark.asyncio
async def test_gateway_job_cannot_fall_back_to_supplier_after_rollback(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("MODEL_GATEWAY_URL", raising=False)
    job = SimpleNamespace(request={"_modelGateway": True}, provider_task_id="job-gateway")

    async def should_not_run(_job):
        raise AssertionError("Must not submit or query direct provider")

    with pytest.raises(RuntimeError, match="MODEL_GATEWAY_URL"):
        await model_gateway.run_with_context(job, should_not_run)
