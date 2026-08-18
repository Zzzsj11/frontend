from __future__ import annotations

import asyncio
import time
from typing import Any

from .llm_comparison import CHAT_TEST_MODEL_MAP, call_chat_model
from .storyboard_prompt import generate_general_story_outline
from .token_usage import normalize_usage


async def compare_general_outlines(*, models: list[str], config: dict[str, Any], selected_humans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(3)

    async def run(model: str) -> dict[str, Any]:
        profile = CHAT_TEST_MODEL_MAP[model]
        calls: list[dict[str, Any]] = []

        async def call_override(client, messages, max_tokens, *, usage_records, operation, prompt_key="", prompt_version=0):
            started = time.perf_counter()
            snapshot = [dict(message) for message in messages]
            try:
                async with semaphore:
                    text, usage, request_id = await call_chat_model(
                        model=model,
                        protocol=profile.protocol,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=max_tokens,
                    )
                duration_ms = round((time.perf_counter() - started) * 1000)
                record = {
                    "operation": operation,
                    "status": "ok",
                    "durationMs": duration_ms,
                    "requestMessages": snapshot,
                    "responseText": text,
                    "usage": usage,
                    "requestId": request_id,
                    "promptKey": prompt_key,
                    "promptVersion": prompt_version,
                }
                usage_records.append(record)
                calls.append(record)
                return text
            except Exception as exc:
                duration_ms = round((time.perf_counter() - started) * 1000)
                record = {
                    "operation": operation,
                    "status": "error",
                    "durationMs": duration_ms,
                    "requestMessages": snapshot,
                    "responseText": "",
                    "usage": {},
                    "requestId": getattr(exc, "request_id", None),
                    "error": str(exc)[:2000],
                    "promptKey": prompt_key,
                    "promptVersion": prompt_version,
                }
                usage_records.append(record)
                calls.append(record)
                raise

        started = time.perf_counter()
        try:
            outline = await generate_general_story_outline(
                config=config,
                selected_humans=selected_humans,
                call_override=call_override,
            )
            usage = normalize_usage(outline.get("usage") or {})
            return {
                "model": model,
                "name": profile.name,
                "protocol": profile.protocol,
                "status": "ok",
                "error": "",
                "totalDurationMs": round((time.perf_counter() - started) * 1000),
                "attempts": len(calls),
                "calls": calls,
                "usage": usage,
                "shots": outline["shots"],
            }
        except Exception as exc:
            raw_usage = {
                "input_tokens": sum(normalize_usage(item.get("usage"))["inputTokens"] for item in calls),
                "output_tokens": sum(normalize_usage(item.get("usage"))["outputTokens"] for item in calls),
            }
            return {
                "model": model,
                "name": profile.name,
                "protocol": profile.protocol,
                "status": "error",
                "error": str(exc)[:2000],
                "totalDurationMs": round((time.perf_counter() - started) * 1000),
                "attempts": len(calls),
                "calls": calls,
                "usage": normalize_usage(raw_usage),
                "shots": [],
            }

    return list(await asyncio.gather(*(run(model) for model in models)))
