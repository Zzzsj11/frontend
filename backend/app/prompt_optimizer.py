from __future__ import annotations

import time
from typing import Any

import httpx

from . import model_gateway
from .agent_attribution import current_agent_attribution
from .config import settings
from .error_logging import redact_error_text

PROVIDERS = ("gemini", "minimax")
RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
MEDIA_LIMITS = {"image": 9, "video": 3, "audio": 3}

SYSTEM_INSTRUCTION = """You are an expert MiniMax H3 full-reference Ref2VA prompt editor.
Analyze every supplied text, image, video, and audio reference directly. Return only the final English prompt, with no Markdown fence or commentary. Use exactly these six section names in order: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music. Keep reference labels stable, use exact shot timing matching the requested duration, and explicitly describe composition, subjects, environment, actions, camera, synchronized physical sound, and referenced music."""


def provider_status() -> dict[str, dict[str, Any]]:
    if settings.llm_channel == "all-in-one":
        return {
            "gemini": {"configured": bool(settings.all_in_one_api_key), "model": settings.llm_model, "keyTail": ""},
            "minimax": {"configured": False, "model": "已停用", "keyTail": ""},
        }
    return {
        "gemini": {
            "configured": bool(settings.prompt_optimizer_gemini_api_key),
            "model": settings.prompt_optimizer_gemini_model,
            "keyTail": f"…{settings.prompt_optimizer_gemini_api_key[-4:]}" if settings.prompt_optimizer_gemini_api_key else "",
        },
        "minimax": {
            "configured": bool(settings.prompt_optimizer_minimax_api_key),
            "model": settings.prompt_optimizer_minimax_model,
            "keyTail": f"…{settings.prompt_optimizer_minimax_api_key[-4:]}" if settings.prompt_optimizer_minimax_api_key else "",
        },
    }


def _agent_headers(agent_name: str = "", agent_run_id: str = "") -> dict[str, str]:
    if not agent_run_id:
        _origin, agent_name, agent_run_id = current_agent_attribution()
    if not agent_run_id:
        return {}
    return {
        "X-Agent-Name": agent_name or "code-agent",
        "X-Agent-Run-Id": agent_run_id,
        "X-Test-Run-Id": agent_run_id,
    }


def _media_label(index: int, kind: str) -> str:
    label = {"image": "Picture", "video": "Video", "audio": "Audio"}[kind]
    return f"<{label} {index}>"


def enrich_prompt(prompt: str, duration: int, ratio: str, media: list[dict[str, Any]]) -> str:
    counters = {"image": 0, "video": 0, "audio": 0}
    bindings = []
    for item in media:
        kind = item["kind"]
        counters[kind] += 1
        bindings.append(f"{_media_label(counters[kind], kind)} = {item.get('name') or kind}; intended role: {item.get('role') or 'reference'}")
    return f"Target duration: exactly {duration} seconds. Target aspect ratio: {ratio}.\nReference bindings:\n" + "\n".join(bindings) + "\n\nUser intent:\n" + prompt.strip()


def _raise_provider_error(response: httpx.Response, provider: str) -> None:
    if response.is_success:
        return
    body = redact_error_text(response.text[:4000])
    raise RuntimeError(f"{provider} HTTP {response.status_code}: {body or 'empty response body'}")


