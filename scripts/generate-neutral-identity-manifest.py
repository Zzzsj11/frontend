#!/usr/bin/env python3
"""Generate system-only headshots; reconcile interrupted jobs before resubmitting."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
from pathlib import Path
from threading import Event, Lock
from urllib.parse import urlsplit

import httpx


def _http_url(value: object) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("image/API URL must be a non-empty HTTP(S) URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port == 0:
        raise ValueError("image/API URL must be HTTP(S), without credentials and with a valid port")
    return value


def _headers(token: str, run_id: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", run_id):
        raise ValueError("run-id must contain 1–160 ASCII letters, digits, dots, underscores or hyphens")
    if not re.fullmatch(r"[!-~]+", token):
        raise ValueError("token must be non-empty ASCII without whitespace")
    return {
        "Authorization": f"Bearer {token}",
        "X-Agent-Name": "code-agent",
        "X-Agent-Run-Id": run_id,
        "X-Test-Run-Id": run_id,
    }


def _wait(client: httpx.Client, headers: dict[str, str], task_id: str, stop: Event) -> dict:
    deadline = time.monotonic() + 11 * 60
    while time.monotonic() < deadline:
        if stop.is_set():
            raise InterruptedError(f"{task_id}: polling paused; resume the saved job")
        response = client.get(f"/api/generations/{task_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        if job.get("status") == "succeeded":
            return job
        if job.get("status") == "failed":
            raise RuntimeError(
                f"{task_id}: {job.get('error') or 'image generation failed'}"
            )
        stop.wait(3)
    raise TimeoutError(f"{task_id}: image generation timed out")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+", help="System human IDs only")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    try:
        headers = _headers(args.token, args.run_id)
        _http_url(args.api_base)
        if args.limit is not None and args.limit < 0:
            raise ValueError("limit must be non-negative")
        if args.concurrency < 1:
            raise ValueError("concurrency must be positive")
        args.output = args.output.resolve()
        if not args.output.parent.is_dir():
            raise ValueError("output parent directory must already exist")
        existing = json.loads(args.output.read_text()) if args.output.exists() else []
        if not isinstance(existing, list):
            raise ValueError("output must be a JSON array of completed or resumable rows")
        completed = set()
        saved = {}
        for item in existing:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                raise ValueError("output rows must have non-empty string ids")
            if item.get("scope", "system") != "system" or item.get("user_id") is not None:
                raise ValueError("output contains a non-system human; private humans require manual updates")
            if item["id"] in saved:
                raise ValueError("output contains duplicate ids")
            saved[item["id"]] = item
            if item.get("url"):
                _http_url(item["url"])
                completed.add(item["id"])
                continue
            job_id = item.get("generation_job_id")
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", job_id):
                raise ValueError(f"{item['id']}: no confirmed job ID; reconcile generation jobs before retrying")
            if item.get("run_id") != args.run_id or item.get("api_base") != args.api_base.rstrip("/"):
                raise ValueError("resume requires the original run-id and api-base")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    with httpx.Client(
        base_url=args.api_base.rstrip("/"), timeout=90, follow_redirects=False
    ) as client:
        response = client.get("/api/digital-humans", headers=headers)
        response.raise_for_status()
        humans = response.json()
        if not isinstance(humans, list) or any(not isinstance(human, dict) for human in humans):
            parser.error("API must return a JSON array of humans")
        selected = [human for human in humans if human.get("scope") == "system" and human.get("user_id") is None]
        if any(not isinstance(human.get("id"), str) or not human["id"].strip() for human in selected):
            parser.error("API system humans must have non-empty string ids")
        if args.ids:
            wanted = set(args.ids)
            unavailable = wanted - {human["id"] for human in selected}
            if unavailable:
                parser.error(f"ids are not available system humans: {sorted(unavailable)}")
            selected = [human for human in selected if human["id"] in wanted]
        selected = [human for human in selected if human["id"] not in completed]
        if args.limit is not None:
            selected = selected[: args.limit]
        if len({human["id"] for human in selected}) != len(selected):
            parser.error("API returned duplicate system human ids")
        # Validate the entire batch before any paid submission.
        for human in selected:
            _http_url(human.get("originalAvatar") or human.get("avatar"))
            if any(human.get(key) is not None and not isinstance(human[key], str) for key in ("ageDescription", "gender", "name")):
                parser.error(f"invalid identity fields for {human['id']}")

        stop = Event()
        save_lock = Lock()

        def save(row: dict) -> None:
            # Workers persist acknowledgements themselves, even after the main thread is interrupted.
            with save_lock:
                saved[row["id"]] = row
                temporary = args.output.with_name(args.output.name + ".tmp")
                temporary.write_text(json.dumps(list(saved.values()), ensure_ascii=False, indent=2))
                temporary.replace(args.output)

        def generate_one(human: dict) -> dict:
            if stop.is_set():
                raise InterruptedError("submission cancelled before starting")
            identity = "，".join(
                value.strip()
                for value in (human.get("ageDescription"), human.get("gender"))
                if value and value.strip()
            )
            payload = {
                "prompt": "",
                "model": "gpt-image-2.5-sunburst",  # Yinghe only, never an environment-dependent channel.
                "size": "1024x1536",
                "quality": "medium",
                "n": 1,
                "purpose": "digital_human",
                "portrait": {
                    "description": (identity + "。" if identity else "")
                    + "仅以参考图锁定人物五官、脸型、肤色、年龄感和发型；"
                    "卡通人物保持卡通风格，儿童保持儿童年龄和比例，不得成人化。"
                    "单张竖版头肩大头照，正面居中，完整头顶与双肩，面部占画面主体；"
                    "纯白无图案T恤、纯灰背景；不要全身、三视图、拼图、文字或水印。",
                    "style": "",
                },
                "images": [human.get("originalAvatar") or human["avatar"]],
            }
            row = saved.get(human["id"])
            with httpx.Client(
                base_url=args.api_base.rstrip("/"), timeout=90, follow_redirects=False
            ) as worker_client:
                if row is None:
                    if stop.is_set():
                        raise InterruptedError("submission cancelled before starting")
                    row = {
                        "id": human["id"],
                        "name": human.get("name") or "",
                        "scope": human["scope"],
                        "code": human.get("assetCode"),
                        "source_url": human.get("originalAvatar") or human["avatar"],
                        "run_id": args.run_id,
                        "api_base": args.api_base.rstrip("/"),
                        "status": "submitting",
                    }
                    # An ambiguous POST must never become an automatic paid retry.
                    save(row)
                    if stop.is_set():
                        raise InterruptedError("submission cancelled; reconcile saved intent")
                    created = worker_client.post(
                        "/api/generations/images", headers=headers, json=payload
                    )
                    created.raise_for_status()
                    row = {**row, "generation_job_id": created.json()["id"], "status": "submitted"}
                    save(row)
                job = _wait(worker_client, headers, row["generation_job_id"], stop)
            result = job.get("result") or {}
            urls = result.get("urls") or []
            if not urls:
                raise RuntimeError(f"{human['id']}: succeeded without output URL")
            row = {**row, "url": _http_url(urls[0]), "status": "succeeded"}
            save(row)
            return row

        workers = min(args.concurrency, 8)
        failures = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        futures = {}
        remaining = iter(selected)
        finished = 0
        try:
            while True:
                # Bound the queue; never enqueue the whole paid batch.
                while len(futures) < workers:
                    human = next(remaining, None)
                    if human is None:
                        break
                    futures[executor.submit(generate_one, human)] = human
                if not futures:
                    break
                done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    human = futures.pop(future)
                    finished += 1
                    try:
                        row = future.result()
                    except Exception as exc:
                        failures.append(f"{human['id']}: {exc}")
                        continue  # Workers have already saved all acknowledged jobs/results.
                    print(f"generated {finished}/{len(selected)} {row['id']} job={row['generation_job_id']}", flush=True)
        finally:
            stop.set()
            # Cancel unstarted work; in-flight POSTs save their job IDs before polling stops.
            executor.shutdown(wait=True, cancel_futures=True)
        if failures:
            raise RuntimeError("Check existing generation jobs before retrying: " + "; ".join(failures))


if __name__ == "__main__":
    main()
