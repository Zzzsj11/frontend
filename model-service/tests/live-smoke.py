"""Explicit one-shot paid acceptance; durable manifest prevents accidental resubmission."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
manifest = root / ".runtime/live-smoke.json"
if manifest.exists():
    raise SystemExit("Existing run manifest found. Inspect existing tasks; do not rerun paid submission.")
run = "model-service-smoke-" + uuid.uuid4().hex
key = json.loads((root / ".secrets/clients.json").read_text())["code-agent-acceptance"]["api_key"]
state = {"run_id": run, "jobs": {}, "llm": None}
manifest.write_text(json.dumps(state))
manifest.chmod(0o600)
headers = {
    "Authorization": "Bearer " + key,
    "X-User-Id": "code-agent-acceptance",
    "X-Agent-Name": "code-agent",
    "X-Agent-Run-Id": run,
    "X-Test-Run-Id": run,
}


def save():
    manifest.write_text(json.dumps(state, indent=2))


async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8011", headers=headers, timeout=360) as api:
        # Each request gets one durable idempotency key and is sent once.
        state["llm"] = {"state": "submitting", "idempotency_key": run + "-llm"}
        save()
        r = await api.post(
            "/v1/chat/completions",
            headers={"Idempotency-Key": run + "-llm"},
            json={"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "Reply with exactly OK."}], "max_tokens": 32},
        )
        state["llm"] = {"http_status": r.status_code, "response": r.json()}
        save()
        print("LLM", r.status_code, flush=True)
        examples = {
            "image": {
                "model": "gpt-image-2.5-flare",
                "payload": {
                    "prompt": "A simple blue ceramic cup on a plain cream tabletop, soft daylight, no text, no people.",
                    "size": "1024x1024",
                    "quality": "low",
                    "n": 1,
                },
            },
            "video": {
                "model": "doubao-seedance-2.0-fast",
                "payload": {
                    "content": [
                        {
                            "type": "text",
                            "text": "A quiet autumn riverside at sunrise, a slow continuous camera push, gentle ripples, no people, no text.",
                        }
                    ],
                    "duration": 5,
                    "ratio": "16:9",
                    "resolution": "720p",
                    "generate_audio": False,
                    "watermark": False,
                    "return_last_frame": True,
                },
            },
        }
        for name, body in examples.items():
            state["jobs"][name] = {"state": "submitting", "idempotency_key": run + "-" + name}
            save()
            r = await api.post("/v1/jobs", headers={"Idempotency-Key": run + "-" + name}, json=body)
            state["jobs"][name] = {"http_status": r.status_code, **r.json()}
            save()
            print(name, r.status_code, state["jobs"][name].get("id"), flush=True)
        for _ in range(300):
            pending = False
            for name, row in list(state["jobs"].items()):
                if not row.get("id") or row.get("status") in {"succeeded", "failed", "recoverable", "manual_review"}:
                    continue
                r = await api.get("/v1/jobs/" + row["id"])
                r.raise_for_status()
                state["jobs"][name] = r.json()
                pending = True
            save()
            if not pending:
                break
            await asyncio.sleep(5)
        print(
            json.dumps(
                {
                    "run_id": run,
                    "results": {
                        k: {"id": v.get("id"), "status": v.get("status"), "error": v.get("error"), "usage": v.get("usage")}
                        for k, v in state["jobs"].items()
                    },
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


asyncio.run(main())