async def call_gemini(*, prompt: str, duration: int, ratio: str, media: list[dict[str, Any]], agent_name: str = "", agent_run_id: str = "") -> dict[str, Any]:
    if settings.llm_channel == "all-in-one":
        return await _call_platform(prompt=prompt, duration=duration, ratio=ratio, media=media, agent_name=agent_name, agent_run_id=agent_run_id)
    content: list[dict[str, Any]] = [{"type": "text", "text": f"{SYSTEM_INSTRUCTION}\n\n{enrich_prompt(prompt, duration, ratio, media)}"}]
    for item in media:
        kind = item["kind"]
        content.append(
            {
                "type": f"{kind}_url",
                f"{kind}_url": {"url": item["url"]},
                "mime_type": item.get("mimeType") or "application/octet-stream",
            }
        )
    payload = {
        "model": settings.prompt_optimizer_gemini_model,
        "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": content}],
        "stream": False,
        "max_tokens": 7000,
    }
    headers = {"Authorization": f"Bearer {settings.prompt_optimizer_gemini_api_key}", "Content-Type": "application/json", **_agent_headers(agent_name, agent_run_id)}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        url = f"{settings.prompt_optimizer_gemini_base_url}/chat/completions"
        if model_gateway.routed("optimizer-gemini"):
            url = model_gateway.base_url() + "/v1/chat/completions"
            headers.update(model_gateway.request_headers())
        response = await client.post(url, headers=headers, json=payload)
    _raise_provider_error(response, "Gemini")
    body = response.json()
    return {
        "prompt": body.get("choices", [{}])[0].get("message", {}).get("content", ""),
        "usage": body.get("usage") or {},
        "requestId": body.get("id") or response.headers.get("x-request-id"),
        "durationMs": round((time.perf_counter() - started) * 1000),
        "requestSnapshot": [{"role": "user", "content": enrich_prompt(prompt, duration, ratio, media)}],
    }


async def create_minimax(*, prompt: str, duration: int, ratio: str, media: list[dict[str, Any]], agent_name: str = "", agent_run_id: str = "") -> dict[str, Any]:
    if settings.llm_channel == "all-in-one":
        raise RuntimeError("MiniMax 专用优化接口已停用，请选择 Gemini")
    content: list[dict[str, Any]] = [{"type": "text", "text": enrich_prompt(prompt, duration, ratio, media)}]
    for item in media:
        kind = item["kind"]
        content.append(
            {
                "type": f"{kind}_url",
                f"{kind}_url": {"url": item["url"]},
                "role": f"reference_{kind}",
            }
        )
    payload = {"model": settings.prompt_optimizer_minimax_model, "content": content, "duration": duration, "ratio": ratio}
    headers = {"Authorization": f"Bearer {settings.prompt_optimizer_minimax_api_key}", "Content-Type": "application/json", **_agent_headers(agent_name, agent_run_id)}
    via_gateway = model_gateway.routed("optimizer-minimax")
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        base = settings.prompt_optimizer_minimax_base_url
        if via_gateway:
            base, gateway_headers = model_gateway.route("optimizer-minimax")
            headers.update(gateway_headers)
        response = await client.post(f"{base}/v2/h3_context_ir", headers=headers, json=payload)
    _raise_provider_error(response, "MiniMax")
    body = response.json()
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"MiniMax HTTP {response.status_code}: response missing task_id; body={redact_error_text(response.text[:4000])}")
    return {"taskId": task_id, "requestId": response.headers.get("x-request-id"), "viaGateway": via_gateway}


async def query_minimax(task_id: str, *, via_gateway: bool, agent_name: str = "", agent_run_id: str = "") -> dict[str, Any]:
    if settings.llm_channel == "all-in-one":
        raise RuntimeError("MiniMax 专用优化接口已停用，请选择 Gemini")
    headers = {"Authorization": f"Bearer {settings.prompt_optimizer_minimax_api_key}", **_agent_headers(agent_name, agent_run_id)}
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        base = settings.prompt_optimizer_minimax_base_url
        if via_gateway:
            base, gateway_headers = model_gateway.route("optimizer-minimax")
            headers.update(gateway_headers)
        response = await client.get(f"{base}/v2/query/video_generation/{task_id}", headers=headers)
    _raise_provider_error(response, "MiniMax")
    task = response.json().get("task") or {}
    return {
        "status": task.get("status") or "running",
        "prompt": (task.get("content") or {}).get("prompt") or "",
        "usage": task.get("usage") or {},
        "error": (task.get("error") or {}).get("message") or "",
        "requestId": response.headers.get("x-request-id"),
    }


