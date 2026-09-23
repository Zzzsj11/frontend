"""Non-generation provider assets, with caller ownership checks and audit records."""

import json
import os
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from .channels import config, unwrap
from .db import Job, Session
from .security import attribution, digest, owner


async def assets(channel, path, payload, request, client):
    uid = owner(request)
    attrs = attribution(request, client)
    if channel != "yinghe" or path not in {"/v3/assets", "/v3/assets/detail"}:
        raise HTTPException(404)
    base, key = config(channel)
    headers = {"Authorization": "Bearer " + key, "group_id": os.environ.get("YINGHE_ASSET_GROUP_ID", "")}
    if attrs["agent_run_id"]:
        headers.update(
            {"X-Agent-Name": attrs["agent_name"], "X-Agent-Run-Id": attrs["agent_run_id"], "X-Test-Run-Id": attrs["test_run_id"]}
        )
    if path.endswith("/detail"):
        async with Session() as db:
            row = await db.scalar(
                select(Job).where(
                    Job.client_id == client.id,
                    Job.user_id == uid,
                    Job.kind == "asset",
                    Job.provider_id == payload.get("assetId"),
                    Job.deleted_at.is_(None),
                )
            )
        if not row:
            raise HTTPException(404, "Asset not owned by caller")
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(base + path, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()
    idem = request.headers.get("idempotency-key", "")
    if not idem or len(idem) > 200:
        raise HTTPException(400, "Idempotency-Key required")
    if not payload.get("url") or payload.get("assetType") != "Image":
        raise HTTPException(422, "Image asset URL required")
    from .storage import _validate_public_url

    await _validate_public_url(payload["url"])
    sig = digest(json.dumps(payload, sort_keys=True))
    async with Session.begin() as db:
        old = await db.scalar(select(Job).where(Job.client_id == client.id, Job.user_id == uid, Job.idempotency_key == idem))
        if old:
            if old.request_hash != sig:
                raise HTTPException(409, "Idempotency conflict")
            if old.status == "succeeded":
                return old.result
            raise HTTPException(409, "Asset submission already accepted; reconcile existing request")
        row = Job(
            id="asset-" + uuid.uuid4().hex,
            client_id=client.id,
            user_id=uid,
            model_id="asset",
            kind="asset",
            channel=channel,
            protocol="asset",
            payload=payload,
            status="submitting",
            request_hash=sig,
            idempotency_key=idem,
            **attrs,
        )
        db.add(row)
    from .queue import update

    try:
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(base + path, headers={**headers, "Idempotency-Key": row.id}, json=payload)
            r.raise_for_status()
            body = r.json()
            aid = unwrap(body).get("id")
            if not aid:
                raise ValueError("Missing asset ID")
        await update(row.id, status="succeeded", provider_id=aid, result=body)
        return body
    except Exception:
        await update(row.id, status="manual_review", error="Asset submission uncertain")
        raise HTTPException(502, "Asset submission uncertain") from None
