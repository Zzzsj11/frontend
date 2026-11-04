"""Model request compatibility and transient text-provider failure classification."""

from __future__ import annotations

import asyncio
import random

from openai import APIConnectionError, APITimeoutError


class TemporaryLlmError(RuntimeError):
    pass


class UncertainLlmError(TemporaryLlmError):
    """保留原工单，禁止在提交或计费不确定时盲目重提。"""

    pass


class LlmContentPolicyError(RuntimeError):
    """供应商明确拒绝输入，不应当作 JSON 损坏或服务故障再次调用。"""

    pass


def completion_options(model: str, max_tokens: int, temperature: float = 0.2) -> dict:
    from .generation_preferences import text_selection

    options = _completion_options(model, max_tokens, temperature)
    selection = text_selection.get() or {}
    if selection.get("channel"):
        options["extra_body"] = {"channel": selection["channel"]}
    return options


def _completion_options(model: str, max_tokens: int, temperature: float = 0.2) -> dict:
    model = model.removesuffix("-all-in-one")
    if model == "gemini-3.8-flash":
        return {"max_completion_tokens": max(8192, max_tokens * 2), "reasoning_effort": "low"}
    if model in {"gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "doubao-seed-2-1-pro-260915"} or model.startswith("gpt-6-astra-"):
        # Reasoning and visible text share the completion budget; avoid unsupported sampling parameters.
        return {"max_completion_tokens": max(8192, max_tokens * 2), "reasoning_effort": "low"}
    return {"max_tokens": max_tokens, "temperature": temperature}


def check_provider_text(text: str) -> None:
    """Some compatible providers send capacity errors inside successful chat responses."""
    stripped = text.strip()
    if not stripped:
        raise TemporaryLlmError("文本模型返回空响应，请稍后重试")
    if len(stripped) > 1000 or stripped.startswith(("{", "[", "```")):
        return
    lower = stripped.lower()
    if ("prompt contains sensitive words" in lower and "prohibited use policy" in lower) or lower.startswith(
        ("the prompt could not be submitted", "your request was blocked due to safety", "prompt blocked due to safety")
    ):
        raise LlmContentPolicyError("文本模型内容审核未通过，请检查本镜描述后重试")
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
