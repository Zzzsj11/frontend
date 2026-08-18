from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import settings
from .token_usage import normalize_usage


@dataclass(frozen=True)
class ChatTestModel:
    code: str
    name: str
    protocol: str = "openai"


CHAT_TEST_MODELS = (
    ChatTestModel("gpt-5.5", "GPT 5.5"),
    ChatTestModel("gpt-5.6-sol", "GPT 5.6 Sol"),
    ChatTestModel("gpt-5.6-terra", "GPT 5.6 Terra"),
    ChatTestModel("claude-opus-4-8", "Claude Opus 4.8", "anthropic"),
    ChatTestModel("deepseek-v4-flash", "DeepSeek V4 Flash"),
    ChatTestModel("deepseek-v4-pro", "DeepSeek V4 Pro"),
    ChatTestModel("grok-4.6", "Grok 4.6"),
    ChatTestModel("kimi-k3", "Kimi K3"),
    ChatTestModel("glm-5.2", "GLM 5.2"),
    ChatTestModel("qwen3.8-max", "Qwen 3.8 Max"),
)
CHAT_TEST_MODEL_MAP = {item.code: item for item in CHAT_TEST_MODELS}


def _anthropic_messages_url() -> str:
    base = settings.llm_base_url.rstrip("/")
    return f"{base}/messages" if base.endswith("/v1") else f"{base}/v1/messages"


async def _call_openai(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, Any, str | None]:
    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=120)
    response = await client.chat.completions.create(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    return response.choices[0].message.content or "", response.usage, response.id


async def _call_anthropic(model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, Any, str | None]:
    system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
    conversation = [item for item in messages if item["role"] != "system"]
    payload: dict[str, Any] = {"model": model, "messages": conversation, "temperature": temperature, "max_tokens": max_tokens}
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            _anthropic_messages_url(),
            headers={"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
    return text, body.get("usage") or {}, body.get("id")


async def call_chat_model(*, model: str, protocol: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> tuple[str, Any, str | None]:
    """单次模型调用；业务流程通过显式 model/protocol 注入测试模型，不改全局默认配置。"""
    caller = _call_anthropic if protocol == "anthropic" else _call_openai
    return await caller(model, messages, temperature, max_tokens)


async def compare_chat_models(*, models: list[str], system_prompt: str, prompt: str, temperature: float, max_tokens: int) -> list[dict[str, Any]]:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    semaphore = asyncio.Semaphore(3)
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]

    async def run(model: str) -> dict[str, Any]:
        profile = CHAT_TEST_MODEL_MAP[model]
        started = time.perf_counter()
        try:
            async with semaphore:
                text, usage, request_id = await call_chat_model(
                    model=model,
                    protocol=profile.protocol,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            normalized = normalize_usage(usage)
            return {
                "model": model,
                "name": profile.name,
                "protocol": profile.protocol,
                "status": "ok",
                "text": text,
                "error": "",
                "durationMs": round((time.perf_counter() - started) * 1000),
                "requestId": request_id,
                "usage": normalized,
            }
        except Exception as exc:
            return {
                "model": model,
                "name": profile.name,
                "protocol": profile.protocol,
                "status": "error",
                "text": "",
                "error": str(exc)[:2000],
                "durationMs": round((time.perf_counter() - started) * 1000),
                "requestId": getattr(exc, "request_id", None),
                "usage": normalize_usage({}),
            }

    return list(await asyncio.gather(*(run(model) for model in models)))
