"""One evenly interleaved shard of the staging 500 QPS measurement."""

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from contextvars import ContextVar
from pathlib import Path

import httpx
from sqlalchemy import select

from app import all_in_one
from app.config import settings
from app.database import session_factory
from app.models import GenerationJobModel
from scripts.mock_video_acceptance import HOST, check


async def measure(run, start, shard, count, path):
    if settings.all_in_one_base_url != HOST or os.getenv("DEPLOYMENT_TIER") != "test" or os.getenv("TLS_DOMAIN") != "mv-test.epaipix.com":
        raise RuntimeError("requires MV staging")
    async with session_factory() as db:
        jobs = (
            await db.execute(
                select(GenerationJobModel.provider_task_id, GenerationJobModel.request)
                .where(GenerationJobModel.agent_run_id.startswith(run + "-"), GenerationJobModel.kind == "mock_video_acceptance", GenerationJobModel.provider_task_id.is_not(None))
                .order_by(GenerationJobModel.id)
            )
        ).all()
    samples = []
    errors = Counter()
    ids = set()
    offsets = []
    wire_offsets = []
    gate = asyncio.Semaphore(24)

    scheduled = ContextVar("scheduled", default=None)
    pre_send = []
    headers_wait = []

    async def instrument(request):
        sent = None

        async def trace(event, info):
            nonlocal sent
            if scheduled.get() is None:
                return
            now = time.monotonic()
            if event.endswith("send_request_headers.complete"):
                sent = now
                wire_offsets.append(round((now - first) * 1000, 2))
                pre_send.append(round((now - scheduled.get()) * 1000, 3))
            elif event.endswith("receive_response_headers.complete") and sent is not None:
                headers_wait.append(round((now - sent) * 1000, 3))

        request.extensions["trace"] = trace

    first = time.monotonic() + start - time.time()
    async with httpx.AsyncClient(timeout=5, event_hooks={"request": [instrument]}, limits=httpx.Limits(max_connections=24, max_keepalive_connections=24)) as client:
        token = all_in_one._poll_client.set(client)

        async def read(i, due):
            scheduled.set(due)
            jid, req = jobs[i % len(jobs)]
            offsets.append(round((time.monotonic() - first) * 1000, 2))
            try:
                async with gate:
                    row = await all_in_one.query_task("video", jid)
                check({**row, "status": row["status"].lower()}, req["model"], jid)
                samples.append(round((time.monotonic() - due) * 1000, 3))
                ids.add(jid)
            except Exception as exc:
                cause = getattr(exc, "__cause__", None)
                status = getattr(getattr(cause, "response", None), "status_code", None)
                errors[str(status or type(exc).__name__)] += 1

        try:
            await asyncio.gather(*(all_in_one.query_task("video", j) for j, _ in jobs[shard * 12 : shard * 12 + 12]))
            wire_offsets.clear()
            if time.monotonic() >= first:
                raise RuntimeError("missed coordinated start")
            pending = set()
            for i in range(shard, 30000, count):
                due = first + i / 500
                await asyncio.sleep(max(0, due - time.monotonic()))
                if time.monotonic() - due > 0.05 or len(pending) >= 96:
                    errors["schedule overrun"] += 1
                    continue
                task = asyncio.create_task(read(i, due))
                pending.add(task)
                task.add_done_callback(pending.discard)
            await asyncio.gather(*pending)
        finally:
            all_in_one._poll_client.reset(token)
            path.write_text(
                json.dumps(
                    dict(
                        shard=shard,
                        run=run,
                        start=start,
                        errors=errors,
                        samples=samples,
                        ids=sorted(ids),
                        offsets=offsets,
                        wire_offsets=wire_offsets,
                        pre_send=pre_send,
                        headers_wait=headers_wait,
                    )
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run")
    parser.add_argument("start", type=float)
    parser.add_argument("shard", type=int)
    parser.add_argument("count", type=int)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    import uvloop

    uvloop.run(measure(**vars(args)))
