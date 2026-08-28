from __future__ import annotations

import time
from typing import Any

import httpx

from .agent_attribution import current_agent_attribution
from .config import settings
from .error_logging import redact_error_text

PROVIDERS = ("gemini", "minimax")
RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
MEDIA_LIMITS = {"image": 9, "video": 3, "audio": 3}

SYSTEM_INSTRUCTION = """You are an expert MiniMax H3 full-reference Ref2VA prompt editor.
Analyze every supplied text, image, video, and audio reference directly. Return only the final English prompt, with no Markdown fence or commentary. Use exactly these six section names in order: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music. Keep reference labels stable, use exact shot timing matching the requested duration, and explicitly describe composition, subjects, environment, actions, camera, synchronized physical sound, and referenced music."""


def provider_status() -> dict[str, dict[str, Any]]:
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
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "max_tokens": 7000,
    }
    headers = {"Authorization": f"Bearer {settings.prompt_optimizer_gemini_api_key}", "Content-Type": "application/json", **_agent_headers(agent_name, agent_run_id)}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        response = await client.post(f"{settings.prompt_optimizer_gemini_base_url}/chat/completions", headers=headers, json=payload)
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
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        response = await client.post(f"{settings.prompt_optimizer_minimax_base_url}/v2/h3_context_ir", headers=headers, json=payload)
    _raise_provider_error(response, "MiniMax")
    body = response.json()
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"MiniMax HTTP {response.status_code}: response missing task_id; body={redact_error_text(response.text[:4000])}")
    return {"taskId": task_id, "requestId": response.headers.get("x-request-id")}


async def query_minimax(task_id: str, *, agent_name: str = "", agent_run_id: str = "") -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {settings.prompt_optimizer_minimax_api_key}", **_agent_headers(agent_name, agent_run_id)}
    async with httpx.AsyncClient(timeout=settings.prompt_optimizer_timeout) as client:
        response = await client.get(f"{settings.prompt_optimizer_minimax_base_url}/v2/query/video_generation/{task_id}", headers=headers)
    _raise_provider_error(response, "MiniMax")
    task = response.json().get("task") or {}
    return {
        "status": task.get("status") or "running",
        "prompt": (task.get("content") or {}).get("prompt") or "",
        "usage": task.get("usage") or {},
        "error": (task.get("error") or {}).get("message") or "",
        "requestId": response.headers.get("x-request-id"),
    }
