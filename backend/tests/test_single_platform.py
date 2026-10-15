from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_comparison, main, model_gateway, prompt_optimizer, providers
from app.llm_policy import completion_options


def test_retired_routes_never_call_supplier(client, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, llm_channel="all-in-one"))
    for path in ("/api/account/balance", "/api/admin/runninghub/status", "/api/admin/kling/status"):
        assert client.get(path).status_code == 410


@pytest.mark.asyncio
async def test_legacy_model_is_rejected_before_network(monkeypatch):
    monkeypatch.setattr(llm_comparison, "settings", replace(llm_comparison.settings, llm_channel="all-in-one"))
    with pytest.raises(ValueError, match="已停用"):
        await llm_comparison.call_chat_model(model="gpt-5.5", protocol="openai", messages=[], temperature=0.2, max_tokens=100)
    monkeypatch.setattr(providers, "settings", replace(providers.settings, llm_channel="all-in-one"))
    for factory in (providers._video_config, providers._image_config, providers._yseeai_config, providers._toapis_config):
        with pytest.raises(providers.ProviderError, match="已停用"):
            factory()


def test_platform_optimizer_exposes_only_configured_gemini(monkeypatch):
    monkeypatch.setattr(prompt_optimizer, "settings", replace(prompt_optimizer.settings, llm_channel="all-in-one", llm_model="gemini-3.8-flash-all-in-one"))
    status = prompt_optimizer.provider_status()
    assert status["gemini"]["configured"]
    assert status["gemini"]["model"] == "gemini-3.8-flash-all-in-one"
    assert not status["minimax"]["configured"]
    assert completion_options(status["gemini"]["model"], 7000) == {"max_completion_tokens": 14000, "reasoning_effort": "low"}


@pytest.mark.asyncio
async def test_platform_optimizer_preserves_headers_usage_and_request(monkeypatch):
    from app import all_in_one, llm_failover, optimizer_media

    model = "gemini-3.8-flash-all-in-one"
    monkeypatch.setattr(prompt_optimizer, "settings", replace(prompt_optimizer.settings, llm_channel="all-in-one", llm_model=model))
    monkeypatch.setattr(llm_failover, "choose_model", AsyncMock(return_value=model))
    monkeypatch.setattr(llm_failover, "record_success", AsyncMock())
    monkeypatch.setattr(model_gateway, "current_owner", lambda: "u1")
    part = {"type": "image_url", "image_url": {"url": "https://tos.test/ref.jpg"}}
    monkeypatch.setattr(optimizer_media, "content_parts", AsyncMock(return_value=[part]))
    create = AsyncMock(
        return_value=SimpleNamespace(
            id="response-1", choices=[SimpleNamespace(message=SimpleNamespace(content="six section prompt"))], usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 42})
        )
    )

    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr(all_in_one, "chat_client", lambda **_: Client())
    result = await prompt_optimizer.call_gemini(prompt="test", duration=5, ratio="16:9", media=[], agent_name="code-agent", agent_run_id="run-1")
    request = create.call_args.kwargs
    assert request["model"] == "gemini-3.8-flash"
    assert request["extra_headers"] == {"X-Agent-Name": "code-agent", "X-Agent-Run-Id": "run-1", "X-Test-Run-Id": "run-1"}
    assert part in request["messages"][0]["content"]
    assert result["usage"]["total_tokens"] == 42
    assert result["provider"] == "all-in-one"
    assert result["requestSnapshot"] == request["messages"]


@pytest.mark.asyncio
async def test_reference_video_becomes_three_frames_and_verified_wav(monkeypatch, tmp_path):
    import base64
    import io
    import subprocess
    import wave

    from app import optimizer_media

    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source),
        ],
        check=True,
    )
    data = source.read_bytes()

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def raise_for_status(self):
            pass

        async def aiter_bytes(self):
            yield data

    class Client(Response):
        def __init__(self, **_):
            pass

        def stream(self, *_):
            return Response()

    monkeypatch.setattr(optimizer_media, "is_user_owned_tos_url", lambda url, owner: owner == "u1")
    monkeypatch.setattr(optimizer_media.httpx, "AsyncClient", Client)
    parts = await optimizer_media.content_parts([{"kind": "video", "url": "https://tos.test/clip.mp4"}], "u1")
    images = [part for part in parts if part["type"] == "image_url"]
    assert len(images) == 3
    assert all(part["image_url"]["url"].startswith("data:image/jpeg;base64,") for part in images)
    audio = next(part["input_audio"] for part in parts if part["type"] == "input_audio")
    with wave.open(io.BytesIO(base64.b64decode(audio["data"])), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
    with pytest.raises(ValueError, match="当前账号"):
        await optimizer_media.content_parts([{"kind": "video", "url": "https://tos.test/clip.mp4"}], "another-user")


def test_production_config_cleanup_preserves_platform_and_storage_secrets(monkeypatch, tmp_path):
    import runpy
    from pathlib import Path

    script = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/configure-single-platform.py"))
    configure = script["main"]
    monkeypatch.setitem(configure.__globals__, "ROOT", tmp_path)
    monkeypatch.setenv("DEPLOY_ENV", "production")
    monkeypatch.setenv("MAINTENANCE_DATA_DIR", str(tmp_path / "maintenance"))
    backend = tmp_path / "backend"
    backend.mkdir()
    runtime = backend / ".runtime_secrets.env"
    original = "ALL_IN_ONE_API_KEY=platform-test\nTOS_SECRET_ACCESS_KEY=storage-test\nJWT_SECRET=session-test\nAIGC_TOKEN=retired-test\nPROMPT_OPTIMIZER_MINIMAX_API_KEY=retired-test\nALL_IN_ONE_LLM_MODEL=old-model\n"
    runtime.write_text(original)
    configure()
    result = runtime.read_text()
    assert "ALL_IN_ONE_API_KEY=platform-test" in result
    assert "TOS_SECRET_ACCESS_KEY=storage-test" in result
    assert "JWT_SECRET=session-test" in result
    assert "retired-test" not in result
    assert "ALL_IN_ONE_LLM_MODEL=gemini-3.8-flash-all-in-one" in result
    assert runtime.stat().st_mode & 0o777 == 0o600
    backups = list((tmp_path / "maintenance/backups").glob("*/backend-runtime_secrets.env"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
    configure()
    assert runtime.read_text() == result
