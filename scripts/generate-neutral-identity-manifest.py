#!/usr/bin/env python3
"""Generate audited neutral identity cards through the application API."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def _headers(token: str, run_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Agent-Name": "code-agent",
        "X-Agent-Run-Id": run_id,
        "X-Test-Run-Id": run_id,
    }


def _wait(client: httpx.Client, headers: dict[str, str], task_id: str) -> dict:
    deadline = time.monotonic() + 11 * 60
    while time.monotonic() < deadline:
        response = client.get(f"/api/generations/{task_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        if job.get("status") == "succeeded":
            return job
        if job.get("status") == "failed":
            raise RuntimeError(
                f"{task_id}: {job.get('error') or 'image generation failed'}"
            )
        time.sleep(3)
    raise TimeoutError(f"{task_id}: image generation timed out")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()

    headers = _headers(args.token, args.run_id)
    existing = json.loads(args.output.read_text()) if args.output.exists() else []
    completed = {str(item["id"]) for item in existing}
    with httpx.Client(
        base_url=args.api_base.rstrip("/"), timeout=90, follow_redirects=True
    ) as client:
        with args.template.open("rb") as source:
            uploaded = client.post(
                "/api/uploads?category=agent-neutral-template",
                headers=headers,
                files={"file": (args.template.name, source, "image/png")},
            )
        uploaded.raise_for_status()
        template_url = uploaded.json()["url"]
        response = client.get("/api/digital-humans", headers=headers)
        response.raise_for_status()
        humans = response.json()
        selected = [
            human
            for human in humans
            if human["scope"] == "system" or not human.get("readOnly")
        ]
        if args.ids:
            wanted = set(args.ids)
            selected = [human for human in selected if human["id"] in wanted]
        selected = [human for human in selected if human["id"] not in completed]
        if args.limit is not None:
            selected = selected[: args.limit]
        for index, human in enumerate(selected, 1):
            identity = (
                "，".join(
                    value
                    for value in (human.get("ageDescription"), human.get("gender"))
                    if value
                )
                or human["name"]
            )
            payload = {
                "prompt": "",
                "size": "1344x768",
                "quality": "medium",
                "n": 1,
                "purpose": "digital_human",
                "portrait": {
                    "description": identity,
                    "style": "写实中性人物身份参考卡",
                },
                "images": [
                    template_url,
                    human.get("originalAvatar") or human["avatar"],
                ],
            }
            created = client.post(
                "/api/generations/images", headers=headers, json=payload
            )
            created.raise_for_status()
            job = _wait(client, headers, created.json()["id"])
            result = job.get("result") or {}
            urls = result.get("urls") or []
            if not urls:
                raise RuntimeError(f"{human['id']}: succeeded without output URL")
            existing.append(
                {
                    "id": human["id"],
                    "name": human["name"],
                    "scope": human["scope"],
                    "source_url": human.get("originalAvatar") or human["avatar"],
                    "url": urls[0],
                    "generation_job_id": job["id"],
                }
            )
            args.output.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            print(
                f"generated {index}/{len(selected)} {human['id']} job={job['id']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
