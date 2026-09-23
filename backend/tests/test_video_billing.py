from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import session_factory
from app.models import Base, DigitalHumanModel, GenerationJobModel, TokenUsageModel, VideoBillingRecordModel, VideoPricingRuleModel
from app.video_billing import reconcile_video_billing, reconcile_video_job


async def _seed_billing_fixtures() -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add(
            DigitalHumanModel(
                id="billing-human",
                user_id="user-admin",
                name="费用详情人物",
                avatar_url="https://tos.test/billing-human.jpg",
                asset_avatar_url="asset://billing-human-1",
                scope="private",
                deleted_at=now,
            )
        )
        for rule in (
            VideoPricingRuleModel(
                id="test-price-sd-720",
                model="doubao-seedance-2.0",
                provider="",
                resolution="720p",
                usage_type="completion_tokens",
                unit_size=1_000_000,
                unit_price=46,
                currency="CNY",
                effective_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                status="active",
                notes="test",
            ),
            VideoPricingRuleModel(
                id="test-price-h3-720",
                model="minimax-h3",
                provider="yinghe-h3",
                resolution="720p",
                usage_type="output_seconds",
                unit_size=1,
                unit_price=Decimal("0.425"),
                currency="CNY",
                effective_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                status="active",
                notes="test",
            ),
            VideoPricingRuleModel(
                id="test-price-sd-mini-720",
                model="doubao-seedance-2.0-mini",
                provider="yinghe",
                resolution="720p",
                usage_type="completion_tokens",
                unit_size=1_000_000,
                unit_price=23,
                currency="CNY",
                effective_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                status="active",
                notes="test",
            ),
            VideoPricingRuleModel(
                id="test-price-wan-prime-720",
                model="wan3.0-video-prime",
                provider="yinghe",
                resolution="720p",
                usage_type="output_seconds",
                unit_size=1,
                unit_price=Decimal("0.9"),
                currency="CNY",
                effective_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
                status="active",
                notes="test",
            ),
        ):
            db.add(rule)
        jobs = (
            GenerationJobModel(
                id="billing-sd-ok",
                user_id="user-admin",
                kind="video",
                status="succeeded",
                request={"model": "doubao-seedance-2.0", "resolution": "720p"},
                provider="yinghe",
                finished_at=now,
            ),
            GenerationJobModel(
                id="billing-h3-failed",
                user_id="user-admin",
                kind="video",
                status="failed",
                request={
                    "model": "minimax-h3",
                    "resolution": "720p",
                    "duration": 12,
                    "prompt": "最终 H3 提示词",
                    "_sourcePrompt": "原始业务提示词",
                    "image_urls": ["asset://billing-human-1", "https://example.com/reference.jpg"],
                },
                provider="yinghe-h3",
                error="供应商失败",
                started_at=now - timedelta(seconds=96),
                finished_at=now,
                deleted_at=now,
                generation_origin="agent_test",
                agent_name="code-agent",
                agent_run_id="agent-test-billing-001",
            ),
            GenerationJobModel(
                id="billing-rh-failed",
                user_id="user-admin",
                kind="video",
                status="failed",
                request={"model": "minimax-h3-runninghub", "resolution": "720p"},
                provider="runninghub",
                error="工作流失败",
                finished_at=now,
            ),
            GenerationJobModel(
                id="billing-sd-mini-ok",
                user_id="user-admin",
                kind="video",
                status="succeeded",
                request={"model": "doubao-seedance-2.0-mini", "resolution": "720p"},
                provider="yinghe",
                finished_at=now,
            ),
            GenerationJobModel(
                id="billing-wan-prime-ok",
                user_id="user-admin",
                kind="video",
                status="succeeded",
                request={"model": "wan3.0-video-prime", "resolution": "720p", "duration": 4},
                provider="yinghe",
                finished_at=now,
            ),
        )
        db.add_all(jobs)
        db.add_all(
            (
                TokenUsageModel(
                    id="billing-usage-sd",
                    user_id="user-admin",
                    generation_job_id="billing-sd-ok",
                    operation="generation_video",
                    provider="yinghe",
                    model="doubao-seedance-2.0",
                    output_tokens=100_000,
                    total_tokens=100_000,
                    raw_usage={"completion_tokens": 100_000},
                ),
                TokenUsageModel(
                    id="billing-usage-h3",
                    user_id="user-admin",
                    generation_job_id="billing-h3-failed",
                    operation="generation_video_failed",
                    provider="yinghe-h3",
                    model="minimax-h3",
                    raw_usage={"output_seconds": 12},
                    deleted_at=now,
                ),
                TokenUsageModel(
                    id="billing-usage-rh",
                    user_id="user-admin",
                    generation_job_id="billing-rh-failed",
                    operation="generation_video_failed",
                    provider="runninghub",
                    model="minimax-h3-runninghub",
                    raw_usage={"consumeCoins": 80},
                ),
                TokenUsageModel(
                    id="billing-usage-sd-mini",
                    user_id="user-admin",
                    generation_job_id="billing-sd-mini-ok",
                    operation="generation_video",
                    provider="yinghe",
                    model="doubao-seedance-2.0-mini",
                    output_tokens=100_000,
                    total_tokens=100_000,
                    raw_usage={"completion_tokens": 100_000},
                ),
                TokenUsageModel(
                    id="billing-usage-wan-prime",
                    user_id="user-admin",
                    generation_job_id="billing-wan-prime-ok",
                    operation="generation_video",
                    provider="yinghe",
                    model="wan3.0-video-prime",
                    raw_usage={"output_seconds": 4},
                ),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_video_billing_reconciles_success_failed_and_excluded(client):
    await _seed_billing_fixtures()
    reconciled = client.post("/api/admin/video-billing/reconcile")
    assert reconciled.status_code == 200
    assert reconciled.json()["jobId"].startswith("job-")
    async with session_factory() as db:
        result = await reconcile_video_billing(db)
        await db.commit()
    assert result["processed"] >= 3

    response = client.get("/api/admin/video-billing", params={"q": "billing-", "limit": 20})
    assert response.status_code == 200
    items = {item["generationJobId"]: item for item in response.json()["items"]}
    assert items["billing-sd-ok"]["amount"] == pytest.approx(3.818)
    assert items["billing-sd-ok"]["unitPrice"] == pytest.approx(38.18)
    assert items["billing-sd-ok"]["listUnitPrice"] == pytest.approx(46)
    assert items["billing-sd-ok"]["discountRate"] == pytest.approx(0.83)
    assert items["billing-sd-ok"]["discountLabel"] == "英和 83 折"
    assert "原价 ¥46" in items["billing-sd-ok"]["rateLabel"]
    assert items["billing-h3-failed"]["isFailed"] is True
    assert items["billing-h3-failed"]["billingStatus"] == "priced"
    assert items["billing-h3-failed"]["amount"] == pytest.approx(5.1)
    assert items["billing-h3-failed"]["durationSeconds"] == 12
    assert items["billing-h3-failed"]["generationElapsedSeconds"] == 96
    assert items["billing-h3-failed"]["rateLabel"] == "¥0.425 / 秒"
    assert items["billing-h3-failed"]["generationOrigin"] == "agent_test"
    assert items["billing-h3-failed"]["agentRunId"] == "agent-test-billing-001"
    assert items["billing-rh-failed"]["billingStatus"] == "excluded"
    assert items["billing-rh-failed"]["amount"] == 0
    assert items["billing-sd-mini-ok"]["amount"] == pytest.approx(2.3)
    assert items["billing-sd-mini-ok"]["rateLabel"] == "¥23 / 100万 Token"
    assert items["billing-wan-prime-ok"]["amount"] == pytest.approx(3.6)
    assert items["billing-wan-prime-ok"]["rateLabel"] == "¥0.9 / 秒"

    failed = client.get("/api/admin/video-billing", params={"status": "failed", "q": "billing-"}).json()
    assert {item["generationJobId"] for item in failed["items"]} == {"billing-h3-failed", "billing-rh-failed"}
    assert failed["summary"]["failedRecords"] == 2

    detail = client.get(f"/api/admin/video-billing/{items['billing-h3-failed']['id']}")
    assert detail.status_code == 200
    assert detail.json()["prompts"] == [
        {"label": "最终提交提示词", "content": "最终 H3 提示词"},
        {"label": "原始业务提示词", "content": "原始业务提示词"},
    ]
    assert detail.json()["references"][0] == {
        "label": "图片 1",
        "type": "图片",
        "url": "https://tos.test/billing-human.jpg",
        "providerUrl": "asset://billing-human-1",
    }
    assert detail.json()["references"][1]["url"] == "https://example.com/reference.jpg"
    assert detail.json()["rawUsage"] == {"output_seconds": 12}
    assert detail.json()["generationOrigin"] == "agent_test"
    assert detail.json()["generationElapsedSeconds"] == 96

    agent_only = client.get("/api/admin/video-billing", params={"origin": "agent_test", "q": "billing-"}).json()
    assert agent_only["total"] == 1
    assert agent_only["summary"]["agentTestRecords"] == 1

    first_page = client.get("/api/admin/video-billing", params={"q": "billing-", "limit": 1, "offset": 0}).json()
    second_page = client.get("/api/admin/video-billing", params={"q": "billing-", "limit": 1, "offset": 1}).json()
    assert first_page["total"] == second_page["total"] == 5
    assert len(first_page["items"]) == len(second_page["items"]) == 1
    assert first_page["items"][0]["id"] != second_page["items"][0]["id"]
    assert first_page["summary"] == second_page["summary"]

    # 重复核算必须更新同一工单账单，不得重复入账。
    assert client.post("/api/admin/video-billing/reconcile").status_code == 200
    assert client.get("/api/admin/video-billing", params={"q": "billing-"}).json()["total"] == 5


def test_video_billing_requires_admin(client):
    created = client.post("/api/admin/users", json={"username": "billing-normal-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "billing-normal-user", "password": "secure-pass-123"}).json()
    headers = {"Authorization": f"Bearer {login['accessToken']}"}
    assert client.get("/api/admin/video-billing", headers=headers).status_code == 403
    assert client.post("/api/admin/video-billing/reconcile", headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")


def test_generation_job_persists_agent_request_attribution(client, monkeypatch):
    async def no_dispatch(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.main.jobs.dispatch", no_dispatch)
    response = client.post(
        "/api/generations/videos",
        json={"prompt": "Agent 归因测试", "duration": 5, "model": "doubao-seedance-2.0"},
        headers={"X-Test-Run-Id": "agent-real-generation-001", "X-Agent-Name": "code-agent", "X-Agent-Run-Id": "agent-real-generation-001"},
    )
    assert response.status_code == 202

    async def load_job():
        async with session_factory() as db:
            return (await db.execute(select(GenerationJobModel).where(GenerationJobModel.id == response.json()["id"]))).scalar_one()

    job = asyncio.run(load_job())
    assert job.generation_origin == "agent_test"
    assert job.agent_name == "code-agent"
    assert job.agent_run_id == "agent-real-generation-001"


@pytest.fixture
async def billing_db():
    # No application startup or provider calls: each test owns an in-memory database.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


async def _seed_billing_snapshot(db, *, model="retired-model", provider="historical-provider", deleted_rule=False, with_record=True, suffix="snapshot"):
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    rule = VideoPricingRuleModel(
        id=f"rule-{suffix}",
        model=model,
        provider="yinghe-h3" if model == "minimax-h3" and provider == "yinghe" else provider,
        resolution="720p",
        usage_type="output_seconds",
        unit_size=1,
        unit_price=Decimal("2"),
        currency="EUR",
        effective_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        deleted_at=now if deleted_rule else None,
    )
    job = GenerationJobModel(
        id=f"job-{suffix}",
        kind="video",
        status="succeeded",
        provider=provider,
        request={"model": model, "resolution": "720p", "duration": 8},
        result={"videoUrl": "https://tos.test/historical.mp4", "duration": 8},
        finished_at=now,
        deleted_at=now,
    )
    usage = TokenUsageModel(
        id=f"usage-{suffix}",
        generation_job_id=job.id,
        operation="generation_video",
        provider=provider,
        model=model,
        output_tokens=200_000,
        total_tokens=200_000,
        raw_usage={"completion_tokens": 200_000, "output_seconds": 8, "consumeCoins": 16},
        deleted_at=now,
    )
    db.add_all([rule, job, usage])
    record = None
    if with_record:
        record = VideoBillingRecordModel(
            id=f"record-{suffix}",
            generation_job_id=job.id,
            pricing_rule_id=rule.id,
            provider=provider,
            model=model,
            resolution="1080p",
            generation_status="failed",
            is_failed=True,
            billing_status="priced",
            usage_type="output_seconds",
            usage_quantity=Decimal("12.5"),
            usage_unit="seconds",
            unit_price=Decimal("0.625"),
            amount=Decimal("7.8125"),
            currency="USD",
            raw_usage={"rawUsage": {"output_seconds": 12.5}, "requestId": "historical-request"},
            completed_at=now - timedelta(days=1),
        )
        db.add(record)
    await db.commit()
    for row in (job, usage, rule, record):
        if row is not None:
            await db.refresh(row)
    return job, usage, rule, record


def _row_snapshot(row):
    return {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}


async def _reconcile_snapshot(db, job, usage, record, path):
    if path == "batch":
        return await reconcile_video_billing(db, job_ids=[job.id])
    if path == "preloaded":
        rules = list((await db.scalars(select(VideoPricingRuleModel))).all())
        execute, get = db.execute, db.get
        db.execute, db.get = AsyncMock(wraps=execute), AsyncMock(wraps=get)
        try:
            result = await reconcile_video_job(db, job, usage=usage, existing_record=record, pricing_rules=rules, preloaded=True)
            db.execute.assert_not_awaited()
            db.get.assert_not_awaited()
            return result
        finally:
            db.execute, db.get = execute, get
    return await reconcile_video_job(db, job)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", "preloaded", "batch"])
@pytest.mark.parametrize(
    "model,provider,deleted_rule,linked_rule",
    [
        ("retired-model", "historical-provider", False, True),
        ("retired-model", "historical-provider", True, True),
        ("retired-model", "historical-provider", False, False),
        ("doubao-seedance-2.0", "yinghe", True, True),
        ("minimax-h3", "yinghe", True, True),
        ("minimax-h3-runninghub", "runninghub", True, True),
    ],
)
async def test_reconcile_preserves_historical_snapshot(billing_db, path, model, provider, deleted_rule, linked_rule):
    db = billing_db
    job, usage, rule, record = await _seed_billing_snapshot(db, model=model, provider=provider, deleted_rule=deleted_rule)
    if not linked_rule:
        record.pricing_rule_id = None
    if deleted_rule:
        # Even an available replacement must not rewrite a retired rule's snapshot.
        db.add(
            VideoPricingRuleModel(
                id="replacement-rule",
                model=model,
                provider=rule.provider,
                resolution="720p",
                usage_type="output_seconds",
                unit_size=1,
                unit_price=99,
                currency="CNY",
                effective_at=rule.effective_at,
            )
        )
    await db.commit()
    await db.refresh(record)
    before = [_row_snapshot(row) for row in (job, usage, rule, record)]
    result = await _reconcile_snapshot(db, job, usage, record, path)
    if path == "batch":
        assert result["processed"] == result["priced"] == result["failed"] == 1
        assert result["unpriced"] == result["excluded"] == 0
    else:
        assert result is record
    assert not db.is_modified(record)
    await db.commit()
    for row, snapshot in zip((job, usage, rule, record), before):
        await db.refresh(row)
        assert _row_snapshot(row) == snapshot
    assert list((await db.scalars(select(VideoBillingRecordModel))).all()) == [record]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", "preloaded", "batch"])
@pytest.mark.parametrize("model,deleted_rule", [("retired-model", False), ("retired-model", True), ("wan3.0-video", True)])
async def test_reconcile_without_snapshot_remains_unpriced(billing_db, path, model, deleted_rule):
    db = billing_db
    job, usage, _, record = await _seed_billing_snapshot(db, model=model, deleted_rule=deleted_rule, with_record=False)
    await _reconcile_snapshot(db, job, usage, record, path)
    await db.commit()
    record = (await db.scalars(select(VideoBillingRecordModel))).one()
    assert record.billing_status == "unpriced"
    assert record.amount == record.unit_price == 0
    assert record.pricing_rule_id is None
    assert record.currency == "CNY"
    assert record.raw_usage == usage.raw_usage
    assert record.usage_quantity == (8 if model == "wan3.0-video" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["single", "preloaded", "batch"])
@pytest.mark.parametrize(
    "model,provider,billing_status,quantity,unit_price,amount,unit",
    [
        ("doubao-seedance-2.0", "yinghe", "priced", 200_000, "1.66", "0.332", "Token"),
        ("wan3.0-video", "yinghe", "priced", 8, "2", "16", "秒"),
        ("minimax-h3", "yinghe", "priced", 8, "2", "16", "秒"),
        ("minimax-h3", "yinghe-h3", "priced", 8, "2", "16", "秒"),
        ("workflow-model", "runninghub", "excluded", 16, "0", "0", "RH币"),
        ("minimax-h3-runninghub", "", "excluded", 16, "0", "0", "RH币"),
    ],
)
async def test_reconcile_updates_supported_snapshot(billing_db, path, model, provider, billing_status, quantity, unit_price, amount, unit):
    db = billing_db
    job, usage, rule, record = await _seed_billing_snapshot(db, model=model, provider=provider)
    if model == "doubao-seedance-2.0":
        rule.usage_type = "completion_tokens"
        rule.unit_size = 1_000_000
    await db.commit()
    await _reconcile_snapshot(db, job, usage, record, path)
    await db.commit()
    await db.refresh(record)
    assert record.billing_status == billing_status
    assert record.usage_quantity == quantity
    assert record.unit_price == Decimal(unit_price)
    assert record.amount == Decimal(amount)
    assert record.usage_unit == unit
    assert record.pricing_rule_id == (rule.id if billing_status == "priced" else None)
    assert record.currency == ("EUR" if billing_status == "priced" else "CNY")
    assert record.raw_usage == usage.raw_usage
    assert record.generation_status == "succeeded"
    assert record.is_failed is False
    assert record.resolution == "720p"
    assert record.completed_at == job.finished_at
    assert list((await db.scalars(select(VideoBillingRecordModel))).all()) == [record]


@pytest.mark.asyncio
async def test_batch_snapshot_protection_uses_only_bulk_queries(billing_db, monkeypatch):
    db = billing_db
    retired = await _seed_billing_snapshot(db, suffix="retired")
    deleted = await _seed_billing_snapshot(db, model="wan3.0-video", provider="yinghe", deleted_rule=True, suffix="deleted")
    active = await _seed_billing_snapshot(db, model="minimax-h3", provider="yinghe", suffix="active")
    snapshots = [_row_snapshot(rows[3]) for rows in (retired, deleted)]
    execute, get = AsyncMock(wraps=db.execute), AsyncMock(wraps=db.get)
    monkeypatch.setattr(db, "execute", execute)
    monkeypatch.setattr(db, "get", get)
    result = await reconcile_video_billing(db)
    assert execute.await_count == 4  # jobs, usages, records, all rules (including deleted)
    get.assert_not_awaited()
    assert result["processed"] == result["priced"] == 3
    assert result["failed"] == 2
    assert result["unpriced"] == 0
    await db.commit()
    for rows, snapshot in zip((retired, deleted), snapshots):
        await db.refresh(rows[3])
        assert _row_snapshot(rows[3]) == snapshot
    await db.refresh(active[3])
    assert active[3].amount == Decimal("16")
