"""Isolated local PostgreSQL contract test; no model requests, database retained for inspection."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import asyncpg
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent / "backend"))
from app.config import settings  # noqa: E402

url = make_url(settings.database_url)
name = "model_service_test_" + uuid.uuid4().hex[:10]


async def create_database():
    conn = await asyncpg.connect(host=url.host, port=url.port, user=url.username, password=url.password, database=url.database)
    await conn.execute("CREATE DATABASE " + name)
    await conn.close()


asyncio.run(create_database())
target = url.set(database=name).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = target
subprocess.run([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"], check=True)
subprocess.run([sys.executable, str(root / "scripts/seed.py")], env={**os.environ, "PYTHONPATH": str(root / "public-api")}, check=True)
sys.path.insert(0, str(root / "public-api"))
from gateway.db import Client, Job, Ledger, Model, PricingRule, Session, engine, now  # noqa: E402
from gateway.queue import claim  # noqa: E402


async def check():
    async with Session.begin() as db:
        db.add(
            Client(
                id="test-client",
                name="concurrency",
                key_hash="a" * 64,
                key_prefix="test",
                concurrency=8,
                allowed_models=[],
                require_agent=True,
            )
        )
        m = await db.get(Model, "veo-3.1-generate-preview")
        m.concurrency = 2
        for i in range(12):
            db.add(
                Job(
                    id=f"job-{i}",
                    client_id="test-client",
                    user_id="test-user",
                    model_id=m.id,
                    kind="video",
                    channel=m.channel,
                    protocol=m.protocol,
                    payload={},
                    request_hash="x",
                    idempotency_key=str(i),
                    origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id="pg-contract",
                    test_run_id="pg-contract",
                )
            )
    claims = await asyncio.gather(*(claim("worker-" + str(i)) for i in range(12)))
    acquired = [x for x in claims if x]
    assert len(acquired) == 2 and len(set(acquired)) == 2, acquired
    (root / ".runtime/postgres-validation.json").write_text(
        json.dumps({"database": name, "parallel_claimers": 12, "model_limit": 2, "claimed": acquired, "passed": True})
    )
    print("PostgreSQL: 12 concurrent claimers, exactly 2 unique leases; no model calls")
    async with Session.begin() as db:
        await db.execute(update(Job).where(Job.client_id == "test-client").values(deleted_at=now()))
        client = await db.get(Client, "test-client")
        client.deleted_at, client.enabled = now(), False
    from gateway.credits import lock, reserve
    from gateway.queue import update as update_job

    async with Session.begin() as db:
        db.add(
            Client(
                id="wallet-client",
                name="isolated wallet test",
                key_hash="b" * 64,
                key_prefix="fixture",
                billing_enabled=True,
                monthly_points=20,
            )
        )
        db.add(
            PricingRule(
                id="fixture-price",
                model_id="veo-3.1-generate-preview",
                actor="test",
                config={
                    "confirmed": True,
                    "reserve_points": "10",
                    "selector": {},
                    "rates": [{"label": "tokens", "path": "completion_tokens", "unit": "1000000", "cny": "2"}],
                },
            )
        )

    async def submit(index):
        async with Session.begin() as db:
            await lock(db)
            c = await db.get(Client, "wallet-client")
            model = await db.get(Model, "veo-3.1-generate-preview")
            j = Job(
                id=f"wallet-job-{index}",
                client_id=c.id,
                user_id="fixture-user",
                model_id=model.id,
                kind="video",
                channel=model.channel,
                protocol=model.protocol,
                payload={"prompt": "fixture"},
                request_hash="fixture",
                idempotency_key=str(index),
                origin="agent_test",
                agent_name="code-agent",
                agent_run_id="pg-wallet",
                test_run_id="pg-wallet",
            )
            try:
                await reserve(db, c, j, model)
                db.add(j)
                return j.id
            except HTTPException as exc:
                assert exc.status_code == 402
                return None

    submissions = await asyncio.gather(*(submit(i) for i in range(12)))
    accepted = [x for x in submissions if x]
    assert len(accepted) == 2
    await asyncio.gather(*(update_job(jid, status="succeeded", usage={"completion_tokens": 1000}) for jid in accepted for _ in range(6)))
    async with Session.begin() as db:
        wallet = await db.get(Client, "wallet-client")
        assert wallet.monthly_balance == Decimal("19.600000")
        entries = (await db.scalars(select(Ledger).where(Ledger.client_id == wallet.id, Ledger.kind == "task_charge"))).all()
        assert len(entries) == 2
        await db.execute(update(Job).where(Job.client_id == wallet.id).values(deleted_at=now()))
        wallet.deleted_at, wallet.enabled = now(), False
    (root / ".runtime/postgres-wallet-validation.json").write_text(
        json.dumps(
            {
                "database": name,
                "parallel_submissions": 12,
                "accepted": 2,
                "settlement_callbacks": 12,
                "charge_entries": 2,
                "balance": "19.600000",
                "model_calls": 0,
                "passed": True,
            }
        )
    )
    print("PostgreSQL wallet: 12 submitters, exactly 2 reservations; 12 callbacks produce 2 charges")
    await engine.dispose()


asyncio.run(check())
