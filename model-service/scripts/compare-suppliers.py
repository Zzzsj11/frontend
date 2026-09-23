"""Minimal paid paired acceptance, serial within each account; durable no-replay journal."""

import argparse
import asyncio
import fcntl
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k] = v
sys.path.insert(0, str(ROOT / "public-api"))
from gateway.channel_balances import fetch  # noqa: E402
from gateway.db import Job, Session  # noqa: E402

OUT = ROOT / ".runtime" / os.getenv("COMPARISON_BATCH", "comparison-20260922")
OUT.mkdir(exist_ok=True)
MANIFEST = OUT / "run.json"
STATE = (
    json.loads(MANIFEST.read_text())
    if MANIFEST.exists()
    else {"run_id": "paired-" + uuid.uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(), "cases": {}, "balances": {}}
)
KEY = json.loads((ROOT / ".secrets/clients.json").read_text())["code-agent-acceptance"]["api_key"]
SELECTION = json.loads((ROOT / "catalog/selected-models.json").read_text())
SOURCE = json.loads((ROOT.parent / "output/dev01-batch-20260921/manifest.json").read_text())[0]
SCENE = SOURCE["prompt"].replace("12秒内", "短片内")
TEXT = (
    "将下面MV场景整理成JSON，含且仅含3个镜头，每个镜头包含index、duration（秒）、prompt。总时长12秒，单镜头4秒。保留秋雨、空车站、灰蓝电影写实风格，不出现人物和文字。只返回JSON。场景："
    + SCENE
)


def save():
    supplier = sys.argv[sys.argv.index("--supplier") + 1]
    with (OUT / "journal.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else dict(STATE)
        current.setdefault("cases", {}).update({k: v for k, v in STATE["cases"].items() if k.startswith(supplier + "--")})
        if supplier in STATE["balances"]:
            current.setdefault("balances", {})[supplier] = STATE["balances"][supplier]
        tmp = MANIFEST.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2))
        tmp.chmod(0o600)
        tmp.replace(MANIFEST)


async def balance(supplier):
    data = await fetch(SimpleNamespace(channel=supplier, key_env=supplier.upper() + "_API_KEY"))
    if supplier == "toapis":
        data["balance_usd"] = str(Decimal(data["balance"]) / Decimal(data["credits_per_usd"]))
        data["balance_cny"] = str(Decimal(data["balance"]) * Decimal("0.035"))
    return {"at": datetime.now(timezone.utc).isoformat(), **data}


async def read_job(key):
    async with Session() as db:
        j = await db.scalar(select(Job).where(Job.idempotency_key == key))
        if not j:
            return None
        return {
            "id": j.id,
            "status": j.status,
            "error": j.error,
            "provider_task_id": j.provider_id,
            "usage": j.usage,
            "response": j.provider_response,
            "result": j.result,
            "request": j.payload,
            "route": j.routing_snapshot,
            "billing_status": j.billing_status,
        }


