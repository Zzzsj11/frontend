"""Replay one stored outline request without touching the user's project or global model.

Run from backend with PYTHONPATH=.; all calls are attributed, persisted and bounded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid

from openai import AsyncOpenAI
from sqlalchemy import select

from app.config import settings
from app.database import session_factory
from app.models import GenerationJobModel, LlmCallLogModel, UserModel, utcnow
from app.storyboard_prompt import _check_general_outline_v2, _extract_json
from app.token_usage import add_llm_call_log, add_token_usage


async def run(args):
    headers = {"X-Agent-Name": "code-agent", "X-Agent-Run-Id": args.run_id, "X-Test-Run-Id": args.run_id}
    async with session_factory() as db:
        source = (
            (
                await db.execute(
                    select(LlmCallLogModel)
                    .where(LlmCallLogModel.generation_job_id == args.source_job, LlmCallLogModel.operation.in_(["general_story_outline_v2", "general_story_outline_v2_failed"]))
                    .order_by(LlmCallLogModel.created_at)
                )
            )
            .scalars()
            .first()
        )
        if source is None:
            raise ValueError("Source general outline call not found")
        owner = (await db.execute(select(UserModel).where(UserModel.username == args.owner, UserModel.deleted_at.is_(None)))).scalar_one()
        messages = source.request_messages[:2]
        payload, _ = json.JSONDecoder().raw_decode(messages[1]["content"])
        if args.enforce_contract:
            from app.llm_policy import outline_contract

            messages = [dict(message) for message in messages]
            messages[0]["content"] += outline_contract(payload)
        if args.repair_job:
            previous = (await db.execute(select(LlmCallLogModel).where(LlmCallLogModel.generation_job_id == args.repair_job))).scalars().one()
            try:
                _check_general_outline_v2(
                    _extract_json(previous.response_text),
                    expected_count=payload["counts"]["total"],
                    empty_count=payload["counts"]["empty"],
                    character_count=payload["counts"]["character"],
                    role_ids=[item["id"] for item in payload["characters"]],
                )
            except ValueError as exc:
                messages.extend([{"role": "assistant", "content": previous.response_text}, {"role": "user", "content": f"结构错误：{exc}。修正并重新输出完整纯 JSON。"}])
            else:
                raise ValueError("Previous output already valid; repair unnecessary")
        job = GenerationJobModel(
            id="job-eval-" + uuid.uuid4().hex,
            user_id=owner.id,
            kind="llm_evaluation",
            status="running",
            phase="evaluating",
            generation_origin="agent_test",
            agent_name="code-agent",
            agent_run_id=args.run_id,
            started_at=utcnow(),
            request={"model": args.model, "sourceJobId": args.source_job, "agentHeaders": headers, "maxCompletionTokens": 8192, "reasoningEffort": "low"},
        )
        db.add(job)
        await db.commit()
        job_id, owner_id = job.id, owner.id
    usage, response_id, text, error, finish = {}, None, "", "", None
    started = time.perf_counter()
    try:
        async with AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=180, max_retries=0, default_headers=headers) as client:
            response = await client.chat.completions.create(model=args.model, messages=messages, max_completion_tokens=8192, reasoning_effort="low")
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        response_id = response.id
        text = response.choices[0].message.content or ""
        finish = response.choices[0].finish_reason
        body = _extract_json(text)
        _check_general_outline_v2(
            body,
            expected_count=payload["counts"]["total"],
            empty_count=payload["counts"]["empty"],
            character_count=payload["counts"]["character"],
            role_ids=[item["id"] for item in payload["characters"]],
        )
    except Exception as exc:
        error = str(exc)[:1500]
    duration = round((time.perf_counter() - started) * 1000)
    async with session_factory() as db:
        add_llm_call_log(
            db,
            operation="outline_model_evaluation",
            provider="openai-compatible",
            model=args.model,
            usage=usage,
            user_id=owner_id,
            generation_job_id=job_id,
            request_id=response_id,
            status="error" if error else "ok",
            error=error,
            duration_ms=duration,
            request_messages=messages,
            response_text=text,
        )
        add_token_usage(
            db,
            operation="outline_model_evaluation",
            provider="openai-compatible",
            model=args.model,
            usage=usage,
            user_id=owner_id,
            generation_job_id=job_id,
            request_id=response_id,
        )
        job = await db.get(GenerationJobModel, job_id)
        job.status = "failed" if error else "succeeded"
        job.phase = "finished"
        job.finished_at = utcnow()
        job.error = error or None
        job.result = {"durationMs": duration, "finishReason": finish, "usage": usage, "valid": not error, "responseLength": len(text)}
        await db.commit()
    print(
        json.dumps(
            {
                "jobId": job_id,
                "runId": args.run_id,
                "model": args.model,
                "durationMs": duration,
                "finishReason": finish,
                "usage": usage,
                "valid": not error,
                "error": error,
                "responseLength": len(text),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-job", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--owner", default="admin")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--enforce-contract", action="store_true")
    parser.add_argument("--repair-job")
    asyncio.run(run(parser.parse_args()))
