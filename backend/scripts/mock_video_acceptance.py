"""MV acceptance client for the test gateway. Python 3.11+, httpx 0.28.1."""

import asyncio
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import select

from app import all_in_one
from app.agent_attribution import attribution_context
from app.config import settings
from app.database import session_factory
from app.jobs import jobs, record_media_usage
from app.models import GenerationJobModel, utcnow

HOST = "https://mg-test.epaipix.com"
MODELS = {"seedance-2.0": (1000, 5), "wan3.0-video": (1000, 5), "veo-3.1-fast": (500, 8)}
QPS, SECONDS = 100, 60
clock = time.monotonic


def check(row, model, jid=None, *, states=("running",)):
    if not isinstance(row, dict) or row.get("mock") is not True:
        raise ValueError("missing mock=true; stop")
    if row.get("model") != model or row.get("status") not in states:
        raise ValueError(f"unexpected model/status: {row.get('model')}/{row.get('status')}")
    if not row.get("id") or (jid is not None and row["id"] != jid) or row.get("provider_task_id") is not None:
        raise ValueError("unexpected task identity")
    bill = row["billing"]
    if any(Decimal(str(bill[field])) != 0 for field in ("points", "reserved_points")):
        raise ValueError("nonzero charge or reservation")


def retry_after(resp, default):
    try:
        return max(default, int(resp.headers.get("Retry-After", default)))
    except ValueError:
        return default


def pct(values, p):
    return round(sorted(values)[math.ceil(len(values) * p) - 1], 2) if values else None


async def measure_single(ordered, ids, read, sleep):
    errors = Counter()
    latencies = []
    covered = set()
    tasks = set()
    start = clock()
    last_launch = None
    sent = 0

    async def measure(jid, scheduled):
        try:
            check(await read(jid), ids[jid], jid)
            covered.add(jid)
            latencies.append((clock() - scheduled) * 1000)
        except Exception as exc:
            errors[type(exc).__name__] += 1

    for i in range(QPS * SECONDS):
        due = start + i / QPS
        await sleep(max(0, due - clock()))
        if len(tasks) >= 512 or clock() - due > 0.1:
            errors["window interrupted; no catch-up burst"] += 1
            break
        t = asyncio.create_task(measure(ordered[i % len(ordered)], due))
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        sent += 1
        last_launch = clock()
    if tasks:
        await asyncio.gather(*list(tasks))
    elapsed = max(1 / QPS, clock() - start)
    p95 = pct(latencies, 0.95)
    return {
        "target_qps": QPS,
        "window_s": SECONDS,
        "sent": sent,
        "valid_200": len(latencies),
        "distinct_running_ids": len(covered),
        "errors": dict(errors),
        "send_qps": round((sent - 1) / (last_launch - start), 2) if sent > 1 else 0,
        "success_qps_including_drain": round(len(latencies) / elapsed, 2),
        "p50_ms": pct(latencies, 0.50),
        "p95_ms": p95,
        "p99_ms": pct(latencies, 0.99),
    }


