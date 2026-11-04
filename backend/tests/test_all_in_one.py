import dataclasses
from unittest.mock import AsyncMock

import httpx
import pytest

from app import all_in_one as aio
from app.all_in_one_catalog import rows
from app.jobs import Job, jobs
from app.llm_policy import completion_options
from app.providers import ProviderSubmissionUncertainError
from app.schemas import ImageGenerationCreate, VideoGenerationCreate


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        aio, "settings", dataclasses.replace(aio.settings, all_in_one_api_key="test-key", all_in_one_base_url="https://channel.example", all_in_one_system_key=False)
    )


def test_personal_and_system_identity(configured, monkeypatch):
    assert "X-User-Id" not in aio.headers(user_id="owner")
    monkeypatch.setattr(aio, "settings", dataclasses.replace(aio.settings, all_in_one_system_key=True))
    with pytest.raises(RuntimeError, match="用户归因"):
        aio.headers()
    assert aio.headers(user_id="owner")["X-User-Id"] == "owner"


@pytest.mark.asyncio
async def test_chat_timeout_allows_long_outline_stage(configured):
    client = aio.chat_client()
    try:
        assert client.timeout == 600
    finally:
        await client.close()


def test_catalog_scope_does_not_clone_yinghe_billing():
    result = rows({"minimax-h3": {"billing": {"currency": "CNY"}, "h3Modes": ["reference"]}})
    assert len(result) == 19
    assert len([m for m in result if m["modality"] == "chat"]) == 5
    h3 = next(m for m in result if m["provider_model_id"] == "MiniMax-H3")
    assert h3["capabilities"]["billing"] == {
        "provider": "all-in-one",
        "balanceCheck": False,
        "billingMode": "platform_points",
        "currency": "points",
    }
    assert h3["capabilities"]["executionConcurrency"] == 100
    assert "reference" in h3["capabilities"]["h3Modes"]
    assert next(m for m in result if m["code"].startswith("doubao-seedance"))["provider_model_id"] == "seedance-2.0"


def test_normalized_result_preserves_pending_cost():
    data = aio.normalized_task(
        {"status": "succeeded", "result": {"media": [{"url": "https://media.example/test.mp4"}]}, "usage": None, "billing": {"status": "pending_reconciliation", "points": None}}
    )
    assert data["status"] == "SUCCEEDED"
    assert data["resultUrls"] == ["https://media.example/test.mp4"]
    assert data["usage"]["platformBilling"]["points"] is None


@pytest.mark.parametrize("model", ["gpt-6.1-sol-all-in-one", "gpt-6-sol-all-in-one", "gpt-6-astra-all-in-one"])
def test_reasoning_compatibility(model):
    assert completion_options(model, 1400) == {"max_completion_tokens": 8192, "reasoning_effort": "low"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "upstream_model"),
    [
        ("image", "gpt-image-2"),
        ("video", "MiniMax-H3"),
        ("video", "seedance-2.0"),
        ("video", "seedance-2.0-fast"),
        ("video", "seedance-2.0-mini"),
        ("video", "seedance-2.5"),
        ("video", "wan3.0-video"),
    ],
)
@pytest.mark.parametrize("selected_channel", [None, "toapis-official"])
async def test_create_maps_payload_and_durable_identity(configured, monkeypatch, kind, upstream_model, selected_channel):
    captured = []

    def handle(request):
        import json

        captured.append((request, json.loads(request.content)))
        return httpx.Response(202, json={"id": "upstream-job", "status": "queued"})

    original = httpx.AsyncClient
    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(jobs, "mark_provider_submitting", AsyncMock())
    provider_request = AsyncMock()
    provider_response = AsyncMock()
    monkeypatch.setattr(jobs, "record_provider_request", provider_request)
    monkeypatch.setattr(jobs, "record_provider_response", provider_response)
    persist = AsyncMock()
    monkeypatch.setattr(jobs, "set_provider_task", persist)
    monkeypatch.setattr(aio, "resume", AsyncMock(return_value={"done": True}))
    monkeypatch.setattr("app.model_gateway.current_agent", lambda: ("code-agent", "test-run"))
    job = Job(
        id="local-job",
        kind=kind,
        user_id="private-owner",
        request={"channel": selected_channel, "_providerModelId": upstream_model, "_capabilities": {"providerResolutionMap": {"720p": "768P"}}},
    )
    request = (
        ImageGenerationCreate(model="gpt-image-2-all-in-one", prompt="cup", images=["https://media.example/input.png"])
        if kind == "image"
        else VideoGenerationCreate(model="minimax-h3-all-in-one", prompt="cup", image_urls=["https://media.example/input.png"], resolution="720p", duration=5)
    )
    assert await aio.generate(request, job) == {"done": True}
    req, body = captured[0]
    assert req.headers["Idempotency-Key"] == f"local-job:{kind}"
    assert req.headers["X-Agent-Run-Id"] == req.headers["X-Test-Run-Id"] == "test-run"
    assert "X-User-Id" not in req.headers
    assert body.get("channel") == selected_channel
    assert ("channel" in body) == (selected_channel is not None)
    assert body["images"] == ["https://media.example/input.png"]
    assert "realPersonMode" not in body
    if kind == "video":
        assert body["resolution"] == "768P"
    provider_request.assert_awaited_once_with(job, body)
    provider_response.assert_awaited_once_with(job, "submission", {"id": "upstream-job", "status": "queued"})
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncertain_submission_is_never_reposted(configured, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(500, json={"detail": "Internal error"})

    original = httpx.AsyncClient
    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(jobs, "mark_provider_submitting", AsyncMock())
    monkeypatch.setattr(jobs, "record_provider_request", AsyncMock())
    job = Job(id="test-uncertain", kind="image", user_id="owner", request={"_providerModelId": "gpt-image-2"})
    with pytest.raises(ProviderSubmissionUncertainError):
        await aio.generate(ImageGenerationCreate(model="gpt-image-2-all-in-one", prompt="cup"), job)
    assert len(calls) == 1
    assert job.idempotency_key == "test-uncertain:image"


@pytest.mark.asyncio
async def test_direct_worker_keeps_agent_headers(configured, monkeypatch):
    from types import SimpleNamespace

    from app import database, model_gateway

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, *_args):
            return SimpleNamespace(agent_name="code-agent", agent_run_id="persisted-run")

    monkeypatch.delenv("MODEL_GATEWAY_URL", raising=False)
    monkeypatch.setattr(database, "session_factory", Session)
    job = Job(id="worker-job", kind="image", user_id="owner", request={"_provider": "all-in-one"})

    async def runner(_job):
        values = aio.headers(user_id="owner")
        assert values["X-Agent-Run-Id"] == values["X-Test-Run-Id"] == "persisted-run"
        assert values["X-Agent-Name"] == "code-agent"
        return "ok"

    assert await model_gateway.run_with_context(job, runner) == "ok"


