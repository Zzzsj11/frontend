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
    from app.worker import _claim, _claim_batch, _recover_stale
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
        # Mixed-version exports have only a kind, with no execution pool in the request.
        async with session_factory.begin() as db:
            db.add_all(
                GenerationJobModel(
                    id=f"zip-{i}", kind="export", user_id="local-proof-user", request={}
                )
                for i in range(12)
            )
        replicas = await asyncio.gather(
            *(
                _claim_batch(("export", "mv_export"), (), f"zip-worker-{i}", "", 20)
                for i in range(3)
            )
        )
        claimed_zips = [job for batch in replicas for job in batch]
        assert len(claimed_zips) == 5
        async with session_factory.begin() as db:
            (await db.get(GenerationJobModel, claimed_zips[0].id)).status = "succeeded"
        assert len(await _claim_batch(("export",), (), "zip-refill", "", 20)) == 1
        print(
            "PASS: three PostgreSQL workers share five material ZIP slots across claims and refill"
        )
        # Saturate one model pool ahead of another; a lost Redis key cannot erase PG occupancy.
        async with session_factory.begin() as db:
            for index in range(103):
                db.add(
                    GenerationJobModel(
                        id=f"local-pool-{index:03d}",
                        user_id="local-proof-user",
                        kind="pool-proof",
                        request={
                            "_executionPool": "slow" if index < 102 else "fast",
                            "_executionConcurrency": 1,
                        },
                    )
                )
        first = await _claim(("pool-proof",), (), "local-first")
        assert (
            first
            and first.database_pool_reserved
            and first.request["_executionPool"] == "slow"
        )
        await redis.delete("execution-pool:slow")
        remaining = await asyncio.gather(
            *(_claim(("pool-proof",), (), f"local-other-{i}") for i in range(10))
        )
        second = [item for item in remaining if item]
        assert len(second) == 1 and second[0].request["_executionPool"] == "fast"
        assert not await _claim(("pool-proof",), (), "local-extra")
        from app.redis_store import notify_worker, wait_for_worker_wakeup
        from app.worker_queues import VIDEO_POOLS

        await asyncio.gather(*(notify_worker("video:wan") for _ in range(20)))
        assert await redis.llen("worker:ready:video:wan") == 1
        await wait_for_worker_wakeup(1, ("video:wan",))
        assert not await redis.exists("worker:ready:video:wan:first")

        async with session_factory.begin() as db:
            db.add_all(
                [
                    GenerationJobModel(
                        id=f"video-pressure-{queue}-{i}",
                        kind="video",
                        request={"_executionPool": pool, "_executionConcurrency": 1},
                        generation_origin="agent_test",
                        agent_name="code-agent",
                        agent_run_id="local-proof-video",
                    )
                    for queue, pool in VIDEO_POOLS.items()
                    for i in range(1001)
                ]
            )

        async def fill(queue, replica):
            count = 0
            while batch := await _claim_batch(("video",), (), replica, queue, 32):
                assert all(
                    job.request["_executionPool"] == VIDEO_POOLS[queue] for job in batch
                )
                count += len(batch)
            return count

        claims = await asyncio.gather(
            *(fill(q, f"proof-{q}-{r}") for q in VIDEO_POOLS for r in range(2))
        )
        assert sum(claims[:2]) == sum(claims[2:]) == 1000, claims
        async with session_factory.begin() as db:
            db.add(
                GenerationJobModel(id="video-other-pressure", kind="video", request={})
            )
        assert not await _claim_batch(("video",), (), "overflow", "video:other", 1)
        from app.config import settings
        from app.text_admission import (
            _acquire_text_slot,
            _release_text_slot,
            _renew_text_slot,
        )

        reserved = [
            await _acquire_text_slot()
            for _ in range(settings.text_generation_concurrency)
        ]
        assert all(reserved) and not await _acquire_text_slot()
        assert await _renew_text_slot(reserved[0])
        await _release_text_slot(reserved[0])
        assert not await _renew_text_slot(reserved[0]) and await _acquire_text_slot()
        print(
            "PASS: durable cross-worker media and text slots, saturated-pool bypass and owner fencing"
        )
        # Exercise real admission entry points; dispatch is replaced at the model boundary.
        from dataclasses import replace
        from unittest.mock import AsyncMock, patch

        from app import domain, main
        from app.agent_attribution import attribution_context
        from app.jobs import jobs
        from app.models import (
            DailyUsageQuotaModel,
            ProjectModel,
            ProjectTaskModel,
            StoryboardLineModel,
        )
        from app.schemas import ImageGenerationCreate, StoryboardLineGenerate
        from fastapi import HTTPException

        owner_id = "local-admission-user"
        async with session_factory.begin() as db:
            db.add(
                UserModel(
                    id=owner_id,
                    username=owner_id,
                    password_hash="fixture",
                    daily_chat_limit=2,
                )
            )
            await db.flush()
            db.add(ProjectModel(id="proof-project", name="fixture", user_id=owner_id))
            await db.flush()
            db.add(
                ProjectTaskModel(
                    id="proof-storyboard",
                    title="fixture",
                    project_id="proof-project",
                    storyboard_type="general",
                )
            )
            await db.flush()
            for n in range(3):
                db.add(
                    StoryboardLineModel(
                        id=f"proof-line-{n}",
                        project_task_id="proof-storyboard",
                        sort_order=n,
                        planned_duration=5,
                    )
                )

        async def submit(kind):
            async with session_factory() as db:
                user = await db.get(UserModel, owner_id)
                try:
                    if kind == "image":
                        await main.create_image_generation(
                            ImageGenerationCreate(
                                model="nano-banana-2.1-all-in-one", prompt="synthetic"
                            ),
                            user,
                            db,
                        )
                    else:
                        await domain.generate_one_storyboard_line(
                            "proof-storyboard",
                            "proof-line-0",
                            StoryboardLineGenerate(),
                            user,
                            db,
                        )
                    return 202
                except HTTPException as exc:
                    return exc.status_code

        with (
            attribution_context("agent_test", "code-agent", "local-admission-proof"),
            patch.object(jobs, "dispatch", AsyncMock()) as dispatch,
            patch.object(
                main,
                "settings",
                replace(
                    main.settings,
                    image_generation_concurrency=1,
                    all_in_one_api_key="fixture-only",
                ),
            ),
            patch.object(
                domain,
                "settings",
                replace(domain.settings, job_execution_mode="worker"),
            ),
        ):
            assert sorted(await asyncio.gather(submit("image"), submit("image"))) == [
                202,
                429,
            ]
            assert sorted(await asyncio.gather(submit("line"), submit("line"))) == [
                202,
                409,
            ]
            async with session_factory() as db:
                try:
                    await domain._submit_storyboard_lines(
                        db,
                        "proof-storyboard",
                        ["proof-line-1", "proof-line-2"],
                        True,
                        await db.get(UserModel, owner_id),
                        batch=True,
                    )
                except HTTPException as exc:
                    assert exc.status_code == 429
                else:
                    raise AssertionError("quota failure expected")
            assert dispatch.await_count == 2
        async with session_factory() as db:
            quotas = dict(
                (
                    await db.execute(
                        select(
                            DailyUsageQuotaModel.category,
                            DailyUsageQuotaModel.usage_count,
                        ).where(DailyUsageQuotaModel.user_id == owner_id)
                    )
                ).all()
            )
            assert quotas == {"image": 1, "chat": 1}
            assert (
                await db.get(StoryboardLineModel, "proof-line-1")
            ).generation_status == "pending"
        print(
            "PASS: atomic image and storyboard admission; partial batch quota failure rolls back"
        )
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