class OptimizationCallError(RuntimeError):
    """调用失败仍携带实际请求、响应和用量，交给工单账本持久化。"""

    def __init__(self, cause: Exception, model: str, messages: list[dict], result: dict):
        super().__init__(str(cause))
        self.provider = "all-in-one"
        self.model = model
        self.usage = result.get("usage") or {}
        self.request_id = result.get("requestId") or getattr(cause, "request_id", None)
        self.request_messages = messages
        self.response_text = result.get("prompt") or ""


async def _job_snapshot(key: str, value: dict | None = None) -> dict | None:
    """先持久化冻结输入，再调用供应商；恢复必须复用同一模型、内容和幂等键。"""
    from sqlalchemy import select

    from .database import session_factory
    from .models import GenerationJobModel

    job_id = model_gateway.current_job_id()
    if not job_id:
        return value
    async with session_factory() as db:
        query = select(GenerationJobModel).where(GenerationJobModel.id == job_id, GenerationJobModel.user_id == model_gateway.current_owner())
        row = await db.scalar(query.with_for_update())
        if row is None:
            raise RuntimeError("提示词优化工单不存在或不属于当前用户")
        stored = (row.request or {}).get(key)
        if stored is None and value is not None:
            row.request = {**(row.request or {}), key: value}
            if key == "_optimizationRequest":
                row.idempotency_key = value.get("idempotencyKey")
            await db.commit()
            stored = value
        return stored


async def _call_platform(*, prompt: str, duration: int, ratio: str, media: list[dict[str, Any]], agent_name: str, agent_run_id: str) -> dict[str, Any]:
    from .all_in_one import chat_client, upstream_model
    from .llm_failover import choose_model, record_failure, record_success
    from .llm_policy import LlmContentPolicyError, check_provider_text, completion_options
    from .optimizer_media import content_parts

    snapshot = await _job_snapshot("_optimizationRequest")
    if snapshot is None:
        model = await choose_model(settings.llm_model)
        if model != settings.llm_model and media:
            # Text-only backup must not silently discard multimodal evidence.
            raise RuntimeError("多参考优化主模型暂不可用，请稍后重试；不会将参考素材交给纯文本备用模型")
        content = [{"type": "text", "text": enrich_prompt(prompt, duration, ratio, media)}]
        content.extend(await content_parts(media, model_gateway.current_owner()))
        snapshot = await _job_snapshot(
            "_optimizationRequest",
            {
                "model": model,
                "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": content}],
                "options": completion_options(model, 7000),
                "idempotencyKey": f"aio-{model_gateway.current_job_id()}:prompt-optimization:v1" if model_gateway.current_job_id() else None,
            },
        )
    model, messages = snapshot["model"], snapshot["messages"]
    started = time.perf_counter()
    cached = await _job_snapshot("_optimizationResponse")
    result = cached or {}
    try:
        if cached is None:
            job_id = model_gateway.current_job_id()
            async with chat_client(
                user_id=model_gateway.current_owner(),
                timeout=settings.prompt_optimizer_timeout,
                idempotency_key=snapshot.get("idempotencyKey") or (f"aio-{job_id}:prompt-optimization:v1" if job_id else None),
            ) as client:
                response = await client.chat.completions.create(
                    model=upstream_model(model), messages=messages, extra_headers=_agent_headers(agent_name, agent_run_id), **snapshot["options"]
                )
            result = {
                "prompt": response.choices[0].message.content or "" if response.choices else "",
                "usage": response.usage.model_dump() if response.usage else {},
                "requestId": response.id,
            }
            # 在内容校验、业务记录之前保存响应，崩溃恢复无需再次调用已完成请求。
            result = await _job_snapshot("_optimizationResponse", result)
        check_provider_text(result["prompt"])
        if not result["prompt"].strip():
            raise RuntimeError("文本模型未返回提示词")
    except Exception as exc:
        if cached is None and not isinstance(exc, LlmContentPolicyError) and not (result and not str(result.get("prompt") or "").strip()):
            await record_failure(model)
        raise OptimizationCallError(exc, model, messages, result) from exc
    if cached is None:
        await record_success(model)
    return {
        **result,
        "durationMs": round((time.perf_counter() - started) * 1000),
        "requestSnapshot": messages,
        "provider": "all-in-one",
        "model": model,
    }
