"""Idempotent initial catalog. Never overwrites operator changes."""

import asyncio
import os

from gateway.db import Model, Session
from sqlalchemy import select


async def main():
    rows = []

    def add(name, channel, kind, protocol, caps=None, enabled=True):
        rows.append(
            dict(
                id=name,
                provider_model=name,
                channel=channel,
                kind=kind,
                protocol=protocol,
                capabilities=caps or {},
                enabled=enabled,
                concurrency=4,
            )
        )

    for name in dict.fromkeys(
        [
            os.getenv("LLM_MODEL", "gpt-5.6-sol"),
            "gpt-5.5",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "claude-opus-4-8",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "grok-4.6",
            "kimi-k3",
            "glm-5.2",
            "qwen3.8-max",
        ]
    ):
        add(name, "yinghe-llm", "chat", "anthropic" if name.startswith("claude") else "chat", {"stream": True})
    add("gemini-3.7-flash", "optimizer-gemini", "chat", "chat")
    add("h3-context", "optimizer-minimax", "text", "context")
    rows[-1]["provider_model"] = "MiniMax-H3"
    add("minimax-h3-runninghub", "runninghub", "video", "runninghub")
    rows[-1]["concurrency"] = 2
    for name in ("gpt-image-2", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare"):
        add(name, "yinghe", "image", "image", {"max_images": 15})
    for name in ("doubao-seedance-2.0", "doubao-seedance-2.0-mini", "doubao-seedance-2.0-fast"):
        add(name, "yinghe", "video", "seedance", {"duration": [4, 15], "resolution": ["480p", "720p"]})
    add("MiniMax-H3", "yinghe", "video", "h3", {"duration": [4, 15], "max_images": 6, "resolution": ["768P", "2K"]})
    for name in ("wan3.0-video", "wan3.0-video-prime"):
        add(name, "yinghe", "video", "wan", {"duration": [4, 15]})
    add(
        "kling-v3",
        "yinghe",
        "video",
        "kling",
        {"duration": [3, 15], "note": "Identity element API unverified; first/last frame only"},
        False,
    )
    add("kling-v3-omni", "yinghe", "video", "kling", {"duration": [3, 15], "note": "Historical lab model; disabled"}, False)
    for name in ("veo-3.1-generate-preview", "veo-3.1-fast-generate-preview"):
        add(name, "yseeai", "video", "unified", {"duration": [4, 8], "max_images": 3, "tested_images": 2})
    add(
        "gemini-omni-flash-preview",
        "yseeai",
        "video",
        "unified",
        {"duration": [1, 15], "max_images": 3, "reference_encoding": "base64", "tested_duration": 10},
    )
    add("grok-video-1.5", "toapis", "video", "grok", {"duration": [1, 10]})
    async with Session.begin() as db:
        # New installations use the reviewed catalog installed by Alembic 0006.
        # Do not append and enable the legacy catalog after that migration.
        existing = (await db.scalars(select(Model))).all()
        if any(m.capabilities.get("unified_catalog") for m in existing):
            print("Versioned catalog present; legacy seed skipped")
            return
        for row in rows:
            if not await db.get(Model, row["id"]):
                db.add(Model(**row))
    print(f"Catalog checked: {len(rows)} models")


if __name__ == "__main__":
    asyncio.run(main())
