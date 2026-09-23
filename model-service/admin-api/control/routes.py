"""Control-plane route management; no upstream credentials or network calls."""

import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .billing import Rate
from .db import Audit, Job, Model, ModelRoute, Session


class EstimatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ascii_chars_per_token: float = Field(default=4, gt=0, le=100)
    non_ascii_tokens_per_char: float = Field(default=1.5, gt=0, le=10)
    message_overhead_tokens: int = Field(default=12, ge=0, le=100000)
    default_output_tokens: int = Field(default=512, ge=1, le=1000000)
    use_history: bool = True
    image_low_tokens: int = Field(default=512, ge=1, le=1000000)
    image_medium_tokens: int = Field(default=2048, ge=1, le=1000000)
    image_high_tokens: int = Field(default=8192, ge=1, le=1000000)
    image_2k_multiplier: float = Field(default=2, gt=0, le=100)
    image_4k_multiplier: float = Field(default=4, gt=0, le=100)
    reference_image_tokens: int = Field(default=1536, ge=0, le=1000000)
    cost_multiplier: Decimal = Field(default=Decimal(1), gt=0, le=1000)
    fixed_cny: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    minimum_cny: Decimal = Field(default=Decimal(0), ge=0, le=1000000)
    range_low: float = Field(default=0.5, ge=0, le=1)
    range_high: float = Field(default=1.5, ge=1, le=100)


class EstimateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conditions: dict = Field(default_factory=dict)
    rates: list[Rate] = Field(min_length=1, max_length=20)
    confirmed: bool = True
    source: str = Field(default="管理员配置", max_length=1000)


class EstimateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: EstimatePolicy = Field(default_factory=EstimatePolicy)
    rules: list[EstimateRule] = Field(max_length=100)


class RoutePatch(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    concurrency: int | None = Field(default=None, ge=1, le=1000)


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=160)
    review_note: str = Field(min_length=10, max_length=2000)
    parameters_checked: bool
    result_checked: bool
    usage_checked: bool
    capabilities: dict | None = None
    pricing: dict | None = None


def view(row):
    return {
        k: getattr(row, k)
        for k in (
            "id",
            "model_id",
            "supplier",
            "provider_model",
            "protocol",
            "enabled",
            "priority",
            "concurrency",
            "verification",
            "capabilities",
            "pricing",
        )
    }


def router_for(admin):
    router = APIRouter(prefix="/admin/routes")

    @router.put("/{rid}/estimate-pricing")
    async def estimate_pricing(rid: str, body: EstimateConfig, actor=Depends(admin)):
        config = body.model_dump(mode="json")
        allowed = {"resolution", "quality", "has_video_input", "input_image_count", "duration", "input_max", "usage_required"}
        for rule in config["rules"]:
            if set(rule["conditions"]) - allowed:
                raise HTTPException(422, "Unsupported price condition")
            for key, value in rule["conditions"].items():
                if key == "usage_required" and value not in ("total_tokens", "input_tokens", "output_tokens"):
                    raise HTTPException(422, "Invalid required usage metric")
                if key == "has_video_input" and type(value) is not bool:
                    raise HTTPException(422, "has_video_input must be boolean")
                if key in {"resolution", "quality"} and (not isinstance(value, str) or len(value) > 30):
                    raise HTTPException(422, "Invalid specification condition")
                if key in {"input_max", "input_image_count", "duration"}:
                    try:
                        number = Decimal(str(value).removesuffix("s"))
                        if not number.is_finite() or number < 0 or number > 10**12:
                            raise ValueError()
                    except (InvalidOperation, ValueError):
                        raise HTTPException(422, "Invalid numeric price condition") from None
            for rate in rule["rates"]:
                if rate["path"] not in {
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "image_tokens",
                    "images",
                    "requests",
                    "seconds",
                    "input_seconds",
                    "claude_web_search_requests",
                }:
                    raise HTTPException(422, "Unsupported estimate quantity")
        async with Session.begin() as db:
            row = await db.get(ModelRoute, rid, with_for_update=True)
            if not row or row.deleted_at:
                raise HTTPException(404)
            before = dict(row.pricing or {})
            row.pricing = {
                **before,
                "synced_estimate_rules": before.get("synced_estimate_rules", before.get("estimate_rules", [])),
                "estimate_rules": config["rules"],
                "estimate_policy": config["policy"],
                "estimate_manual_override": True,
                "estimate_version": "manual-" + uuid.uuid4().hex,
            }
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="route.estimate_pricing",
                    target=rid,
                    detail={"before": before, "after": row.pricing},
                )
            )
            return view(row)

    @router.get("")
    async def listing(actor=Depends(admin)):
        async with Session() as db:
            rows = (
                await db.scalars(
                    select(ModelRoute).where(ModelRoute.deleted_at.is_(None)).order_by(ModelRoute.model_id, ModelRoute.priority)
                )
            ).all()
            return [view(row) for row in rows]

    @router.patch("/{rid}")
    async def patch(rid: str, body: RoutePatch, actor=Depends(admin)):
        async with Session.begin() as db:
            row = await db.get(ModelRoute, rid)
            if not row or row.deleted_at:
                raise HTTPException(404)
            changes = body.model_dump(exclude_none=True)
            if changes.get("enabled") and row.verification != "passed":
                raise HTTPException(409, "Complete attributed live verification before enabling this route")
            enabled_changed = "enabled" in changes and changes["enabled"] != row.enabled
            for k, v in changes.items():
                setattr(row, k, v)
            await db.flush()
            if enabled_changed:
                model = await db.get(Model, row.model_id)
                model.enabled = bool(
                    await db.scalar(
                        select(ModelRoute.id)
                        .where(ModelRoute.model_id == model.id, ModelRoute.enabled.is_(True), ModelRoute.deleted_at.is_(None))
                        .limit(1)
                    )
                )
            db.add(Audit(id=uuid.uuid4().hex, actor=actor, action="route.update", target=rid, detail=changes))
            return view(row)

    @router.post("/{rid}/verify")
    async def verify(rid: str, body: Verification, actor=Depends(admin)):
        if not all((body.parameters_checked, body.result_checked, body.usage_checked)):
            raise HTTPException(422, "Review requested parameters, actual output and recorded usage before verification")
        async with Session.begin() as db:
            row = await db.get(ModelRoute, rid, with_for_update=True)
            job = await db.get(Job, body.job_id)
            if not row or row.deleted_at:
                raise HTTPException(404)
            if (
                not job
                or job.deleted_at
                or job.route_id != rid
                or job.status != "succeeded"
                or job.origin != "agent_test"
                or job.agent_name != "code-agent"
                or not job.agent_run_id
                or not job.test_run_id
                or not job.usage
            ):
                raise HTTPException(409, "A successful attributed acceptance job with recorded usage on this exact route is required")
            if any(job.routing_snapshot.get(k) != getattr(row, k) for k in ("channel", "provider_model", "protocol")):
                raise HTTPException(409, "Route changed since this acceptance job; verify the current route")
            if job.routing_snapshot.get("capabilities", {}) != row.capabilities:
                raise HTTPException(409, "Route capabilities changed since this acceptance job")
            row.verification = "passed"
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="route.verify",
                    target=rid,
                    detail={
                        **body.model_dump(),
                        "agent_run_id": job.agent_run_id,
                        "route": {k: getattr(row, k) for k in ("channel", "provider_model", "protocol")},
                    },
                )
            )
            # Verification and enablement are separate; no generation or billing publication here.
            return view(row)

    return router
