"""Read-only release readiness. Healthy processes are not proof of billable model readiness."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "public-api"))


async def inspect():
    from gateway.channels import config
    from gateway.credits import amount
    from gateway.db import Model, ModelRoute, PricingRule, Session
    from sqlalchemy import select

    async with Session() as db:
        models = {m.id: m for m in (await db.scalars(select(Model).where(Model.deleted_at.is_(None)))).all()}
        routes = (await db.scalars(select(ModelRoute).where(ModelRoute.deleted_at.is_(None)))).all()
        rules = (await db.scalars(select(PricingRule).where(PricingRule.deleted_at.is_(None)))).all()
    enabled = [r for r in routes if r.enabled and models.get(r.model_id) and models[r.model_id].enabled]
    errors = []
    if not enabled:
        errors.append("No enabled model/supplier route; catalog and quotes only")
    for route in enabled:
        if route.verification != "passed":
            errors.append(route.id + ": verification pending")
        try:
            config(route.channel)
        except ValueError:
            errors.append(route.id + ": channel credentials missing")
        candidates = [route.pricing] + [r.config for r in rules if r.model_id == route.model_id]
        if not any(
            p.get("confirmed") and amount(p.get("reserve_points", 0)) > 0 and (p.get("rates") or p.get("actual_cny_path"))
            for p in candidates
        ):
            errors.append(route.id + ": verified billing/reservation rule missing")
    return {
        "generation_ready": not errors,
        "models": len(models),
        "routes": len(routes),
        "enabled_routes": len(enabled),
        "routes_with_quotes": sum(bool(r.pricing.get("estimate_rules")) for r in routes),
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--catalog-only", action="store_true", help="Report generation blockers without requiring generation enablement")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        if not args.env_file.is_file():
            parser.error("Environment file not found")
        load_dotenv(args.env_file, override=False)
    if not os.getenv("DATABASE_URL"):
        parser.error("Explicit DATABASE_URL or --env-file required")
    result = asyncio.run(inspect())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["generation_ready"] or args.catalog_only else 1)