async def run(supplier, kinds):
    hdr = {
        "Authorization": "Bearer " + KEY,
        "X-User-Id": "code-agent-acceptance",
        "X-Agent-Name": "code-agent",
        "X-Agent-Run-Id": STATE["run_id"],
        "X-Test-Run-Id": STATE["run_id"],
        "X-Test-Supplier": supplier,
    }
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8011", headers=hdr, timeout=360) as api:
        if supplier not in STATE["balances"]:
            STATE["balances"][supplier] = {"initial": await balance(supplier)}
            save()
        for kind, names in SELECTION.items():
            if kind not in kinds:
                continue
            for name in names:
                if os.getenv("COMPARISON_MODELS") and name not in os.environ["COMPARISON_MODELS"].split(","):
                    continue
                case_id = supplier + "--" + name
                row = STATE["cases"].get(case_id)
                if row and row.get("finished_at"):
                    continue
                if not row:
                    before = await balance(supplier)
                    # Conservative remaining-funds guard, not an assertion of exact video cost.
                    minimum = (
                        Decimal("0.9")
                        if kind == "video" and "2.5" in name
                        else Decimal("0.85")
                        if "omni" in name
                        else Decimal("0.6")
                        if kind == "video"
                        else Decimal("0.2")
                        if kind == "image"
                        else Decimal("0.04")
                    )
                    if Decimal(before.get("balance_usd", before["balance"])) < minimum:
                        STATE["cases"][case_id] = {
                            "status": "budget_blocked",
                            "reason": "Remaining account funds below conservative submission guard",
                            "balance": before,
                        }
                        save()
                        continue
                    body = {"model": name}
                    if kind == "chat":
                        text = TEXT
                        if os.getenv("COMPARISON_FRESH_PREFIX"):
                            text = "本次独立请求标识（勿输出）：" + uuid.uuid4().hex + "。\n" + TEXT
                            body["system"] = "独立请求 " + uuid.uuid4().hex if name.startswith("claude") and supplier == "yseeai" else None
                            if body["system"] is None:
                                body.pop("system")
                            if name.startswith("gpt"):
                                body["prompt_cache_key"] = uuid.uuid4().hex
                        body.update(
                            messages=[{"role": "user", "content": text}], max_tokens=1024 if os.getenv("COMPARISON_FRESH_PREFIX") else 384
                        )
                        path = "/v1/messages" if name.startswith("claude") and supplier == "yseeai" else "/v1/chat/completions"
                    elif kind == "image":
                        body.update(prompt=SCENE, size="2048x2048" if name == "seedream-5.0" else "1024x1024", quality="high", n=1)
                        path = "/v1/images"
                    else:
                        body.update(
                            prompt=SCENE,
                            duration=10 if "omni" in name else 4,
                            resolution="720p",
                            aspect_ratio="16:9",
                            generate_audio=True,
                            reference_mode="text",
                        )
                        path = "/v1/videos"
                    row = {
                        "status": "submitting",
                        "kind": kind,
                        "model": name,
                        "supplier": supplier,
                        "request": body,
                        "path": path,
                        "before": before,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "idempotency_key": STATE["run_id"] + "-" + case_id,
                        "source_task_id": SOURCE["task_id"],
                        "source_line_id": SOURCE["line_id"],
                    }
                    STATE["cases"][case_id] = row
                    save()
                    try:
                        response = await api.post(path, json=body, headers={"Idempotency-Key": row["idempotency_key"]})
                        row["http_status"] = response.status_code
                        row["accepted_response"] = response.json()
                        save()
                    except Exception as exc:
                        row["transport_error"] = type(exc).__name__
                        save()
                deadline = time.monotonic() + 3000
                while True:
                    job = await read_job(row["idempotency_key"])
                    if job:
                        row["job"] = job
                        row["status"] = job["status"]
                        save()
                    else:
                        row["status"] = "not_accepted"
                        break
                    if job["status"] in ("succeeded", "failed", "manual_review", "recoverable"):
                        break
                    if time.monotonic() > deadline:
                        row["status"] = "pending_timeout"
                        break
                    await asyncio.sleep(5)
                if row["status"] == "pending_timeout":
                    save()
                    print(case_id, row["status"], "ACCOUNT PAUSED", flush=True)
                    return
                if row["status"] == "manual_review":
                    row["reconciliation_note"] = (
                        "Submission uncertain; never replay. Subsequent account deltas may include delayed settlement."
                    )
                    STATE["balances"][supplier]["uncertain_submission"] = case_id
                # Allow async debit bookkeeping to settle; snapshot all three checks.
                row["after_samples"] = []
                for _ in range(3):
                    await asyncio.sleep(2)
                    row["after_samples"].append(await balance(supplier))
                    save()
                row["after"] = row["after_samples"][-1]
                delta = Decimal(row["before"]["balance"]) - Decimal(row["after"]["balance"])
                if supplier == "toapis":
                    row["balance_delta_credits"] = str(delta)
                    row["balance_delta_cny"] = str(delta * Decimal("0.035"))
                    row["balance_delta_usd"] = str(delta / Decimal(row["after"]["credits_per_usd"]))
                    row["conversion"] = {"toapis_credits": "1000", "cny": "35"}
                else:
                    row["balance_delta_usd"] = str(delta)
                    row["balance_delta_cny_reference"] = str(delta * Decimal("6.9"))
                row["finished_at"] = datetime.now(timezone.utc).isoformat()
                save()
                print(case_id, row["status"], "USD delta", row["balance_delta_usd"], flush=True)
                # Generation success alone does not certify parameter or billing correctness.
        STATE["balances"][supplier]["latest"] = await balance(supplier)
        save()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--supplier", choices=["yseeai", "toapis"], required=True)
    parser.add_argument("--kinds", default="chat,image,video")
    args = parser.parse_args()
    save()
    await run(args.supplier, args.kinds.split(","))


if __name__ == "__main__":
    asyncio.run(main())