@pytest.mark.asyncio
async def test_aio_text_5xx_has_no_blind_retry(monkeypatch):
    from app import llm_comparison, storyboard_prompt
    from app.llm_policy import TemporaryLlmError

    class ServerError(Exception):
        status_code = 500

    monkeypatch.setattr(storyboard_prompt, "settings", dataclasses.replace(storyboard_prompt.settings, llm_model="gpt-6-sol-all-in-one"))
    call = AsyncMock(side_effect=ServerError("original job unknown"))
    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    records = []
    with pytest.raises(TemporaryLlmError):
        await storyboard_prompt._call(None, [], 1400, operation="storyboard_line", usage_records=records)
    call.assert_awaited_once()
    assert len(records) == 1


def test_aio_models_are_available_in_catalog_and_comparison(client):
    options = client.get("/api/model-options").json()
    import json

    encoded = json.dumps(options)
    for code in ["gpt-6.1-sol", "gpt-6-astra", "doubao-seed-2-1-pro-260915", "doubao-seedance-2.0", "wan3.0-video", "minimax-h3"]:
        assert code + "-all-in-one" in encoded
    assert any(item["id"] == "nano-banana-2.1-all-in-one" for item in options)
    assert any(item["id"] == "seedream-5.0-pro-all-in-one" for item in options)
    comparison = client.get("/api/admin/chat-comparison/models").json()
    assert all(any(item["code"] == code + "-all-in-one" for item in comparison) for code in ["gpt-6.1-sol", "gpt-6-astra", "doubao-seed-2-1-pro-260915"])


@pytest.mark.asyncio
async def test_known_job_on_5xx_restores_without_posting_again(configured, monkeypatch):
    original = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(500, headers={"X-Job-Id": "durable-job"}, json={"error": {"job_id": "durable-job"}})

    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(jobs, "mark_provider_submitting", AsyncMock())
    monkeypatch.setattr(jobs, "record_provider_request", AsyncMock())
    persist = AsyncMock()
    monkeypatch.setattr(jobs, "set_provider_task", persist)
    resume = AsyncMock(return_value={"restored": True})
    monkeypatch.setattr(aio, "resume", resume)
    job = Job(id="test-recover", kind="image", user_id="owner", request={"_providerModelId": "gpt-image-2"})
    assert await aio.generate(ImageGenerationCreate(model="gpt-image-2-all-in-one", prompt="cup"), job) == {"restored": True}
    assert len(calls) == 1
    persist.assert_awaited_once_with(job, "all-in-one", "durable-job", idempotency_key="test-recover:image")
    resume.assert_awaited_once()


