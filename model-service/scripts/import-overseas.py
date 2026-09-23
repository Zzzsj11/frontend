"""Import reviewed overseas catalog without overwriting existing operator routes."""

import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def definition(item):
    name = item["innerCode"]
    path = (item.get("apiPath") or "").split("|")[0]
    kind = {"TEXT": "chat", "IMAGE": "image", "VIDEO": "video"}[item["modelType"]]
    protocol = {
        "/v1/messages": "anthropic",
        "/v1/chat/completions": "chat",
        "/v1/responses": "responses",
        "/v1/images/generations": "image-sync",
        "/image/generation/tasks": "image",
        "/v3/video/tasks": "seedance",
    }.get(path)
    configured = bool(path and item.get("apiBaseUrl"))
    if not protocol:
        protocol = (
            "anthropic"
            if kind == "chat" and "claude" in name
            else "dreamactor"
            if name.startswith("dreamactor")
            else "wan"
            if name.startswith("wan")
            else "seedance-unified"
            if name.startswith("dreamina")
            else "unified"
        )
    caps = {
        "vendor": item["groupName"],
        "source": "yseeai-overseas-2026-09-21",
        "documentation_configured": configured,
        "verification": "not_tested",
        "native_endpoint": path,
    }
    if kind == "chat":
        caps["stream"] = True
    if protocol in ("seedance", "seedance-unified"):
        caps.update(duration=[4, 15], resolution=["480p", "720p"])
    if name.startswith("veo"):
        caps.update(duration=[4, 8], max_images=3)
    if name.startswith("gemini-omni"):
        caps.update(duration=[1, 15], max_images=3, reference_encoding="base64")
    return dict(
        id="yseeai--" + name,
        provider_model=name,
        channel="yseeai-llm" if item.get("apiBaseUrl") == "https://ai-aigc.yseeai.com" or kind == "chat" else "yseeai",
        kind=kind,
        protocol=protocol,
        enabled=configured,
        concurrency=2,
        capabilities=caps,
    )


async def main():
    from gateway.db import Model, Session

    rows = json.loads((ROOT / "catalog/yseeai-2026-09-21.json").read_text())["models"]
    async with Session.begin() as db:
        for item in rows:
            row = definition(item)
            if not await db.get(Model, row["id"]):
                db.add(Model(**row))
    print(f"Overseas catalog: {len(rows)} entries; incomplete provider routes remain disabled")


if __name__ == "__main__":
    asyncio.run(main())
