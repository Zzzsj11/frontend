"""Model request compatibility and transient text-provider failure classification."""

from __future__ import annotations

import asyncio
import random

from openai import APIConnectionError, APITimeoutError


class TemporaryLlmError(RuntimeError):
    pass


def completion_options(model: str, max_tokens: int, temperature: float = 0.2) -> dict:
    if model == "gpt-6-astra" or model.startswith("gpt-6-astra-"):
        # Reasoning and visible text share the completion budget; Astra rejects temperature.
        return {"max_completion_tokens": max(8192, max_tokens * 2), "reasoning_effort": "low"}
    return {"max_tokens": max_tokens, "temperature": temperature}


def check_provider_text(text: str) -> None:
    """Some compatible providers send capacity errors inside successful chat responses."""
    stripped = text.strip()
    if len(stripped) > 1000 or stripped.startswith(("{", "[", "```")):
        return
    lower = stripped.lower()
    if any(
        value in lower
        for value in (
            "temporarily unable to respond to this volume",
            "too many requests",
            "rate limit exceeded",
            "upstream request timeout",
            "service overloaded",
            "模型繁忙",
            "请求过于频繁",
        )
    ):
        raise TemporaryLlmError("文本模型服务繁忙或限流，请稍后重试")
    if any(value in lower for value in ("未授权模型", "model_not_found", "not authorized to access")):
        raise RuntimeError("当前文本模型未获供应商授权，请联系管理员检查模型配置")


def is_transient_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in (408, 429) or 500 <= status < 600
    if isinstance(exc, (TemporaryLlmError, APIConnectionError, APITimeoutError, TimeoutError)):
        return True
    return any(value in str(exc).lower() for value in ("upstream connect error", "upstream request timeout", "connection reset by peer", "connection error.", "tls_error"))


async def retry_delay(exc: Exception, attempt: int) -> None:
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("retry-after", "")
    try:
        delay = min(30.0, max(0.0, float(header)))
    except (TypeError, ValueError):
        delay = min(15.0, 2.0 * 2**attempt) + random.uniform(0, 1)
    await asyncio.sleep(delay)


def outline_contract(payload: dict) -> str:
    """Promote the application-owned schema above free-form user story requirements."""
    counts = payload["counts"]
    groups = payload.get("schema", {}).get("wardrobeGroups", [])
    fields = "shots、wardrobeGroups" if groups else "shots"
    return (
        f"\n应用输出契约：顶层必须且只能包含 {fields}。shots 必须恰好 {counts['total']} 条，"
        f"其中 t=e 恰好 {counts['empty']} 条、t=c 恰好 {counts['character']} 条，i 从 0 连续编号。"
        + (f"wardrobeGroups 为独立顶层数组，必须完整输出 {len(groups)} 组，字段、覆盖区间与人物 ID 严格遵循 schema，禁止省略。" if groups else "")
        + "八字段限制仅针对 shots 内的每条镜头，不限制顶层服装分组。输出前自行核对所有顶层字段、条数和类型配额。"
    )
