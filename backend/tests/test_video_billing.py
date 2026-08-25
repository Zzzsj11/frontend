from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.database import session_factory
from app.models import GenerationJobModel, TokenUsageModel, VideoPricingRuleModel


async def _seed_billing_fixtures() -> None:
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
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
        ):
            db.add(rule)
        jobs = (
            GenerationJobModel(
                id="billing-sd-ok",
                user_id="user-admin",
                kind="video",
                status="succeeded",
                request={"model": "doubao-seedance-2.0", "resolution": "720p"},
                provider="yinhe",
                finished_at=now,
            ),
            GenerationJobModel(
                id="billing-h3-failed",
                user_id="user-admin",
                kind="video",
                status="failed",
                request={"model": "minimax-h3", "resolution": "720p"},
                provider="yinghe-h3",
                error="供应商失败",
                finished_at=now,
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
        )
        db.add_all(jobs)
        db.add_all(
            (
                TokenUsageModel(
                    id="billing-usage-sd",
                    user_id="user-admin",
                    generation_job_id="billing-sd-ok",
                    operation="generation_video",
                    provider="yinhe",
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
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_video_billing_reconciles_success_failed_and_excluded(client):
    await _seed_billing_fixtures()
    reconciled = client.post("/api/admin/video-billing/reconcile")
    assert reconciled.status_code == 200
    assert reconciled.json()["processed"] >= 3

    response = client.get("/api/admin/video-billing", params={"q": "billing-", "limit": 20})
    assert response.status_code == 200
    items = {item["generationJobId"]: item for item in response.json()["items"]}
    assert items["billing-sd-ok"]["amount"] == pytest.approx(4.6)
    assert items["billing-h3-failed"]["isFailed"] is True
    assert items["billing-h3-failed"]["billingStatus"] == "priced"
    assert items["billing-h3-failed"]["amount"] == pytest.approx(5.1)
    assert items["billing-rh-failed"]["billingStatus"] == "excluded"
    assert items["billing-rh-failed"]["amount"] == 0

    failed = client.get("/api/admin/video-billing", params={"status": "failed", "q": "billing-"}).json()
    assert {item["generationJobId"] for item in failed["items"]} == {"billing-h3-failed", "billing-rh-failed"}
    assert failed["summary"]["failedRecords"] == 2

    # 重复核算必须更新同一工单账单，不得重复入账。
    assert client.post("/api/admin/video-billing/reconcile").status_code == 200
    assert client.get("/api/admin/video-billing", params={"q": "billing-"}).json()["total"] == 3


def test_video_billing_requires_admin(client):
    created = client.post("/api/admin/users", json={"username": "billing-normal-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "billing-normal-user", "password": "secure-pass-123"}).json()
    headers = {"Authorization": f"Bearer {login['accessToken']}"}
    assert client.get("/api/admin/video-billing", headers=headers).status_code == 403
    assert client.post("/api/admin/video-billing/reconcile", headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")
