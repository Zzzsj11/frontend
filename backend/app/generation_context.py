"""User, job and attribution context for generation requests."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from openai import AsyncOpenAI as OpenAIClient

from .agent_attribution import attribution_context, current_agent_attribution, current_test_run_id

_owner: ContextVar[str] = ContextVar("generation_owner", default="")
_agent: ContextVar[tuple[str, str] | None] = ContextVar("generation_agent", default=None)
_job: ContextVar[str] = ContextVar("generation_job", default="")


def set_owner(user_id: str) -> None:
    _owner.set(user_id)


def current_owner() -> str:
    return _owner.get()


def current_job_id() -> str:
    return _job.get()


def current_agent() -> tuple[str, str] | None:
    return _agent.get()


async def run_with_context(job: Any, runner: Any) -> Any:
    snapshot = getattr(job, "request", None) or {}
    if snapshot.get("_modelGateway"):
        raise RuntimeError("历史模型网关已退役，请使用原工单记录核对")
    from .config import settings

    all_in_one = snapshot.get("_provider") == "all-in-one" or str(snapshot.get("model") or "").endswith("-all-in-one")
    all_in_one = all_in_one or (job.kind not in {"image", "video"} and any(model.endswith("-all-in-one") for model in (settings.llm_model, settings.general_outline_llm_model)))
    text_job = settings.llm_channel in {"yseeai", "toapis", "all-in-one"} and job.kind in {"chat", "ass_outline", "general_outline", "ass_segment_retry", "storyboard_line"}
    if not all_in_one and not text_job:
        return await runner(job)
    from .database import session_factory
    from .models import GenerationJobModel

    async with session_factory() as db:
        row = await db.get(GenerationJobModel, job.id)
        attrs = (row.agent_name or "", row.agent_run_id or "") if row else ("", "")
    owner_token = _owner.set(job.user_id or "")
    agent_token = _agent.set(attrs)
    job_token = _job.set(str(job.id or ""))
    from .generation_preferences import text_selection

    selection_token = text_selection.set(snapshot.get("_textSelection"))
    try:
        with attribution_context(row.generation_origin if row else "business", *attrs, row.test_run_id if row else ""):
            return await runner(job)
    finally:
        _owner.reset(owner_token)
        _agent.reset(agent_token)
        _job.reset(job_token)
        text_selection.reset(selection_token)


class AsyncOpenAI(OpenAIClient):
    """Preserve Agent attribution for direct text channels."""

    def __init__(self, **kwargs: Any):
        from .config import settings

        direct_text = settings.llm_channel in {"yseeai", "toapis"} and str(kwargs.get("base_url") or "").rstrip("/") == settings.llm_base_url.rstrip("/")
        if direct_text:
            _, name, run = current_agent_attribution()
            if _agent.get() is not None:
                name, run = _agent.get() or ("", "")
            if run:
                kwargs["default_headers"] = {
                    **kwargs.get("default_headers", {}),
                    "X-Agent-Name": name or "code-agent",
                    "X-Agent-Run-Id": run,
                    "X-Test-Run-Id": current_test_run_id() or run,
                }
        super().__init__(**kwargs)
