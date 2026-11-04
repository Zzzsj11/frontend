"""Synthetic PostgreSQL/Redis queue proof; all external sockets are blocked."""

from __future__ import annotations

import asyncio
import os
import socket
from datetime import timedelta
from urllib.parse import urlsplit


def restrict_network():
    for name in ("DATABASE_URL", "REDIS_URL"):
        parsed = urlsplit(os.environ[name])
        if parsed.hostname != "127.0.0.1" or (
            name == "DATABASE_URL" and parsed.path != "/mv_local_proof"
        ):
            raise RuntimeError("Proof requires disposable loopback dependencies")
    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("External network is forbidden in local proof")
        return original(sock, address)

    socket.socket.connect = connect


async def proof():
    from app.database import close_database, session_factory
    from app.models import GenerationJobModel, UserModel, utcnow
    from app.redis_store import (
        acquire_execution_lease,
        close_redis,
        redis,
        release_execution_lease,
    )
    from app.worker import _claim, _recover_stale
    from sqlalchemy import select

    try:
        assert await redis.ping()
        async with session_factory.begin() as db:
            db.add(
                UserModel(
                    id="local-proof-user",
                    username="local-proof-user",
                    password_hash="not-a-login-credential",
                )
            )
            await db.flush()
            db.add(
                GenerationJobModel(
                    id="local-proof-job",
                    user_id="local-proof-user",
                    kind="general_outline",
                    request={},
                    generation_origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id="synthetic-local-proof",
                )
            )
        from app.generation_preferences import GenerationPreference, save_preference
        from app.models import AiModelModel

        # Auth preloads both users before either request locks the row.
        async with session_factory() as first, session_factory() as second:
            owners = await asyncio.gather(
                first.get(UserModel, "local-proof-user"),
                second.get(UserModel, "local-proof-user"),
            )
            async with session_factory() as catalog:
                codes = {}
                for modality in ("image", "video"):
                    codes[modality] = await catalog.scalar(
                        select(AiModelModel.code)
                        .where(
                            AiModelModel.modality == modality,
                            AiModelModel.status == "active",
                            AiModelModel.user_visible.is_(True),
                            AiModelModel.deleted_at.is_(None),
                        )
                        .limit(1)
                    )
                    assert codes[modality], "Migrated model catalog is missing"
            await asyncio.gather(
                save_preference(
                    "image",
                    GenerationPreference(model=codes["image"]),
                    owners[0],
                    first,
                ),
                save_preference(
                    "video",
                    GenerationPreference(model=codes["video"]),
                    owners[1],
                    second,
                ),
            )
        async with session_factory() as check:
            saved = (
                await check.get(UserModel, "local-proof-user")
            ).generation_preferences
            assert set(saved) == {"image", "video"}, saved
        print("PASS: concurrent PostgreSQL preference saves preserve both modalities")
        claims = await asyncio.gather(
            *(_claim(("general_outline",), (), f"local-worker-{i}") for i in range(12))
        )
        assert sum(job is not None for job in claims) == 1, (
            "Concurrent workers claimed the same job"
        )
        async with session_factory.begin() as db:
            job = await db.get(GenerationJobModel, "local-proof-job")
            job.lease_expires_at = utcnow() - timedelta(seconds=1)
        assert (await _recover_stale(("general_outline",), ()))[0] == 1
        recovered = await _claim(("general_outline",), (), "recovery-worker")
        assert recovered and recovered.attempt == 2
        async with session_factory.begin() as db:
            job = await db.get(GenerationJobModel, "local-proof-job")
            job.status, job.deleted_at = "queued", utcnow()
        assert await _claim(("general_outline",), (), "must-not-claim-deleted") is None
        # Separate Redis client connections execute the actual atomic Lua gate.
        tokens = await asyncio.gather(
            *(acquire_execution_lease("local-proof-pool", 3, 60) for _ in range(20))
        )
        acquired = [token for token in tokens if token]
        assert len(acquired) == 3 and "redis-unavailable" not in acquired
        await asyncio.gather(
            *(release_execution_lease("local-proof-pool", token) for token in acquired)
        )
        assert await acquire_execution_lease("local-proof-pool", 3, 60)
        async with session_factory() as db:
            assert await db.scalar(
                select(UserModel.id).where(UserModel.id == "local-proof-user")
            )
        print(
            "PASS: PostgreSQL 12 claimants -> one lease; stale recovery; soft-delete exclusion; Redis 20 admissions -> 3 slots; zero model calls"
        )
    finally:
        await close_redis()
        await close_database()


if __name__ == "__main__":
    restrict_network()
    asyncio.run(proof())
