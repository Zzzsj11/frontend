"""Disposable local PostgreSQL concurrency validation; no model calls."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent / "backend"))
from app.config import settings  # noqa: E402

url = make_url(settings.database_url)
assert url.host in {"localhost", "127.0.0.1", "::1"}, "Only an isolated local PostgreSQL target is allowed"
name = "model_quota_test_" + uuid.uuid4().hex[:10]


async def prepare():
    conn = await asyncpg.connect(host=url.host, port=url.port, user=url.username, password=url.password, database=url.database)
    await conn.execute("CREATE DATABASE " + name)
    await conn.close()


asyncio.run(prepare())
os.environ["DATABASE_URL"] = url.set(database=name).render_as_string(hide_password=False)
subprocess.run([sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"], check=True)
sys.path.insert(0, str(root / "public-api"))
from gateway.credits import ensure_key_slot, lock, reserve, reset, user_account  # noqa: E402
from gateway.db import Client, Job, Model, PricingRule, Session, User, engine  # noqa: E402


async def check():
    async with Session.begin() as db:
        db.add(User(id="quota-owner", username="quota@star-net.cn", password_hash="fixture", monthly_points=20))
        for ident in ("a", "b"):
            c = Client(
                id=ident,
                name=ident,
                user_id="quota-owner",
                key_hash=ident * 64,
                key_prefix="fixture",
                billing_enabled=True,
                monthly_points=100,
                monthly_balance=0,
                extra_balance=0,
                billing_month="",
            )
            db.add(c)
            await db.flush()
            await reset(db, c)
        db.add(
            PricingRule(
                id="quota-price", model_id="gpt-5.6-sol", actor="test", config={"confirmed": True, "reserve_points": "10", "rates": []}
            )
        )

    async def submit(i):
        try:
            async with Session.begin() as db:
                await lock(db)
                c = await db.get(Client, "a" if i % 2 else "b")
                m = await db.get(Model, "gpt-5.6-sol")
                j = Job(
                    id=f"quota-{i}",
                    client_id=c.id,
                    user_id=c.user_id,
                    model_id=m.id,
                    kind=m.kind,
                    channel=m.channel,
                    protocol=m.protocol,
                    payload={},
                    request_hash="fixture",
                    idempotency_key=str(i),
                    origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id=name,
                    test_run_id=name,
                )
                await reserve(db, c, j, m)
                db.add(j)
            return 202
        except HTTPException as exc:
            return exc.status_code

    results = await asyncio.gather(*(submit(i) for i in range(8)))
    assert sorted(results) == [202] * 2 + [402] * 6, results

    async def create(i):
        try:
            async with Session.begin() as db:
                await lock(db)
                await ensure_key_slot(db, "quota-owner")
                db.add(Client(id=f"new-{i}", name="fixture", user_id="quota-owner", key_hash=f"new-{i}", key_prefix="fixture"))
            return 201
        except HTTPException as exc:
            return exc.status_code

    results = await asyncio.gather(*(create(i) for i in range(12)))
    assert sorted(results) == [201] * 8 + [409] * 4, results
    async with Session() as db:
        user = await db.get(User, "quota-owner")
        view = await user_account(db, user)
        assert view["key_count"] == 10 and view["reserved_points"] == "20.000000"
        assert len((await db.scalars(select(Job))).all()) == 2
    await engine.dispose()
    print(
        "PostgreSQL account limits passed: 8 concurrent submissions -> 2 accepted; 12 concurrent key creations -> 10 total. Zero model calls."
    )


asyncio.run(check())
