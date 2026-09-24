import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import timedelta
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .adapters import video_payload
from .channels import PATHS, config, headers, native
from .credits import job_bill, reserve, settle
from .db import Client, Job, Model, Session, now
from .errors import describe
from .estimates import estimate
from .image_parameters import toapis_image
from .portal import router as portal_router
from .queue import capacity, heartbeat, lock, update
from .routing import resolve, snapshot
from .schemas import ImageCreate, VideoCreate
from .security import attribution, authenticate, owner
from .status import public_status
from .usage_normalization import normalize_usage
from .validation import validate

app = FastAPI(title="Company Model API", version="1.0.0")


@app.middleware("http")
async def bounded_body(request: Request, call_next):
    limit = int(os.getenv("MAX_REQUEST_BYTES", str(32 * 1024 * 1024)))
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            return JSONResponse({"detail": "Request body too large; use original public URLs"}, status_code=413)
        content.extend(chunk)
    request._body = bytes(content)
    return await call_next(request)


class CreateJob(BaseModel):
    model: str
    payload: dict[str, Any] = Field(description="Native provider body; model is enforced by registry")


@app.post("/v1/pricing/estimate")
async def price_estimate(payload: dict, client: Client = Depends(authenticate)):
    return await estimate(payload, client)


def public_job(row):
    return {
        "id": row.id,
        "model": row.model_id,
        "kind": row.kind,
        "status": public_status(row.status),
        "provider_task_id": row.provider_id,
        "result": row.result,
        "usage": row.usage,
        "billing": job_bill(row),
        "error": row.error,
        "origin": row.origin,
        "agent_name": row.agent_name,
        "agent_run_id": row.agent_run_id,
        "created_at": row.created_at.isoformat(),
    }


@app.get("/health")
async def health():
    async with Session() as db:
        await db.execute(select(Model.id).limit(1))
    return {"ok": True}


@app.get("/v1/models")
async def models(client: Client = Depends(authenticate)):
    async with Session() as db:
        rows = (await db.scalars(select(Model).where(Model.enabled.is_(True), Model.deleted_at.is_(None)))).all()
    return {
        "object": "list",
        "data": [
            {"id": m.id, "object": "model", "kind": m.kind, "channel": m.channel, "capabilities": m.capabilities}
            for m in rows
            if not client.allowed_models or m.id in client.allowed_models
        ],
    }


