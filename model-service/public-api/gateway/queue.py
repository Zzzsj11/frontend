import asyncio
import os
import signal
import time
import uuid
from contextvars import ContextVar
from datetime import timedelta

import httpx
from sqlalchemy import func, select

from .channels import PATHS, config, headers, task_id, task_state, unwrap
from .credits import automatic, lock, reset
from .db import Client, Job, Model, ModelRoute, Session, now
from .errors import describe
from .media import archive, gemini_images, output_urls

_worker: ContextVar[str | None] = ContextVar("worker_fence", default=None)


class LeaseLost(RuntimeError):
    pass


ACTIVE = ("preparing", "submitting", "running", "archiving")


async def quarantine_unavailable_target(db, job):
    model = await db.get(Model, job.model_id)
    target = None
    if not model or model.deleted_at:
        target = "Model"
    elif job.route_id:
        route = await db.get(ModelRoute, job.route_id)
        if not route or route.deleted_at:
            target = "Model route"
    if target is None:
        return False
    # Do not use update/automatic: quarantine must preserve historical financial records.
    job.status = "manual_review"
    job.error = f"{target} is missing or soft-deleted; job is not recoverable and must not be resubmitted"
    job.worker_id = job.lease_until = None
    return True


async def capacity(db, job):
    model = await db.get(Model, job.model_id)
    client = await db.get(Client, job.client_id)
    acceptance = job.origin == "agent_test" and job.route_id and client and client.require_agent
    if not model or not client or (not model.enabled and not acceptance) or not client.enabled or model.deleted_at or client.deleted_at:
        return False
    active = select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE), Job.deleted_at.is_(None), Job.id != job.id)
    per_model = await db.scalar(active.where(Job.model_id == model.id))
    per_client = await db.scalar(active.where(Job.client_id == client.id))
    per_channel = await db.scalar(active.where(Job.channel == job.channel))
    channel_limit = int(os.getenv(job.channel.upper().replace("-", "_") + "_CONCURRENCY", "16"))
    if job.route_id:
        route = await db.get(ModelRoute, job.route_id)
        route_active = await db.scalar(active.where(Job.route_id == job.route_id))
        if not route or route_active >= route.concurrency:
            return False
    return per_model < model.concurrency and per_client < client.concurrency and per_channel < channel_limit


