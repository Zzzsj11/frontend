"""One submission per overseas model. Resume polls only; never replay uncertain POSTs."""

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".runtime/overseas-live.json"
CATALOG = json.loads((ROOT / "catalog/yseeai-2026-09-21.json").read_text())["models"]
KEY = json.loads((ROOT / ".secrets/clients.json").read_text())["code-agent-acceptance"]["api_key"]
state = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"run_id": "overseas-" + uuid.uuid4().hex, "models": {}}


def save():
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    tmp.replace(MANIFEST)


save()
headers = {
    "Authorization": "Bearer " + KEY,
    "X-User-Id": "code-agent-acceptance",
    "X-Agent-Name": "code-agent",
    "X-Agent-Run-Id": state["run_id"],
    "X-Test-Run-Id": state["run_id"],
}
PROMPT = "A blue ceramic cup on a cream table in soft daylight. Gentle camera movement. No text or people."


def request(item, image, video):
    name = item["innerCode"]
    model = "yseeai--" + name
    path = (item.get("apiPath") or "").split("|")[0]
    if item["modelType"] == "TEXT":
        body = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly OK."}], "max_tokens": 32}
        if path == "/v1/responses":
            body = {"model": model, "input": "Reply with exactly OK.", "max_output_tokens": 32}
        return path, body
    if item["modelType"] == "IMAGE":
        body = {"model": model, "prompt": PROMPT, "n": 1, "size": "2048x2048" if "seedream" in name else "1024x1024"}
        if name.startswith("wan"):
            body["size"] = "1K"
            if "-image" in name:
                body["images"] = [image]
        return "/v1/images", body
    body = {
        "model": model,
        "prompt": PROMPT,
        "duration": 4 if name.startswith("dreamina") else 8 if name.startswith("veo") else 5,
        "resolution": "720p",
        "reference_mode": "text",
    }
    if "-i2v" in name:
        body.update(images=[image], reference_mode="first_frame")
    if "-r2v" in name:
        body.update(images=[image], reference_mode="reference")
    if "videoedit" in name:
        body.update(videos=[video], prompt="Make the lighting warmer, preserve the scene.", reference_mode="reference")
    return "/v1/videos", body


async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8011", headers=headers, timeout=360) as api:
        image_job = (await api.get("/v1/jobs/job-ed5a19a00c4944c7a2b20bade093be43")).json()
        video_job = (await api.get("/v1/jobs/job-7c8dca55c70440ec864b7c8bbedeb7f2")).json()
        image = image_job["result"]["media"][0]["url"]
        video = video_job["result"]["media"][0]["url"]
        # Read-only permission preflight prevents known-denied billable submissions.
        env = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
        async with httpx.AsyncClient(timeout=30) as supplier:
            check = await supplier.get("https://ai-aigc.yseeai.com/v1/models", headers={"Authorization": "Bearer " + env["YSEEAI_API_KEY"]})
            check.raise_for_status()
            permitted = {item["id"] for item in check.json()["data"]}
        state["key_models"] = sorted(permitted)
        save()
        semaphore = asyncio.Semaphore(3)

        async def submit(item):
            name = item["innerCode"]
            if name in state["models"]:
                return
            if not item.get("apiPath") or not item.get("apiBaseUrl"):
                state["models"][name] = {"status": "blocked", "reason": "Provider catalog missing API path/base URL"}
                save()
                return
            if name not in permitted:
                state["models"][name] = {"status": "blocked", "reason": "Current overseas key has not enabled this model"}
                save()
                return
            if name.startswith("dreamactor"):
                state["models"][name] = {
                    "status": "blocked",
                    "reason": "Need person motion video; existing smoke fixture is a landscape, not a valid motion input",
                }
                save()
                return
            async with semaphore:
                path, body = request(item, image, video)
                row = {"status": "submitting", "request_path": path, "request": body, "idempotency_key": state["run_id"] + "-" + name}
                state["models"][name] = row
                save()
                try:
                    response = await api.post(path, json=body, headers={"Idempotency-Key": row["idempotency_key"]})
                    row.update(http_status=response.status_code, response=response.json())
                    row["job_id"] = (
                        row["response"].get("id")
                        if item["modelType"] != "TEXT"
                        else row["response"].get("detail", {}).get("job_id")
                        if isinstance(row["response"].get("detail"), dict)
                        else None
                    )
                    row["status"] = row["response"].get("status", "succeeded" if response.is_success else "failed")
                except Exception as exc:
                    row.update(status="uncertain", error=type(exc).__name__)
                save()
                print(name, row["status"], row.get("http_status"), flush=True)

        if "--poll-only" not in sys.argv:
            await asyncio.gather(*(submit(item) for item in CATALOG))
        for _ in range(480):
            pending = []
            for name, row in state["models"].items():
                if row.get("job_id") and row["status"] not in ("succeeded", "failed"):
                    response = await api.get("/v1/jobs/" + row["job_id"])
                    if response.is_success:
                        row["result"] = response.json()
                        row["status"] = row["result"]["status"]
                    if row["status"] not in ("succeeded", "failed"):
                        pending.append(name)
            save()
            if not pending:
                break
            await asyncio.sleep(10)
        from collections import Counter

        print(dict(Counter(r["status"] for r in state["models"].values())), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