async def enqueue(body, request, client, channel=None, path=None, expected_kind=None):
    uid = owner(request)
    attrs = attribution(request, client)
    key = request.headers.get("idempotency-key", "")
    if not key or len(key) > 200:
        raise HTTPException(400, "Idempotency-Key required (maximum 200 characters)")
    async with Session() as db:
        model = await db.get(Model, body.model)
        if channel and (not model or model.channel != channel):
            model = await db.scalar(select(Model).where(Model.provider_model == body.model, Model.channel == channel))
        acceptance = client.require_agent and attrs["agent_name"] == "code-agent" and request.headers.get("x-test-supplier")
        if not model or (not model.enabled and not (acceptance and model.capabilities.get("unified_catalog"))) or model.deleted_at:
            raise HTTPException(400, "Unknown or disabled model")
        if expected_kind and model.kind != expected_kind:
            raise HTTPException(422, "Incorrect endpoint for this model kind")
        if client.allowed_models and model.id not in client.allowed_models:
            raise HTTPException(403, "Model not allowed for this client")
        if channel and (model.channel != channel or PATHS[model.protocol] != path):
            raise HTTPException(400, "Model/channel/protocol mismatch")
        model, route = await resolve(db, model, request, client)
        try:
            config(model.channel)
        except ValueError:
            raise HTTPException(503, "Channel not configured") from None
        payload = dict(body.payload)
        payload["model_name" if model.protocol == "kling" else "model"] = model.provider_model
        if model.kind == "chat":
            if model.protocol == "responses":
                if not payload.get("input"):
                    raise HTTPException(422, "input required")
            elif not isinstance(payload.get("messages"), list) or not payload["messages"]:
                raise HTTPException(422, "messages required")
        else:
            if not any(payload.get(k) for k in ("prompt", "content", "input", "workflow", "nodeInfoList", "video_url")):
                raise HTTPException(422, "prompt, content or input required")
            duration = payload.get("duration", payload.get("parameters", {}).get("duration"))
            limits = model.capabilities.get("duration")
            if limits and (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration != int(duration)
                or not limits[0] <= duration <= limits[1]
            ):
                raise HTTPException(422, f"duration must be an integer in {limits}")
            images = payload.get("images", [])
            if isinstance(images, list) and len(images) > model.capabilities.get("max_images", 100):
                raise HTTPException(422, "Too many reference images")
        validate(model, payload)
        signature = hashlib.sha256(json.dumps({"model": model.id, "payload": payload, **attrs}, sort_keys=True).encode()).hexdigest()
        await lock(db)
        existing = await db.scalar(select(Job).where(Job.client_id == client.id, Job.user_id == uid, Job.idempotency_key == key))
        if existing:
            if existing.request_hash != signature:
                raise HTTPException(409, "Idempotency key already used with different input or attribution")
            return existing, False
        pending = await db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.client_id == client.id, Job.status.in_(["queued", "preparing", "submitting", "running", "archiving"]))
        )
        if pending >= int(os.getenv("MAX_PENDING_PER_CLIENT", "1000")):
            raise HTTPException(429, "Pending task limit reached")
        job = Job(
            id="job-" + uuid.uuid4().hex,
            client_id=client.id,
            user_id=uid,
            model_id=model.id,
            kind=model.kind,
            channel=model.channel,
            protocol=model.protocol,
            route_id=route.id if route else None,
            routing_snapshot=snapshot(route),
            payload=payload,
            request_hash=signature,
            idempotency_key=key,
            **attrs,
        )
        await reserve(db, client, job, model)
        db.add(job)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(select(Job).where(Job.client_id == client.id, Job.user_id == uid, Job.idempotency_key == key))
            if not existing or existing.request_hash != signature:
                raise HTTPException(409, "Concurrent idempotency conflict") from None
            return existing, False
        return job, True


@app.post("/v1/videos", status_code=202)
async def create_video(body: VideoCreate, request: Request, client: Client = Depends(authenticate)):
    if body.estimate_only:
        return JSONResponse(await estimate(body.model_dump(), client, "video"))
    async with Session() as db:
        model = await db.get(Model, body.model)
        if not model or model.kind != "video":
            raise HTTPException(422, "Unknown video model")
        model, _ = await resolve(db, model, request, client)
        payload = video_payload(model, body)
    job, _ = await enqueue(CreateJob(model=body.model, payload=payload), request, client, expected_kind="video")
    return public_job(job)


@app.post("/v1/images", status_code=202)
async def create_image(body: ImageCreate, request: Request, client: Client = Depends(authenticate)):
    if body.estimate_only:
        return JSONResponse(await estimate(body.model_dump(), client, "image"))
    payload = body.model_dump(exclude={"images", "estimate_only", "estimate_usage", "resolution"})
    if body.images:
        payload["image"] = body.images[0] if len(body.images) == 1 else body.images
    async with Session() as db:
        model = await db.get(Model, body.model)
        if model:
            model, _ = await resolve(db, model, request, client)
        if body.resolution and model and model.protocol != "toapis-image":
            raise HTTPException(422, "Explicit resolution is supported only by canonical ToAPIs image routes; use size for this route")
        if model and model.provider_model.startswith("wan"):
            content = [{"text": body.prompt}] + [{"image": url} for url in body.images]
            payload = {
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": body.size, "n": body.n, "watermark": False, "enable_interleave": False},
            }
        elif model and model.protocol == "toapis-image":
            payload = toapis_image(model, body)
        elif model and model.protocol == "image-sync":
            payload.pop("quality", None)
            payload["response_format"] = "url"
    job, _ = await enqueue(CreateJob(model=body.model, payload=payload), request, client, expected_kind="image")
    return public_job(job)


