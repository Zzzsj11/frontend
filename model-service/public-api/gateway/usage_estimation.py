"""Local indicative usage estimates. No token-counting or generation network calls."""

import json
import math
from statistics import median

from sqlalchemy import or_, select

from .db import Job


def text_tokens(payload, policy=None):
    policy = policy or {}

    # Do not count URLs/base64 as language tokens or fetch media just to quote.
    def content(value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "\n".join(content(v) for v in value)
        if isinstance(value, dict):
            return content(value.get("text", value.get("content", "")))
        return ""

    text = "\n".join(content(payload.get(k, "")) for k in ("messages", "input", "system", "prompt"))
    if payload.get("tools"):
        text += json.dumps(payload["tools"], ensure_ascii=False)
    if not text.strip():
        return None
    ascii_count = sum(ord(c) < 128 for c in text)
    return math.ceil(
        ascii_count / float(policy.get("ascii_chars_per_token", 4))
        + (len(text) - ascii_count) * float(policy.get("non_ascii_tokens_per_char", 1.5))
    ) + int(policy.get("message_overhead_tokens", 12))


def resolution(payload):
    value = payload.get("resolution") or (payload.get("metadata") or {}).get("resolution") or payload.get("size") or "1K"
    if "x" in str(value):
        try:
            w, h = [int(x) for x in value.split("x")]
            return "4k" if max(w, h) > 2048 else "2k" if max(w, h) > 1536 else "1k"
        except ValueError:
            pass
    return str(value).lower()


def output_usage(usage):
    if isinstance(usage.get("rawUsage"), dict):
        nested = output_usage(usage["rawUsage"])
        if nested is not None:
            return nested
    for key in ("completion_tokens", "outputTokens", "output_tokens"):
        if usage.get(key) is not None:
            try:
                n = float(usage[key])
                if math.isfinite(n) and n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    return None


async def infer(db, model, route, client, payload, usage):
    usage = dict(usage)
    policy = (route.pricing or {}).get("estimate_policy", {}) if route else {}
    local_input = text_tokens(payload, policy)
    if local_input is None or model.kind not in {"chat", "image"}:
        return usage, {}
    policy = (route.pricing or {}).get("estimate_policy", {}) if route else {}
    generated = []
    samples = []
    overheads = []
    query = (
        select(Job)
        .where(
            Job.model_id == model.id,
            Job.status == "succeeded",
            Job.deleted_at.is_(None),
            or_(
                (Job.origin == "agent_test") & (Job.user_id == "code-agent-acceptance"),
                (Job.client_id == client.id) & (Job.user_id == client.user_id),
            ),
        )
        .order_by(Job.created_at.desc())
        .limit(50)
    )
    if route:
        query = query.where(Job.route_id == route.id)
    for job in (await db.scalars(query)).all() if policy.get("use_history", True) else []:
        if model.kind == "image" and (
            resolution(job.payload) != resolution(payload) or job.payload.get("quality", "auto") != payload.get("quality", "auto")
        ):
            continue
        value = output_usage(job.usage or {})
        if value:
            samples.append(value / max(1, job.payload.get("n", 1)) if model.kind == "image" else value)
        if model.kind == "chat":
            historical_input = (job.usage or {}).get("prompt_tokens", (job.usage or {}).get("input_tokens"))
            counted = text_tokens(job.payload, policy)
            if isinstance(historical_input, (int, float)) and counted:
                overheads.append(max(0, historical_input - counted))
    if "input_tokens" not in usage:
        usage["input_tokens"] = str(math.ceil(local_input + (median(overheads) if overheads else 0)))
        generated.append("input_tokens")
    if "output_tokens" not in usage:
        if model.kind == "chat":
            predicted = median(samples) if samples else policy.get("default_output_tokens", 512)
            cap = payload.get("max_completion_tokens", payload.get("max_output_tokens", payload.get("max_tokens")))
            if cap is not None and type(cap) is int and cap > 0:
                predicted = min(predicted, cap)
        else:
            base = {"low": policy.get("image_low_tokens", 512), "medium": policy.get("image_medium_tokens", 2048)}.get(
                payload.get("quality"), policy.get("image_high_tokens", 8192)
            )
            scale = {"1k": 1, "2k": policy.get("image_2k_multiplier", 2), "4k": policy.get("image_4k_multiplier", 4)}.get(
                resolution(payload), 1
            )
            predicted = (median(samples) if samples else base * scale) * payload.get("n", 1)
        usage["output_tokens"] = str(math.ceil(predicted))
        generated.append("output_tokens")
    if model.kind == "image" and payload.get("images") and "image_tokens" not in usage:
        usage["image_tokens"] = str(len(payload["images"]) * int(policy.get("reference_image_tokens", 1536)))
        if "input_tokens" in generated:
            usage["input_tokens"] = str(int(usage["input_tokens"]) + int(usage["image_tokens"]))
        generated.append("image_tokens")
    return usage, {
        "method": "local_characters_and_matching_history" if samples else "local_characters_and_defaults",
        "automatic_fields": generated,
        "sample_count": len(samples),
        "confidence": "reference_only",
        "notes": [
            "历史输出取中位数；无样本使用可解释默认值",
            "区间为参考值，不是上下限承诺；隐藏提示词、推理Token和参考图复杂度会影响实际用量",
        ],
    }
