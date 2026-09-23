"""Recover already-paid comparison images through the explicitly configured local proxy."""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k] = v
sys.path.insert(0, str(ROOT / "public-api"))
from gateway import media  # noqa: E402
from gateway.db import Audit, Job, Session  # noqa: E402
from gateway.storage import _validate_public_url  # noqa: E402


async def download(url, max_bytes):
    async with httpx.AsyncClient(proxy="http://127.0.0.1:7897", timeout=180, follow_redirects=False) as c:
        for _ in range(4):
            await _validate_public_url(url)
            async with c.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers["location"])
                    continue
                r.raise_for_status()
                chunks = []
                size = 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Image too large")
                    chunks.append(chunk)
                return url, b"".join(chunks), r.headers.get("content-type", "image/png")
    raise ValueError("Too many redirects")


async def main():
    media.download_public_url = download
    async with Session() as db:
        jobs = (
            await db.scalars(
                select(Job).where(
                    Job.kind == "image", Job.status == "recoverable", Job.agent_run_id == "paired-fbd21e7300064b60952fb36714e89a05"
                )
            )
        ).all()
    for j in jobs:
        try:
            result = await media.archive(j, j.provider_response)
            async with Session.begin() as db:
                row = await db.get(Job, j.id)
                if row.status != "recoverable":
                    continue
                row.result = result
                row.status = "succeeded"
                row.error = None
                db.add(
                    Audit(
                        id=__import__("uuid").uuid4().hex,
                        actor="code-agent",
                        action="job.archive_recovered",
                        target=j.id,
                        detail={"generated": False, "original_provider_task_id": j.provider_id},
                    )
                )
            print(j.model_id, "archive recovered", flush=True)
        except Exception as e:
            print(j.model_id, type(e).__name__, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