@app.post("/v1/jobs", status_code=202)
async def create_job(body: CreateJob, request: Request, client: Client = Depends(authenticate)):
    async with Session() as db:
        model = await db.get(Model, body.model)
        if model and model.kind == "chat":
            raise HTTPException(422, "Use /v1/chat/completions for chat")
    job, _ = await enqueue(body, request, client)
    return public_job(job)


async def get_owned(jid, request, client):
    uid = owner(request)
    async with Session() as db:
        job = await db.scalar(select(Job).where(Job.id == jid, Job.client_id == client.id, Job.user_id == uid, Job.deleted_at.is_(None)))
    if not job:
        raise HTTPException(404, "Task not found")
    return job


@app.get("/v1/jobs/{jid}")
async def get_job(jid: str, request: Request, client: Client = Depends(authenticate)):
    return public_job(await get_owned(jid, request, client))


@app.post("/v1/messages")
@app.post("/v1/responses")
@app.post("/v1/chat/completions")
async def chat(payload: dict, request: Request, client: Client = Depends(authenticate)):
    if "estimate_only" in payload and not isinstance(payload["estimate_only"], bool):
        raise HTTPException(422, "estimate_only must be a boolean")
    if payload.get("estimate_only"):
        return await estimate(payload, client, "chat")
    payload = {k: v for k, v in payload.items() if k not in {"estimate_only", "estimate_usage"}}
    job, fresh = await enqueue(CreateJob(model=payload.get("model", ""), payload=payload), request, client, expected_kind="chat")
    if not fresh:
        if job.status == "succeeded" and not payload.get("stream"):
            return job.result
        raise HTTPException(409, {"message": "Request already accepted; inspect job", "job_id": job.id})
    async with Session.begin() as db:
        await lock(db)
        row = await db.get(Job, job.id)
        if not await capacity(db, row):
            row.status, row.error = "failed", "Concurrency limit reached"
            await settle(db, row, 0, "system", "并发限制，未提交渠道，释放预占", "unsubmitted:" + row.id, {})
            limited = True
        else:
            row.status, row.lease_until = "submitting", now() + timedelta(seconds=120)
            limited = False
    if limited:
        raise HTTPException(429, "Concurrency limit reached")
    body = dict(job.payload)
    if body.get("stream"):
        if job.protocol == "chat":
            body["stream_options"] = {**body.get("stream_options", {}), "include_usage": True}
    base, _ = config(job.channel)
    beat = asyncio.create_task(heartbeat(job.id))
    upstream = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20))
    try:
        response = await upstream.send(
            upstream.build_request("POST", base + PATHS[job.protocol], json=body, headers=headers(job)), stream=bool(body.get("stream"))
        )
        response.raise_for_status()
    except asyncio.CancelledError:
        beat.cancel()
        await upstream.aclose()
        await asyncio.shield(update(job.id, status="manual_review", error="Chat connection cancelled; submission may be uncertain"))
        raise
    except Exception as exc:
        beat.cancel()
        failed = isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500
        reason = "Chat submission unavailable; billing may be uncertain"
        if failed:
            try:
                await exc.response.aread()
                reason = describe(exc.response.json(), job.channel)
            except ValueError:
                reason = "Provider rejected the chat request"
            reason = f"Provider HTTP {exc.response.status_code}: {reason}"
        await upstream.aclose()
        await update(job.id, status="failed" if failed else "manual_review", error=reason)
        raise HTTPException(502, {"message": reason, "job_id": job.id}) from None
    if not body.get("stream"):
        try:
            result = response.json()
            if result.get("error") or result.get("code", 200) not in (0, 200, "200"):
                reason = describe(result, job.channel)
                await update(
                    job.id, status="failed", error=reason, usage=normalize_usage(result.get("usage", {})), provider_response=result
                )
                raise HTTPException(502, {"message": reason, "job_id": job.id})
            await update(
                job.id, status="succeeded", result=result, usage=normalize_usage(result.get("usage", {})), provider_response=result
            )
            return result
        finally:
            beat.cancel()
            await upstream.aclose()

    async def events():
        raw_usage = {}
        finished = False
        try:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    content = line[6:]
                    if content == "[DONE]":
                        finished = True
                    else:
                        try:
                            data = json.loads(content)
                            if data.get("type") == "message_stop":
                                finished = True
                            if data.get("type") == "response.completed":
                                finished = True
                                raw_usage.update(data.get("response", {}).get("usage", {}))
                            if data.get("usage"):
                                raw_usage = {**raw_usage, **data["usage"]}
                            if data.get("message", {}).get("usage"):
                                raw_usage = {**raw_usage, **data["message"]["usage"]}
                        except ValueError:
                            pass
                yield line + "\n"
        finally:
            beat.cancel()
            await response.aclose()
            await upstream.aclose()
            await update(
                job.id,
                status="succeeded" if finished else "manual_review",
                usage=normalize_usage(raw_usage),
                error=None if finished else "Stream interrupted; usage may be incomplete",
            )

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Job-Id": job.id})