async def proof(api, probe_api, run, out, sleep=asyncio.sleep):
    started = clock()
    ids = {}
    report = {"run_id": run, "endpoint": HOST, "buckets": {}, "overflow": {}, "passed": False}
    ready_by = started + 450  # Leave room before the first ten-minute video expires.
    calls = asyncio.Semaphore(16)
    journal = out / "jobs.jsonl"

    async def create(model, n, *, probe=False):
        logical = f"{run}-{model}-{n}"
        headers = {"Idempotency-Key": logical, "X-Agent-Run-Id": logical, "X-Test-Run-Id": run, "X-Agent-Name": "code-agent"}
        body = {"model": model, "prompt": "MV mock acceptance", "duration": MODELS[model][1], "mock": True}
        client = probe_api if probe else api
        async with calls:
            with attribution_context("agent_test", "code-agent", logical):
                async with session_factory.begin() as db:
                    local = await jobs.enqueue(db, "mock_video_acceptance", body, user_id=None)
                    order = await db.get(GenerationJobModel, local.id)
                    order.idempotency_key = logical
                    order.status, order.phase, order.provider = "running", "submitting_provider", "all-in-one"
            for attempt in range(3):
                if clock() >= ready_by:
                    raise RuntimeError("fill/probe deadline exceeded")
                try:
                    resp = await all_in_one.submit_media(client, "videos?mock=true", body, {**all_in_one.headers(), **headers})
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    await sleep(1 + attempt)
                    continue
                if resp.status_code == 202:
                    row = resp.json()
                    check(row, model)
                    jid = row["id"]
                    if jid in ids:
                        raise ValueError("duplicate job ID for distinct logical requests")
                    ids[jid] = model
                    async with session_factory() as db:
                        row_db = await db.get(GenerationJobModel, local.id, with_for_update=True)
                        row_db.phase, row_db.provider_task_id, row_db.provider_submitted_at = "provider_running", jid, utcnow()
                        await record_media_usage(db, row_db, {"platformBilling": row["billing"]}, jid, "video_mock", "all-in-one", model)
                        await db.commit()
                    with journal.open("a", encoding="utf-8") as log:
                        print(json.dumps({"id": jid, "model": model, "key": logical, "probe": probe}), file=log)
                    if probe:
                        raise ValueError(f"{model}: overflow unexpectedly accepted")
                    return
                if resp.status_code == 429:
                    if probe and resp.json().get("detail") == "Shared generation pool is full" and "Retry-After" in resp.headers:
                        async with session_factory.begin() as db:
                            order = await db.get(GenerationJobModel, local.id)
                            order.status, order.phase, order.finished_at = "failed", "rejected_before_acceptance", utcnow()
                            order.result = {"httpStatus": 429, "detail": resp.json()["detail"], "retryAfter": resp.headers["Retry-After"]}
                        report["overflow"][model] = 429
                        return
                    if not probe and attempt < 2:
                        await sleep(retry_after(resp, 5))
                        continue
                if resp.status_code in (502, 503, 504) and attempt < 2:
                    await sleep(retry_after(resp, 1 + attempt))
                    continue
                async with session_factory.begin() as db:
                    order = await db.get(GenerationJobModel, local.id)
                    order.status, order.finished_at = "failed", utcnow()
                    order.phase = "rejected_before_acceptance" if resp.status_code == 429 else "manual_review"
                    order.error = f"HTTP {resp.status_code}"
                raise RuntimeError(f"{model} {n}: create/probe HTTP {resp.status_code}, {resp.text[:220]}")

    async def read(jid):
        row = await all_in_one.query_task("video", jid)
        return {**row, "status": row["status"].lower()}

    try:
        catalog = await api.get("/v1/models")
        catalog.raise_for_status()
        if not MODELS.keys() <= {m["id"] for m in catalog.json()["data"]}:
            raise RuntimeError("the Key cannot see all three models")
        # Omit the required prompt: even older gateways cannot accept this request.
        invalid = await api.post(
            "/v1/videos",
            json={"model": "seedance-2.0", "mock": "invalid"},
            headers={
                "X-Agent-Name": "code-agent",
                "X-Test-Run-Id": run,
                "X-Agent-Run-Id": run + "-schema",
                "Idempotency-Key": run + "-schema",
            },
        )
        if invalid.status_code != 422 or not any(e.get("loc") == ["body", "mock"] for e in invalid.json().get("detail", []) if isinstance(e, dict)):
            raise RuntimeError("gateway did not validate mock as a typed field; stopped before creating jobs")
        # These three jobs are included in the target counts.
        for model in MODELS:
            await create(model, 0)
            jid = next(j for j in ids if ids[j] == model)
            check(await read(jid), model, jid)

        # Interleave models, bound outstanding submissions, stop scheduling on failure.
        plan = [(model, n) for n in range(1, max(v[0] for v in MODELS.values())) for model, (limit, _) in MODELS.items() if n < limit]
        for start in range(0, len(plan), 16):
            results = await asyncio.gather(*(create(m, n) for m, n in plan[start : start + 16]), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        report["buckets"] = dict(Counter(ids.values()))
        if report["buckets"] != {m: a for m, (a, _) in MODELS.items()}:
            raise ValueError("bucket totals do not match")
        for model in MODELS:
            await create(model, "overflow", probe=True)
        if clock() >= ready_by:
            raise RuntimeError("insufficient overlap before expiry")
        print("Filled", report["buckets"], "and observed three overflow 429s", flush=True)

        async with session_factory() as db:
            persisted = (
                await db.execute(
                    select(GenerationJobModel.provider_task_id, GenerationJobModel.request).where(
                        GenerationJobModel.kind == "mock_video_acceptance", GenerationJobModel.provider_task_id.is_not(None), GenerationJobModel.agent_run_id.startswith(run + "-")
                    )
                )
            ).all()
        if {jid: req["model"] for jid, req in persisted} != ids:
            raise ValueError("MV persisted work orders disagree with accepted tasks")
        ordered = [jid for jid, _ in persisted]
        if os.getenv("MV_SHARDED_WINDOW") == "1":
            (out / "ready.json").write_text(json.dumps({"run_id": run, "counts": report["buckets"]}))
            metrics = out / "window.json"
            deadline = clock() + 150
            while not metrics.exists() and clock() < deadline:
                await sleep(0.5)
            result = json.loads(metrics.read_text())
            if result["run_id"] != run:
                raise ValueError("window belongs to another run")
            report["query"] = result
        else:
            report["query"] = await measure_single(ordered, ids, read, sleep)
        query = report["query"]
        failed_window = (
            query["target_qps"] != QPS
            or query["window_s"] != SECONDS
            or query["sent"] != QPS * SECONDS
            or query["valid_200"] != query["sent"]
            or query["distinct_running_ids"] != len(ids)
            or query["errors"]
            or query["p95_ms"] is None
            or query["p95_ms"] > 500
        )
        print(json.dumps(query), flush=True)
        if failed_window:
            raise ValueError(f"{QPS} QPS acceptance failed")
        report["passed"] = len(ids) == 2500
        report["diagnostic_only"] = len(ids) != 2500
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["accepted_by_model"] = dict(Counter(ids.values()))
        if ids:
            try:
                report["terminal_succeeded"] = await drain(run)
                if report["terminal_succeeded"] != len(ids):
                    raise RuntimeError("terminal count differs from accepted tasks")
            except Exception as exc:
                report["passed"] = False
                report["drain_failure"] = str(exc)
        (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


async def drain(run):
    async with session_factory() as db:
        stored = (
            await db.execute(
                select(GenerationJobModel.id, GenerationJobModel.provider_task_id, GenerationJobModel.request).where(
                    GenerationJobModel.kind == "mock_video_acceptance", GenerationJobModel.provider_task_id.is_not(None), GenerationJobModel.agent_run_id.startswith(run + "-")
                )
            )
        ).all()
    pending = {jid: (local_id, req["model"]) for local_id, jid, req in stored}
    deadline = clock() + 900
    while pending and clock() < deadline:
        batch_ids = list(pending)
        for offset in range(0, len(batch_ids), 8):
            batch = batch_ids[offset : offset + 8]
            rows = await asyncio.gather(*(all_in_one.query_task("video", jid) for jid in batch), return_exceptions=True)
            async with session_factory.begin() as db:
                for jid, row in zip(batch, rows):
                    if isinstance(row, Exception):
                        continue
                    local_id, model = pending[jid]
                    check({**row, "status": row["status"].lower()}, model, jid, states=("running", "succeeded"))
                    if row["status"] == "SUCCEEDED":
                        if row["result"].get("mock") is not True or row["result"].get("media") != []:
                            raise ValueError("unexpected mock media")
                        work = await db.get(GenerationJobModel, local_id)
                        work.status, work.phase, work.finished_at = "succeeded", "succeeded", work.finished_at or utcnow()
                        work.result = {"mock": True, "media": [], "billing": row["billing"]}
                        pending.pop(jid)
            await asyncio.sleep(0.1)
        if pending:
            await asyncio.sleep(10)
    if pending:
        raise TimeoutError(f"{len(pending)} mock jobs still unresolved")
    return len(stored)


async def main():
    if settings.all_in_one_base_url != HOST or os.getenv("DEPLOYMENT_TIER") != "test" or os.getenv("TLS_DOMAIN") != "mv-test.epaipix.com" or settings.all_in_one_system_key:
        raise SystemExit("requires MV staging and its personal test Key")
    drain_run = os.getenv("MV_DRAIN_RUN")
    if drain_run and not re.fullmatch(r"mv-[0-9a-f]{32}", drain_run):
        raise ValueError("invalid run id")
    diagnostic_veo = int(os.getenv("MV_DIAGNOSTIC_VEO_SLOTS", "500"))
    if not 1 <= diagnostic_veo <= 500:
        raise ValueError("invalid diagnostic pool size")
    MODELS["veo-3.1-fast"] = (diagnostic_veo, 8)
    run = drain_run or "mv-" + uuid.uuid4().hex
    out = Path(os.environ.get("MV_EVIDENCE_DIR", "/tmp")) / run
    out.mkdir(mode=0o700, exist_ok=bool(drain_run))
    print("Evidence directory:", out, flush=True)
    async with httpx.AsyncClient(
        base_url=HOST, headers=all_in_one.headers(), timeout=10, follow_redirects=False, limits=httpx.Limits(max_connections=320, max_keepalive_connections=256)
    ) as client:
        token = all_in_one._poll_client.set(client)
        try:
            if drain_run:
                print(json.dumps({"run": run, "terminal_succeeded": await drain(run)}), flush=True)
            else:
                await proof(client, client, run, out)
                if not json.loads((out / "summary.json").read_text())["passed"]:
                    raise SystemExit(1)
        finally:
            all_in_one._poll_client.reset(token)


if __name__ == "__main__":
    asyncio.run(main())
