"""Provision the approved 19-model/two-supplier catalog; keep unverified routes disabled."""

import asyncio
import importlib.util
import json
from pathlib import Path

from gateway.db import Model, ModelRoute, Session
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "gemini-3.1-pro-preview": "gemini-3.1-pro-preview-official",
    "seedream-5.0": "doubao-seedream-5-0",
    "dreamina-seedance-2.5": "seedance-2-5",
    "dreamina-seedance-2.0": "seedance-2",
    "dreamina-seedance-2.0-fast": "seedance-2-fast",
    "dreamina-seedance-2.0-mini": "seedance-2-mini",
    "gemini-omni-flash-preview": "gemini-omni-flash-preview-official",
    "wan3.0-video-sg": "wan3.0-video",
    "wan3.0-video-prime-sg": "wan3.0-video-prime",
}


async def main():
    spec = importlib.util.spec_from_file_location("overseas", ROOT / "scripts/import-overseas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = {x["innerCode"]: x for x in json.loads((ROOT / "catalog/yseeai-2026-09-21.json").read_text())["models"]}
    chosen = json.loads((ROOT / "catalog/selected-models.json").read_text())
    allowed = {n for names in chosen.values() for n in names}
    async with Session.begin() as db:
        for model in (await db.scalars(select(Model))).all():
            if model.id not in allowed:
                model.enabled = False
        for kind, names in chosen.items():
            for name in names:
                original = module.definition(catalog[name])
                model = await db.get(Model, name)
                if not model:
                    model = Model(
                        id=name,
                        provider_model=name,
                        channel=original["channel"],
                        protocol=original["protocol"],
                        kind=kind,
                        enabled=False,
                        concurrency=4,
                        capabilities={},
                    )
                    db.add(model)
                if not model.capabilities.get("unified_catalog"):
                    model.enabled = False
                    model.capabilities = {**original["capabilities"], "unified_catalog": True, "catalog_selected": True}
                for supplier in ("yseeai", "toapis"):
                    rid = supplier + "--" + name
                    if await db.get(ModelRoute, rid):
                        continue
                    channel = original["channel"] if supplier == "yseeai" else "toapis"
                    protocol = original["protocol"] if supplier == "yseeai" else "chat" if kind == "chat" else "toapis-" + kind
                    caps = dict(original["capabilities"])
                    if supplier == "toapis":
                        caps["native_endpoint"] = (
                            "/v1/chat/completions"
                            if kind == "chat"
                            else "/v1/" + ("images" if kind == "image" else "videos") + "/generations"
                        )
                    db.add(
                        ModelRoute(
                            id=rid,
                            model_id=name,
                            supplier=supplier,
                            channel=channel,
                            provider_model=name if supplier == "yseeai" else ALIASES.get(name, name),
                            protocol=protocol,
                            enabled=False,
                            priority=10 if supplier == "yseeai" else 20,
                            concurrency=2,
                            verification="pending",
                            capabilities=caps,
                            pricing={},
                        )
                    )
    print("Provisioned 19 canonical models and 38 supplier routes; verification required before public enablement")


if __name__ == "__main__":
    asyncio.run(main())