@app.post("/providers/runninghub/openapi/v2/media/upload/binary")
async def runninghub_upload(request: Request, file: UploadFile, client: Client = Depends(authenticate)):
    uid = owner(request)
    attribution(request, client)
    data = await file.read(50 * 1024 * 1024 + 1)
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Upload exceeds 50 MiB")
    from .storage import get_storage, put_image_with_thumbnail, safe_key

    prefix = f"clients/{client.id}/users/{uid}/references"
    if (file.content_type or "").startswith("image/"):
        stored, thumb = await put_image_with_thumbnail(safe_key(prefix, file.filename or "image.png"), data, file.content_type)
    else:
        stored = await get_storage().put_bytes(safe_key(prefix, file.filename or "reference.bin"), data, file.content_type)
        thumb = None
    base, key = config("runninghub")
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.post(
            base + "/openapi/v2/media/upload/binary",
            headers={"Authorization": "Bearer " + key},
            files={"file": (file.filename or "reference.bin", data, file.content_type)},
        )
        response.raise_for_status()
        body = response.json()
    body["archived_reference"] = {"url": stored, "thumbnail_url": thumb}
    return body


@app.post("/providers/{channel}/{path:path}", status_code=200)
async def native_create(channel: str, path: str, payload: dict, request: Request, client: Client = Depends(authenticate)):
    path = "/" + path
    if path in {"/v3/assets", "/v3/assets/detail"}:
        from .auxiliary import assets

        return await assets(channel, path, payload, request, client)
    if channel == "runninghub" and path == "/openapi/v2/query":
        job = await get_owned(str(payload.get("taskId", "")), request, client)
        if job.channel != channel:
            raise HTTPException(404)
        return native(job)
    workflow_path = None
    if channel == "runninghub":
        payload = {k: v for k, v in payload.items() if k != "apiKey" and not k.startswith("_gateway")}
        payload["model"] = "minimax-h3-runninghub"
        if re.fullmatch(r"/openapi/v2/run/workflow/[0-9]{1,30}", path):
            workflow_path = path
            path = "/task/openapi/create"
            payload["_gateway_workflow_path"] = workflow_path
    if path not in set(PATHS.values()) - {"/v1/chat/completions", "/v1/messages"}:
        raise HTTPException(404, "Unsupported provider operation")
    job, _ = await enqueue(
        CreateJob(model=payload.get("model") or payload.get("model_name", ""), payload=payload), request, client, channel, path
    )
    return {
        "code": 0 if channel == "runninghub" else 200,
        "data": {"id": job.id, "taskId": job.id, "task_id": job.id},
        "id": job.id,
        "taskId": job.id,
        "task_id": job.id,
    }


@app.get("/providers/{channel}/{path:path}")
async def native_query(channel: str, path: str, request: Request, client: Client = Depends(authenticate)):
    jid = path.rsplit("/", 1)[-1]
    job = await get_owned(jid, request, client)
    allowed = "/v2/query/video_generation" if job.protocol == "context" else PATHS[job.protocol] if job.protocol != "grok" else "/v1/videos"
    if channel != job.channel or "/" + path != allowed + "/" + jid:
        raise HTTPException(404, "Task not found")
    return native(job)


app.include_router(portal_router)