def test_new_channel_key_is_redacted():
    from app.error_logging import redact_error_text

    assert redact_error_text("bad ms_abcdefghijklmnop123456789") == "bad ms_***"


@pytest.mark.asyncio
async def test_resume_uses_original_job_without_creation(configured, monkeypatch):
    query = AsyncMock(
        side_effect=[
            RuntimeError("temporary connection"),
            {"status": "RUNNING", "failReason": ""},
            {"status": "SUCCEEDED", "result": {"media": [{"url": "https://media.example/result"}]}},
        ]
    )
    monkeypatch.setattr(aio, "query_task", query)
    stored = AsyncMock(return_value={"urls": ["https://tos.example/user-result"]})
    monkeypatch.setattr(aio, "store_result", stored)
    monkeypatch.setattr(jobs, "update_progress", AsyncMock())
    terminal = AsyncMock()
    monkeypatch.setattr(jobs, "record_provider_response", terminal)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    job = Job(id="resume-only", kind="image", provider_task_id="original-id", user_id="owner")
    assert await aio.resume(job) == {"urls": ["https://tos.example/user-result"]}
    assert query.await_count == 3
    assert all(c.args[1] == "original-id" for c in query.call_args_list)
    stored.assert_awaited_once()
    terminal.assert_awaited_once()


@pytest.mark.asyncio
async def test_seedance_uses_public_original_images_without_private_review(configured, monkeypatch):
    from app.providers import ProviderError

    original = httpx.AsyncClient
    payloads = []

    def handle(request):
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(202, json={"id": "seedance-review"})

    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    submitting = AsyncMock()
    monkeypatch.setattr(jobs, "mark_provider_submitting", submitting)
    monkeypatch.setattr(jobs, "record_provider_request", AsyncMock())
    monkeypatch.setattr(jobs, "record_provider_response", AsyncMock())
    monkeypatch.setattr(jobs, "set_provider_task", AsyncMock())
    monkeypatch.setattr(aio, "resume", AsyncMock(return_value={"done": True}))
    job = Job(id="sd-aio", kind="video", user_id="owner", request={"_providerModelId": "seedance-2.0"})
    request = VideoGenerationCreate(model="doubao-seedance-2.0-all-in-one", prompt="scene", image_urls=["https://tos.example/original.png"], resolution="480p", duration=4)
    await aio.generate(request, job)
    assert "private_asset_review" not in payloads[0]
    assert payloads[0]["images"] == ["https://tos.example/original.png"]
    submitting.reset_mock()
    request.image_urls = ["asset://another-account"]
    with pytest.raises(ProviderError, match="原始 TOS"):
        await aio.generate(request, job)
    submitting.assert_not_awaited()


@pytest.mark.asyncio
async def test_sd20_person_asset_mode_is_transmitted_with_identity_positions(configured, monkeypatch):
    import json

    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(202, json={"id": "asset-mode-test"})

    original = httpx.AsyncClient
    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    for name in ("mark_provider_submitting", "record_provider_request", "record_provider_response", "set_provider_task"):
        monkeypatch.setattr(jobs, name, AsyncMock())
    monkeypatch.setattr(aio, "resume", AsyncMock(return_value={"ok": True}))
    request = VideoGenerationCreate(
        model="doubao-seedance-2.0-all-in-one", prompt="synthetic", image_urls=["https://example.com/identity.png"], person_asset_mode=True, person_reference_indices=[1]
    )
    job = Job(id="person-assets-contract", kind="video", user_id="owner", request={"_providerModelId": "seedance-2.0"})
    await aio.generate(request, job)
    assert captured[0]["images"] == request.image_urls
    assert captured[0]["person_asset_mode"] is True
    assert captured[0]["person_reference_indices"] == [1]
    assert "private_asset_review" not in captured[0] and "real_person_mode" not in captured[0]


@pytest.mark.asyncio
async def test_platform_proven_preacceptance_503_is_safe_rejection(configured, monkeypatch):
    from app.providers import ProviderRejectedError

    original = httpx.AsyncClient
    response = httpx.Response(503, json={"detail": "all routes unavailable"}, headers={"X-Platform-Job-Created": "false", "X-Generation-Submitted": "false"})
    monkeypatch.setattr(aio.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(lambda _: response), **kw))
    for name in ("mark_provider_submitting", "record_provider_request", "record_provider_response"):
        monkeypatch.setattr(jobs, name, AsyncMock())
    request = VideoGenerationCreate(model="doubao-seedance-2.0-all-in-one", prompt="synthetic")
    job = Job(id="proven-unsubmitted", kind="video", user_id="owner", request={"_providerModelId": "seedance-2.0"})
    with pytest.raises(ProviderRejectedError, match="未提交视频"):
        await aio.generate(request, job)
