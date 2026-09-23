"""Only operator-configured destinations; callers never choose an upstream URL."""

import os

DEFAULTS = {
    "yinghe": "https://api-aigc.fzyinghe.com",
    "yinghe-llm": "https://ai-aigc.fzyinghe.com",
    "yseeai": "https://api-aigc.yseeai.com",
    "yseeai-llm": "https://ai-aigc.yseeai.com",
    "optimizer-gemini": "https://api.ommapi.top",
    "optimizer-minimax": "https://api.minimaxi.com",
    "runninghub": "https://www.runninghub.cn",
    "toapis": "https://toapis.cn",
}
PATHS = {
    "image": "/image/generation/tasks",
    "toapis-image": "/v1/images/generations",
    "toapis-video": "/v1/videos/generations",
    "image-sync": "/v1/images/generations",
    "responses": "/v1/responses",
    "dreamactor": "/video/generation/tasks",
    "seedance-unified": "/video/generation/tasks",
    "seedance": "/v3/video/tasks",
    "unified": "/video/generation/tasks",
    "kling": "/video/generation/tasks",
    "h3": "/video/generation/tasks",
    "wan": "/video/generation/tasks",
    "grok": "/v1/videos/generations",
    "chat": "/v1/chat/completions",
    "anthropic": "/v1/messages",
    "context": "/v2/h3_context_ir",
    "runninghub": "/task/openapi/create",
}


def config(channel):
    prefix = channel.upper().replace("-", "_")
    base = os.environ.get(prefix + "_BASE_URL", DEFAULTS.get(channel, "")).rstrip("/")
    key = os.environ.get(prefix + "_API_KEY", os.environ.get("YSEEAI_API_KEY", "") if channel == "yseeai-llm" else "")
    if not base or not key:
        raise ValueError(f"Channel {channel} is not configured")
    return base, key


def headers(job):
    _, key = config(job.channel)
    result = {"Authorization": "Bearer " + key, "x-api-key": key, "Idempotency-Key": job.id}
    if job.protocol == "anthropic":
        result["anthropic-version"] = "2023-06-01"
    if job.agent_run_id:
        result.update({"X-Agent-Name": job.agent_name, "X-Agent-Run-Id": job.agent_run_id, "X-Test-Run-Id": job.test_run_id})
    return result


def unwrap(body):
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    return data.get("task") if isinstance(data.get("task"), dict) else data


def task_id(body):
    data = unwrap(body)
    return str(data.get("task_id") or data.get("taskId") or data.get("id") or data.get("interaction_id") or "")


def task_state(body):
    data = unwrap(body)
    status = str(data.get("status") or data.get("task_status") or data.get("state") or "").lower()
    if status in {"succeeded", "succeed", "success", "completed", "done", "ready"}:
        return "succeeded"
    if status in {"failed", "fail", "error", "cancelled", "canceled"}:
        return "failed"
    return "running"


def native(job):
    # Query shape remains compatible with existing MV adapters.
    if job.status == "succeeded":
        return job.result.get("native", job.provider_response)
    if job.protocol == "context":
        return {
            "task": {
                "task_id": job.id,
                "status": "failed" if job.status in {"failed", "manual_review"} else "running",
                "error": {"message": job.error},
            }
        }
    if job.protocol == "runninghub":
        return {"taskId": job.id, "status": "FAILED" if job.status in {"failed", "manual_review"} else "RUNNING", "errorMessage": job.error}
    failed = job.status in {"failed", "manual_review"}
    state = "failed" if failed else "processing"
    data = {
        "id": job.id,
        "taskId": job.id,
        "task_id": job.id,
        "status": state,
        "task_status": state,
        "progress": 10 if not job.provider_id else 50,
        "failReason": job.error,
        "message": job.error,
        "error": {"message": job.error},
        "usage": job.usage,
    }
    return {"code": 200, "data": data, **data}
