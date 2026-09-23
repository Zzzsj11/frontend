"""Price rows verified in the authenticated dashboard, separately from the empty Key API response."""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public-api"))

# model: resolution, has_video_input, USD / 1M total_tokens, indicative USD / second.
ROWS = {
    "dreamina-seedance-2.0": [
        ("4k", False, "3.71", "0.7242"),
        ("4k", True, "2.29", "0.3776"),
        ("480p", False, "6.57", "0.0598"),
        ("480p", True, "4", "0.0354"),
        ("720p", False, "6.57", "0.1338"),
        ("720p", True, "4", "0.0795"),
        ("1080p", False, "7.29", "0.3339"),
        ("1080p", True, "4.43", "0.2161"),
    ],
    "dreamina-seedance-2.0-fast": [
        ("480p", False, "3.96", "0.0122"),
        ("480p", True, "2.36", "0.007007"),
        ("720p", False, "3.96", "0.0829"),
        ("720p", True, "2.36", "0.0444"),
    ],
}


def rate(path, price, unit):
    return {"label": path, "path": path, "unit": str(unit), "cny": str(Decimal(price) * 200 * Decimal("0.035"))}


async def main():
    from gateway.db import Audit, ModelRoute, Session

    async with Session.begin() as db:
        for model, rows in ROWS.items():
            row = await db.get(ModelRoute, "toapis--" + model)
            rules = []
            for resolution, has_video, tokens, seconds in rows:
                conditions = {"resolution": resolution, "has_video_input": has_video}
                rules.append(
                    {
                        "confirmed": True,
                        "conditions": {**conditions, "usage_required": "total_tokens"},
                        "source": "登录态价格工作台：total_tokens计价",
                        "rates": [rate("total_tokens", tokens, 1000000)],
                    }
                )
                rates = [rate("seconds", seconds, 1)]
                if has_video:
                    rates.append(rate("input_seconds", seconds, 1))
                rules.append(
                    {
                        "confirmed": True,
                        "conditions": conditions,
                        "source": "登录态价格工作台：按秒预算参考价（低至），不保证最终费用",
                        "rates": rates,
                    }
                )
            snapshot = {
                "source_url": "https://toapis.com/zh-TW/dashboard/pricing",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "group": "default",
                "group_multiplier": "1",
                "currency": "USD",
                "credit_conversion": "1000 credits = CNY35",
                "rows": [
                    {"resolution": r, "has_video_input": v, "usd_per_million_total_tokens": t, "indicative_usd_per_second": s}
                    for r, v, t, s in rows
                ],
            }
            before = dict(row.pricing or {})
            row.pricing = {
                **before,
                "dashboard_price_snapshot": snapshot,
                "dashboard_estimate_rules": rules,
                "synced_estimate_rules": rules,
            }
            if not before.get("estimate_manual_override"):
                row.pricing = {**row.pricing, "estimate_rules": rules, "estimate_version": "dashboard-" + uuid.uuid4().hex}
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor="code-agent",
                    action="pricing.dashboard_verified",
                    target=row.id,
                    detail={"before": before, "after": row.pricing},
                )
            )
            print(model, len(rows), "verified dashboard prices stored")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        if not args.env_file.is_file():
            parser.error("Environment file not found")
        load_dotenv(args.env_file, override=False)
    if not os.getenv("DATABASE_URL"):
        parser.error("Set the target DATABASE_URL explicitly (or use --env-file)")
    asyncio.run(main())
