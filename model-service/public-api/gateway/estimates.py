"""Read-only quotes. Never submit, reserve credits, fetch media, or create a job."""

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from .channels import config as channel_config
from .credits import amount, dimensions, measured_points, rule
from .db import Model, ModelRoute, Session
from .image_parameters import toapis_image
from .schemas import ImageCreate
from .usage_estimation import infer, resolution


def quantities(values):
    if not isinstance(values, dict):
        raise HTTPException(422, "estimate_usage must be an object")
    result = {}
    for key, value in values.items():
        try:
            n = Decimal(str(value))
            if isinstance(value, bool) or not n.is_finite() or n < 0 or n > 10**12:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise HTTPException(422, f"Invalid estimated quantity: {key}") from None
        result[key] = str(n)
    return result


def matches(condition, payload, usage):
    for key, wanted in condition.items():
        if key == "usage_required":
            if wanted not in usage:
                return False
        elif key == "input_max":
            if "input_tokens" not in usage or Decimal(usage["input_tokens"]) > Decimal(str(wanted)):
                return False
        elif key == "has_video_input":
            if bool(payload.get("videos")) != wanted:
                return False
        elif key == "input_image_count":
            if len(payload.get("images") or []) != wanted:
                return False
        elif key == "duration":
            if str(payload.get(key, "")).removesuffix("s") != str(wanted).removesuffix("s"):
                return False
        elif str(payload.get(key, "")).lower() != str(wanted).lower():
            return False
    return True


async def estimate(payload, client, expected_kind=None):
    mid = payload.get("model")
    if not isinstance(mid, str):
        raise HTTPException(422, "model required")
    for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
        if payload.get(key) is not None and (type(payload[key]) is not int or not 0 < payload[key] <= 10**9):
            raise HTTPException(422, f"{key} must be a positive integer")
    if not isinstance(payload.get("images", []), list) or not isinstance(payload.get("metadata", {}), dict):
        raise HTTPException(422, "images must be an array and metadata must be an object")
    if not isinstance(payload.get("quality", "auto"), str):
        raise HTTPException(422, "quality must be a string")
    usage = quantities(payload.get("estimate_usage", {}))
    async with Session() as db:
        model = await db.get(Model, mid)
        if not model or model.deleted_at or (not model.enabled and not model.capabilities.get("catalog_selected")):
            raise HTTPException(404, "Unknown model")
        if expected_kind and model.kind != expected_kind:
            raise HTTPException(422, "Incorrect endpoint for this model kind")
        if client.allowed_models and mid not in client.allowed_models:
            raise HTTPException(403, "Model not allowed for this client")
        routes = list(
            (
                await db.scalars(
                    select(ModelRoute)
                    .where(ModelRoute.model_id == mid, ModelRoute.deleted_at.is_(None))
                    .order_by(ModelRoute.enabled.desc(), ModelRoute.priority, ModelRoute.id)
                )
            ).all()
        )
        # Same preferred enabled route as generation; disabled routes are only indicative catalogue quotes.
        available_routes = []
        for candidate in routes:
            if candidate.enabled and candidate.verification == "passed":
                try:
                    channel_config(candidate.channel)
                except ValueError:
                    continue
                available_routes.append(candidate)
        route = available_routes[0] if available_routes else routes[0] if routes else None
        pricing = route.pricing if route else {}
        data = dict(payload)
        if route and route.protocol == "toapis-image":
            from pydantic import ValidationError

            try:
                normalized = toapis_image(route, ImageCreate(**payload))
            except ValidationError:
                raise HTTPException(422, "Invalid canonical image parameters") from None
            data.update(size=normalized["size"], resolution=normalized.get("resolution") or normalized["metadata"]["resolution"])
            data["quality"] = normalized.get("quality", "auto")
        if not data.get("resolution"):
            data["resolution"] = "720p" if model.kind == "video" else resolution(payload)
        if model.kind == "image":
            n = payload.get("n", 1)
            if type(n) is not int or not 1 <= n <= 4:
                raise HTTPException(422, "n must be an integer from 1 to 4")
            usage["images"] = usage["requests"] = str(n)
            if not payload.get("images"):
                usage.setdefault("image_tokens", "0")
        if model.kind == "video" and payload.get("duration") is not None:
            duration = payload["duration"]
            limits = model.capabilities.get("duration", [1, 15])
            if type(duration) is not int or not limits[0] <= duration <= limits[1]:
                raise HTTPException(422, "duration outside model limits")
            usage["seconds"] = str(duration)
        usage, estimation = await infer(db, model, route, client, data, usage)
        if "input_tokens" in usage and "output_tokens" in usage:
            usage.setdefault("total_tokens", str(Decimal(usage["input_tokens"]) + Decimal(usage["output_tokens"])))
        usage = quantities(usage)
        candidates = pricing.get("estimate_rules", [])
        override = await rule(db, mid, dimensions(model, data))
        if override and override.get("confirmed") and override.get("rates") and not pricing.get("estimate_manual_override"):
            candidates = []
        selected = next((r for r in candidates if matches(r.get("conditions", {}), data, usage)), None)
        if candidates and selected is None:
            return {
                "object": "price_estimate",
                "model": mid,
                "status": "needs_parameters",
                "missing": ["matching pricing conditions"],
                "amount_cny": None,
                "generated": False,
            }
        config = selected or (pricing if pricing.get("rates") else override)
        if not config or not config.get("confirmed"):
            raise HTTPException(503, "Verified estimation rates have not been configured")
        missing = [r["path"] for r in config.get("rates", []) if not r.get("optional") and r["path"] not in usage]
        measured = measured_points(SimpleNamespace(pricing_snapshot=config, usage=usage)) if not missing else None
        points, breakdown = measured if measured else (None, [])
        base_cny = str(points / 100) if points is not None else None
        policy = pricing.get("estimate_policy", {})
        if points is not None:
            adjusted_cny = points / 100 * Decimal(str(policy.get("cost_multiplier", 1))) + Decimal(str(policy.get("fixed_cny", 0)))
            points = amount(max(adjusted_cny, Decimal(str(policy.get("minimum_cny", 0)))) * 100)

        return {
            "object": "price_estimate",
            "model": mid,
            "status": "estimated" if points is not None else "needs_usage",
            "generated": False,
            "charged": False,
            "normalized_parameters": {k: data[k] for k in ("size", "resolution", "quality") if k in data},
            "generation_available": bool(model.enabled and (route is None or available_routes)),
            "amount_cny": str(points / 100) if points is not None else None,
            "points": str(points) if points is not None else None,
            "missing": missing,
            "estimated_usage": usage,
            "breakdown": breakdown,
            "adjustments": {
                "base_cny": base_cny,
                "multiplier": str(policy.get("cost_multiplier", 1)),
                "fixed_cny": str(policy.get("fixed_cny", 0)),
                "minimum_cny": str(policy.get("minimum_cny", 0)),
            },
            "rate_version": pricing.get("estimate_version", config.get("id")),
            "estimation": estimation,
            "reference_range_cny": {
                "low": str(points / 100 * Decimal(str(policy.get("range_low", 0.5)))),
                "high": str(points / 100 * Decimal(str(policy.get("range_high", 1.5)))),
            }
            if points is not None and any(r["path"] in estimation.get("automatic_fields", []) for r in config.get("rates", []))
            else None,
            "assumptions": ["无缓存计价", "用量由调用方提供或本地粗估，最终以实际生成用量结算", "报价不锁定路由或费率"],
        }
