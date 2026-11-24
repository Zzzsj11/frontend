"""One evenly interleaved shard of the staging query measurement."""

import argparse
import asyncio
import gc
import json
import time
from collections import Counter
from contextlib import AsyncExitStack
from contextvars import ContextVar
from pathlib import Path

import httpx
from sqlalchemy import select

from app import all_in_one
from app.database import session_factory
from app.models import GenerationJobModel
from scripts.mock_video_acceptance import QPS, SECONDS, check, check_target, trace_hooks

MAX_PENDING = 96


class WindowClosed(Exception):
    """No new request may start sending headers at or after the deadline."""


class WirePacer:
    def __init__(self, shard_count, end):
        # Each shard owns every Nth nominal slot. Allow a bounded catch-up
        # margin after jitter without draining a queue of prepared connections at once.
        interval = shard_count / QPS
        self.recovery_interval = 0.99 * interval
        self.credit = 5 * self.recovery_interval
        self.min_gap = interval / 8
        self.virtual_time = 0.0
        self.next_send = 0.0
        self.end = end
        self.lock = asyncio.Lock()

    async def wait(self, due):
        # A later request whose connection is ready first must not hold the
        # shard lock while an earlier slot is still waiting to send.
        now = time.monotonic()
        if now < due:
            await asyncio.sleep(due - now)
        async with self.lock:
            target = max(due, self.next_send, self.virtual_time - self.credit)
            if target >= self.end:
                raise WindowClosed
            now = time.monotonic()
            while now < target:
                await asyncio.sleep(max(target - now, 0.001))
                now = time.monotonic()
            if now >= self.end:
                raise WindowClosed
            self.virtual_time = max(now, self.virtual_time) + self.recovery_interval
            self.next_send = now + self.min_gap


def skip_reason(now, end, pending):
    if now >= end:
        return "window_closed"
    if pending >= MAX_PENDING:
        return "pending_limit"
    return None


async def measure(run, start, shard, count, path):
    check_target()
    async with session_factory() as db:
        jobs = (
            await db.execute(
                select(GenerationJobModel.provider_task_id, GenerationJobModel.request)
                .where(GenerationJobModel.agent_run_id.startswith(run + "-"), GenerationJobModel.kind == "mock_video_acceptance", GenerationJobModel.provider_task_id.is_not(None))
                .order_by(GenerationJobModel.id)
            )
        ).all()
    await measure_window(run, start, shard, count, path, jobs)


async def measure_window(run, start, shard, count, path, jobs):
    if not 0 <= shard < count or not jobs:
        raise ValueError("invalid shard or empty job list")
    samples = []
    errors = Counter()
    ids = set()
    offsets = []
    wire_offsets = []

    scheduled = ContextVar("scheduled", default=None)
    pre_send = []
    headers_wait = []
    scheduling = [{"scheduler_late": 0, "pending_limit": 0, "window_closed": 0, "peak_pending": 0, "max_dispatch_lag_ms": 0.0} for _ in range(SECONDS)]

    async def instrument(request):
        sent = None

        async def trace(event, info):
            nonlocal sent
            due = scheduled.get()
            if due is None:
                return
            if event.endswith("send_request_headers.started"):
                await pacer.wait(due)
                return
            now = time.monotonic()
            if event.endswith("send_request_headers.complete"):
                sent = now
                wire_offsets.append((now - first) * 1000)
                pre_send.append(round((now - due) * 1000, 3))
            elif event.endswith("receive_response_headers.complete") and sent is not None:
                headers_wait.append(round((now - sent) * 1000, 3))

        request.extensions["trace"] = trace

    first = time.monotonic() + start - time.time()
    pacer = WirePacer(count, first + SECONDS)
    # Lease a single-connection client before entering HTTPX. Concurrent
    # requests cannot queue behind a paced request on the same HTTP/1 socket.
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=1, keepalive_expiry=SECONDS + 5)
    request_ids = []
    hooks = trace_hooks(run, request_ids.append)
    hooks["request"].append(instrument)
    async with AsyncExitStack() as stack:
        available = asyncio.Queue()
        tls = httpx.create_ssl_context()
        for _ in range(32):
            client = httpx.AsyncClient(timeout=5, verify=tls, event_hooks=hooks, limits=limits)
            available.put_nowait(await stack.enter_async_context(client))

        async def query(jid):
            client = await available.get()
            token = all_in_one._poll_client.set(client)
            try:
                return await all_in_one.query_task("video", jid)
            finally:
                all_in_one._poll_client.reset(token)
                available.put_nowait(client)

        async def read(i, due):
            scheduled.set(due)
            jid, req = jobs[i % len(jobs)]
            offsets.append(round((time.monotonic() - first) * 1000, 2))
            try:
                row = await query(jid)
                check({**row, "status": row["status"].lower()}, req["model"], jid)
                samples.append(round((time.monotonic() - due) * 1000, 3))
                ids.add(jid)
            except WindowClosed:
                errors["window_closed"] += 1
                scheduling[i // QPS]["window_closed"] += 1
            except Exception as exc:
                cause = getattr(exc, "__cause__", None)
                status = getattr(getattr(cause, "response", None), "status_code", None)
                errors[str(status or type(exc).__name__)] += 1

        try:
            for batch in range(4):
                warm = [(shard * 32 + batch * 8 + n) % len(jobs) for n in range(8)]
                await asyncio.gather(*(query(jobs[n][0]) for n in warm))
                await asyncio.sleep(0.08)
            wire_offsets.clear()
            if time.monotonic() >= first:
                raise RuntimeError("missed coordinated start")
            pending = set()
            loop = asyncio.get_running_loop()
            dispatched = asyncio.Event()
            final_slot = range(shard, QPS * SECONDS, count)[-1]

            def dispatch(i, due):
                now = time.monotonic()
                lag = now - due
                bucket = scheduling[i // QPS]
                bucket["max_dispatch_lag_ms"] = max(bucket["max_dispatch_lag_ms"], round(lag * 1000, 3))
                bucket["peak_pending"] = max(bucket["peak_pending"], len(pending))
                reason = skip_reason(now, pacer.end, len(pending))
                if reason:
                    errors[reason] += 1
                    bucket[reason] += 1
                else:
                    task = asyncio.create_task(read(i, due))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
                if i == final_slot:
                    dispatched.set()

            # Register independent absolute deadlines. When the event loop is late,
            # one missed timer cannot delay scheduling all the following slots.
            loop_first = loop.time() + first - time.monotonic()
            # These short-lived proof processes each load the full MV app. Collect
            # before the shared start so a full-heap scan does not stall every
            # shard mid-window. Refcount reclamation continues during the bound.
            gc.collect()
            gc_enabled = gc.isenabled()
            timers = [loop.call_at(loop_first + i / QPS, dispatch, i, first + i / QPS) for i in range(shard, QPS * SECONDS, count)]
            try:
                gc.disable()
                await dispatched.wait()
                await asyncio.gather(*pending)
            finally:
                if gc_enabled:
                    gc.enable()
                for timer in timers:
                    timer.cancel()
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
        finally:
            path.write_text(
                json.dumps(
                    dict(
                        shard=shard,
                        shard_count=count,
                        target_qps=QPS,
                        scheduling=scheduling,
                        request_ids=request_ids,
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
