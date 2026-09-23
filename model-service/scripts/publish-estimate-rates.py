"""Import non-cache rate snapshots into route-local quote rules, without enabling generation."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public-api"))
OUT = None


def rate(path, value, factor, unit=1000000, optional=False):
    return {"label": path, "path": path, "cny": str(D(str(value)) * factor), "unit": str(unit), "optional": optional}


def entry(conditions, rates, source):
    return {"conditions": conditions, "rates": rates, "confirmed": True, "source": source}


async def refresh():
    # Fixed trusted endpoints; never print URLs containing API keys.
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as api:
        requests = [
            (
                "yseeai-key-prices.json",
                "https://admin-aigc.yseeai.com/admin-api/router/aiModel/marketplace/byApiKey",
                {"params": {"apiKey": os.environ["YSEEAI_API_KEY"]}},
            ),
            ("toapis-text-prices.json", "https://toapis.cn/api/pricing", {}),
        ]
        documents = {}
        for filename, url, kwargs in requests:
            try:
                response = await api.get(url, **kwargs)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data.get("data"), list):
                    raise ValueError()
                documents[filename] = data
            except Exception:
                raise RuntimeError("Price fetch failed: " + filename) from None
        rows, cursor, seen = [], None, set()
        while True:
            params = {"limit": 100, **({"after": cursor} if cursor else {})}
            try:
                response = await api.get(
                    "https://toapis.cn/v1/pricing", params=params, headers={"Authorization": "Bearer " + os.environ["TOAPIS_API_KEY"]}
                )
                response.raise_for_status()
                data = response.json()
                rows.extend(data["data"])
            except Exception:
                raise RuntimeError("Toapis price fetch failed") from None
            if not data.get("has_more"):
                break
            cursor = data.get("next_after")
            if not cursor or cursor in seen:
                raise RuntimeError("Invalid pricing pagination")
            seen.add(cursor)
        response = await api.get("https://toapis.cn/v1/user/balance", headers={"Authorization": "Bearer " + os.environ["TOAPIS_API_KEY"]})
        if response.status_code != 200:
            raise RuntimeError("Cannot verify Toapis credit unit")
        conversion = D(str(response.json().get("credits_per_usd", 0)))
        if not conversion.is_finite() or conversion <= 0:
            raise RuntimeError("Invalid Toapis credit unit")
        documents["toapis-prices.json"] = {"data": rows, "currency": "USD", "credits_per_usd": str(conversion)}
        for filename, data in documents.items():
            target = OUT / filename
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            temp.chmod(0o600)
            temp.replace(target)


async def main(fresh=False, snapshot_dir=None):
    from gateway.db import Audit, ModelRoute, Session
    from sqlalchemy import select

    global OUT
    OUT = Path(snapshot_dir).resolve()
    if fresh:
        OUT.mkdir(parents=True, exist_ok=True)
        await refresh()
    synced_at = datetime.now(timezone.utc).isoformat()
    y = {r["innerCode"]: r for r in json.loads((OUT / "yseeai-key-prices.json").read_text())["data"]}
    toapis_catalog = json.loads((OUT / "toapis-prices.json").read_text())
    credit_unit = D(toapis_catalog.get("credits_per_usd", "200"))  # Historical snapshot used 200.
    t = {r["id"]: r for r in toapis_catalog["data"]}
    text = {r["model_name"]: r for r in json.loads((OUT / "toapis-text-prices.json").read_text())["data"]}
    async with Session.begin() as db:
        routes = (await db.scalars(select(ModelRoute).where(ModelRoute.deleted_at.is_(None)))).all()
        for route in routes:
            rules = []
            if route.supplier == "yseeai":
                model = y[route.provider_model]
                root = model["billingRule"]
                factor = D(str(model["discount"])) * D("6.9")
                variants = root.get("scenarioRules") or root.get("tiers") or [root]
                for v in variants:
                    conditions = {}
                    if v.get("inputThresholdK") is not None:
                        conditions["input_max"] = str(D(v["inputThresholdK"]) * 1000)
                    if v.get("inputMode") in ("无输入视频", "含输入视频"):
                        conditions["has_video_input"] = v["inputMode"] == "含输入视频"
                    resolutions = v.get("resolution", "").split("/")
                    if v.get("pricePerSecond"):
                        rates = [rate("seconds", v["pricePerSecond"], factor, 1)]
                    else:
                        rates = [
                            rate(path, v[key], factor)
                            for path, key in [("input_tokens", "inputPricePerMillion"), ("output_tokens", "outputPricePerMillion")]
                            if v.get(key) is not None and D(v[key]) != 0
                        ]
                    for surcharge in root.get("surcharges", []):
                        path = {"generated_images": "images"}.get(surcharge["metricKey"], surcharge["metricKey"])
                        rates.append(
                            rate(
                                path,
                                surcharge["unitPrice"],
                                factor * D(str(surcharge.get("multiplier") or 1)),
                                surcharge["unitSize"],
                                path == "claude_web_search_requests",
                            )
                        )
                    for resolution in resolutions:
                        rules.append(
                            entry(
                                {**conditions, **({"resolution": resolution} if resolution else {})},
                                rates,
                                "英和账户费率快照；USD/CNY=6.9",
                            )
                        )
            elif route.supplier == "toapis":
                factor = credit_unit * D("0.035")  # USD目录 -> 供应商积分 -> CNY，不使用外汇汇率。
                if route.protocol == "chat":
                    v = text[route.provider_model]
                    rates = [
                        rate("input_tokens", D(str(v["model_ratio"])) * 2, factor),
                        rate("output_tokens", D(str(v["model_ratio"])) * 2 * D(str(v["completion_ratio"])), factor),
                    ]
                    rules.append(entry({}, rates, "Toapis 文本目录参考价；1000积分=35元"))
                else:
                    for v in t[route.provider_model]["prices"]:
                        if v["group"] != "default" or v.get("pricing_period"):
                            continue
                        c = {
                            k: val
                            for k, val in v.get("conditions", {}).items()
                            if k in ("resolution", "quality", "has_video_input", "input_image_count")
                            or (k == "duration" and v["charge_type"] == "per_request")
                        }
                        path = {
                            "request": "requests",
                            "output_seconds": "seconds",
                            "total_tokens": "total_tokens",
                            "text_input_tokens": "input_tokens",
                        }[v["price_basis"]]
                        rates = [rate(path, v["unit_price"], factor, 1000000 if v["unit"] == "1m_tokens" else 1)]
                        if v.get("image_token_prices") or v.get("input_unit_price") or v.get("minimum_charge_usd"):
                            # No silent partial quote for unsupported supplementary charges.
                            continue
                        rules.append(entry(c, rates, "Toapis 当前Key生效价；1000积分=35元"))
            if not rules and route.pricing.get("dashboard_estimate_rules"):
                rules = route.pricing["dashboard_estimate_rules"]
            raw = (
                {"billingRule": y[route.provider_model]["billingRule"], "discount": y[route.provider_model]["discount"]}
                if route.supplier == "yseeai"
                else text[route.provider_model]
                if route.protocol == "chat"
                else t[route.provider_model]
            )
            version = hashlib.sha256(
                json.dumps({"raw": raw, "rules": rules, "credits_per_usd": str(credit_unit)}, sort_keys=True).encode()
            ).hexdigest()[:16]
            source_url = (
                "https://admin-aigc.yseeai.com/model-marketplace"
                if route.supplier == "yseeai"
                else "https://toapis.com/zh-TW/dashboard/pricing"
            )
            prior = route.pricing
            route.pricing = {
                **route.pricing,
                "synced_estimate_rules": rules,
                "estimate_rules": prior.get("estimate_rules", []) if prior.get("estimate_manual_override") else rules,
                "estimate_version": prior.get("estimate_version") if prior.get("estimate_manual_override") else version,
                "supplier_price_snapshot": {
                    "raw": raw,
                    "source_url": source_url,
                    "synced_at": synced_at,
                    "currency": "USD",
                    "conversion": {"usd_cny": "6.9"}
                    if route.supplier == "yseeai"
                    else {"credits_per_usd": str(credit_unit), "credits": "1000", "cny": "35"},
                },
            }
            db.add(
                Audit(
                    id=__import__("uuid").uuid4().hex,
                    actor="code-agent",
                    action="pricing.estimate_import",
                    target=route.id,
                    detail={
                        "rules": len(rules),
                        "version": version,
                        "before": prior.get("supplier_price_snapshot"),
                        "after": route.pricing["supplier_price_snapshot"],
                    },
                )
            )
            print(route.id, len(rules))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--snapshot-dir", type=Path, required=True, help="Explicit price snapshot input/output directory")
    parser.add_argument("--env-file", type=Path, help="Explicit private runtime configuration; inherited variables take precedence")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        if not args.env_file.is_file():
            parser.error("Environment file not found")
        load_dotenv(args.env_file, override=False)
    if not os.getenv("DATABASE_URL"):
        parser.error("Set the target DATABASE_URL explicitly (or use --env-file)")
    asyncio.run(main(args.refresh, args.snapshot_dir))