async def claim(worker):
    async with Session.begin() as db:
        await lock(db)
        stale = list(
            (await db.scalars(select(Job).where(Job.status.in_(ACTIVE), Job.lease_until < now()).with_for_update(skip_locked=True))).all()
        )
        for row in stale:
            if row.status == "submitting" or row.kind == "chat":
                row.status, row.error = "manual_review", "Worker interrupted while submitting; do not resubmit without reconciliation"
            else:
                row.status = "queued"  # provider_id resumes polling; saved response resumes archive
            row.worker_id = None
        candidates = (
            await db.scalars(
                select(Job)
                .where(Job.status == "queued", Job.kind != "chat", Job.deleted_at.is_(None))
                .order_by(Job.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in candidates:
            if await quarantine_unavailable_target(db, row):
                continue
            if not await capacity(db, row):
                continue
            row.status = "preparing"
            row.worker_id, row.lease_until = worker, now() + timedelta(seconds=120)
            row.attempts += 1
            return row.id
    return None


async def update(jid, **values):
    async with Session.begin() as db:
        await lock(db)
        row = await db.get(Job, jid, with_for_update=True)
        if _worker.get() and row.worker_id != _worker.get():
            raise LeaseLost("Worker lease transferred")
        for key, value in values.items():
            setattr(row, key, value)
        await automatic(db, row)


async def heartbeat(jid):
    while True:
        await asyncio.sleep(20)
        await update(jid, lease_until=now() + timedelta(seconds=120))


def usage(body):
    data = unwrap(body)
    nested = data.get("result") if isinstance(data.get("result"), dict) else {}
    result = dict(data.get("usage") or data.get("tokenUsage") or nested.get("usage") or body.get("usage") or {})
    if data.get("billing"):
        result["billing"] = data["billing"]
    if data.get("cost") is not None:
        result["provider_cost"] = data["cost"]
    return result


async def process(jid):
    async with Session.begin() as db:
        await lock(db)
        job = await db.get(Job, jid, with_for_update=True)
        # A target may have been deleted after claim, including during a migration.
        if await quarantine_unavailable_target(db, job):
            return
    fence = _worker.set(job.worker_id)
    beat = asyncio.create_task(heartbeat(jid))
    phase = "preparing"
    try:
        observed_usage = dict(job.usage or {})
        base, _ = config(job.channel)
        hdr = headers(job)
        path = PATHS[job.protocol]
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            saved_success = job.provider_response and (job.protocol == "image-sync" or task_state(job.provider_response) == "succeeded")
            if not job.provider_id and not saved_success:
                payload = job.payload
                if payload.get("model") == "gemini-omni-flash-preview":
                    payload = await gemini_images(payload)
                payload = dict(payload)
                if job.protocol == "runninghub":
                    payload.pop("model", None)
                    path = payload.pop("_gateway_workflow_path", path)
                    payload["apiKey"] = config(job.channel)[1]
                phase = "submitting"
                await update(jid, status=phase)
                response = await client.post(base + path, headers=hdr, json=payload, timeout=300 if job.protocol == "image-sync" else 60)
                # 5xx/transport/malformed response is ambiguous; never automatically POST again.
                if 400 <= response.status_code < 500:
                    try:
                        rejected = response.json()
                        reason = describe(rejected, job.channel)
                        observed_usage.update(usage(rejected))
                    except ValueError:
                        reason = "Provider rejected the request"
                    await update(
                        jid,
                        status="failed",
                        error=f"Provider HTTP {response.status_code}: {reason}",
                        provider_response={"http_status": response.status_code},
                        usage=observed_usage,
                    )
                    return
                response.raise_for_status()
                body = response.json()
                observed_usage.update(usage(body))
                if task_state(body) == "failed" or body.get("error") or body.get("code", 200) not in (0, 200, "200"):
                    await update(jid, status="failed", error=describe(body, job.channel), provider_response=body, usage=observed_usage)
                    return
                if job.protocol == "image-sync":
                    # Save the billable response before archive; recovery must never regenerate.
                    await update(jid, provider_response=body, usage=observed_usage, status="archiving")
                    job.provider_response = body
                    phase = "archiving"
                    output_urls(body, "image")
                if job.protocol == "toapis-image" and isinstance(body.get("data"), list):
                    body = {**body, "status": "completed"}
                    job.provider_response = body
                    phase = "archiving"
                    await update(jid, provider_response=body, usage=observed_usage, status="archiving")
                tid = task_id(body)
                if not tid and job.protocol != "image-sync" and task_state(body) != "succeeded":
                    raise ValueError("Submission response has no task ID; reconcile before retry")
                if job.protocol != "image-sync" and tid:
                    job.provider_id = tid
                    await update(jid, provider_id=tid, provider_response=body, usage=observed_usage, status="running")
            phase = "running"
            saved = job.provider_response
            body = saved if job.protocol == "image-sync" or task_state(saved or {}) == "succeeded" else None
            errors = 0
            for _ in range(480):
                if body:
                    break
                await asyncio.sleep(float(os.getenv("POLL_SECONDS", "5")))
                try:
                    query_path = path + "/" + job.provider_id
                    if job.protocol == "grok":
                        query_path = "/v1/videos/" + job.provider_id
                    if job.protocol == "context":
                        query_path = "/v2/query/video_generation/" + job.provider_id
                    if job.protocol == "runninghub":
                        response = await client.post(base + "/openapi/v2/query", headers=hdr, json={"taskId": job.provider_id})
                    else:
                        response = await client.get(base + query_path, headers=hdr)
                    response.raise_for_status()
                    queried = response.json()
                    errors = 0
                except (httpx.HTTPError, ValueError):
                    errors += 1
                    if errors >= 6:
                        raise ValueError("Provider query unavailable; existing task ID retained")
                    continue
                observed_usage.update(usage(queried))
                await update(jid, provider_response=queried, usage=observed_usage)
                state = task_state(queried)
                if state == "failed":
                    await update(jid, status="failed", error=describe(queried, job.channel))
                    return
                if state == "succeeded":
                    body = queried
            if not body:
                raise ValueError("Polling deadline exceeded; existing task ID retained")
            phase = "archiving"
            await update(jid, status=phase)
            result = None
            for attempt in range(3):
                try:
                    result = (
                        {"native": body, "text": unwrap(body).get("content", {}).get("prompt", "")}
                        if job.kind == "text"
                        else await archive(job, body)
                    )
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2**attempt)
            await update(jid, status="succeeded", result=result, error=None, usage=observed_usage)
    except LeaseLost:
        return
    except asyncio.CancelledError:
        # Persist a safe restart boundary before relinquishing the lease. Never
        # automatically repeat a submission whose acknowledgement was interrupted.
        state = "manual_review" if phase == "submitting" else "queued"
        await asyncio.shield(
            update(jid, status=state, worker_id=None, lease_until=None, error="Worker stopped; resume or reconcile existing task")
        )
        raise
    except Exception as exc:
        # Avoid logging signed URLs, keys or upstream response bodies in exception text.
        state = "manual_review" if phase == "submitting" else "recoverable" if phase in {"running", "archiving"} else "failed"
        await update(jid, status=state, error=f"{phase}: {type(exc).__name__}; no automatic generation retry")
    finally:
        beat.cancel()
        await asyncio.gather(beat, return_exceptions=True)
        _worker.reset(fence)


async def main(stop=None, drain_seconds=None):
    from .channel_balances import loop as balance_loop

    install_signals = stop is None
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    if install_signals:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    drain_seconds = float(os.getenv("WORKER_DRAIN_SECONDS", "105")) if drain_seconds is None else drain_seconds
    balance_task = asyncio.create_task(balance_loop())
    worker = "worker-" + uuid.uuid4().hex
    tasks = set()
    last_reset = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() - last_reset >= 60:
                async with Session.begin() as db:
                    await lock(db)
                    clients = (await db.scalars(select(Client).where(Client.billing_enabled.is_(True), Client.deleted_at.is_(None)))).all()
                    for client in clients:
                        await reset(db, client)
                last_reset = time.monotonic()
            if balance_task.done():
                await asyncio.gather(balance_task, return_exceptions=True)
                balance_task = asyncio.create_task(balance_loop())
            completed = {t for t in tasks if t.done()}
            if completed:
                await asyncio.gather(*completed, return_exceptions=True)
                tasks -= completed
            if len(tasks) < int(os.getenv("WORKER_CONCURRENCY", "16")):
                jid = await claim(worker)
                if jid:
                    tasks.add(asyncio.create_task(process(jid)))
                    continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        balance_task.cancel()
        await asyncio.gather(balance_task, return_exceptions=True)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=max(0, drain_seconds))
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if install_signals:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)


if __name__ == "__main__":
    asyncio.run(main())
