"""Reconcile platform text failures before permitting another paid request."""

from types import SimpleNamespace
from typing import Any

from .all_in_one import query_task
from .llm_policy import UncertainLlmError, is_transient_error, retry_delay
from .model_gateway import current_owner


def platform_job_id(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    for value in (body, body.get("error"), body.get("detail")):
        if isinstance(value, dict) and isinstance(value.get("job_id"), str):
            return value["job_id"]
    return None


async def reconcile(exc: Exception) -> dict[str, Any] | None:
    """返回已完成原响应；仅确认未受理且零结算时允许返回 None 重试。"""
    jid = platform_job_id(exc)
    if not jid:
        if getattr(exc, "status_code", None) == 429:
            return None
        raise UncertainLlmError("文本请求提交状态待核对，已停止自动重提以避免重复费用") from exc
    try:
        body = await query_task("chat", jid, user_id=current_owner())
    except Exception as query_error:
        raise UncertainLlmError(f"文本请求状态查询失败，请核对平台工单 {jid}，暂不重复提交") from query_error
    billing = body.get("billing") or {}
    exc.platform_job_id = jid
    exc.platform_usage = {"platformBilling": billing, **(body.get("usage") or {})}
    result = body.get("result")
    if body.get("status", "").upper() == "SUCCEEDED" and isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict) and isinstance(choices[0].get("message"), dict):
            return result
    message = str(body.get("error") or "").lower()
    unsubmitted = "no supplier request submitted" in message or "concurrency limit" in message or "admission limit" in message
    if unsubmitted and billing.get("status") == "settled" and str(billing.get("points")) in {"0", "0.000000", "0.0"}:
        return None
    if billing.get("status") == "settled" and str(billing.get("points")) in {"0", "0.000000", "0.0"} and message.startswith(("provider http 401:", "provider http 403:")):
        error = RuntimeError(f"文本供应商鉴权或额度异常，本次未计费，请联系管理员检查（平台工单 {jid}）")
        error.platform_job_id = jid
        error.platform_usage = exc.platform_usage
        raise error from exc
    error = UncertainLlmError(f"文本请求未交付，计费状态待核对（平台工单 {jid}）；请勿重复提交")
    error.platform_job_id = jid
    error.platform_usage = {"platformBilling": billing, **(body.get("usage") or {})}
    raise error from exc


async def create_stream(client, payload, *, key, on_retry):
    """只重试建流前已确认未受理的请求；已输出的流不自动重放。"""
    for attempt in range(3):
        try:
            return await client.chat.completions.create(**payload, extra_headers={"Idempotency-Key": f"{key}-{attempt}"})
        except Exception as exc:
            if not is_transient_error(exc) and getattr(exc, "status_code", None) != 409:
                raise
            recovered = await reconcile(exc)
            if recovered is not None:

                async def restored():
                    choice = recovered["choices"][0]
                    yield SimpleNamespace(
                        id=recovered.get("id"), usage=recovered.get("usage"), choices=[SimpleNamespace(delta=SimpleNamespace(content=choice["message"].get("content")))]
                    )

                return restored()
            if attempt == 2:
                raise
            await on_retry(exc)
            from .text_admission import cooldown

            await cooldown()
            await retry_delay(exc, attempt)
    raise AssertionError("unreachable")
