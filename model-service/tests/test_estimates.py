from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_estimate_never_generates_or_reserves_and_checks_permissions(service, monkeypatch):
    from gateway.db import Job, Ledger, Model, ModelRoute, Session

    api, ctl, _, _ = service
    async with Session() as db:
        initial_ledger = await db.scalar(select(func.count()).select_from(Ledger))
    async with Session.begin() as db:
        m = await db.get(Model, "gpt-5.6-sol")
        m.capabilities = {"catalog_selected": True, "unified_catalog": True}
        db.add(
            ModelRoute(
                id="quote-route",
                model_id=m.id,
                supplier="yseeai",
                channel="yseeai-llm",
                provider_model=m.id,
                protocol="chat",
                enabled=True,
                priority=1,
                concurrency=1,
                verification="passed",
                capabilities={},
                pricing={
                    "estimate_version": "test-v1",
                    "estimate_rules": [
                        {
                            "confirmed": True,
                            "conditions": {},
                            "rates": [
                                {"label": "input", "path": "input_tokens", "unit": "1000000", "cny": "10"},
                                {"label": "output", "path": "output_tokens", "unit": "1000000", "cny": "30"},
                            ],
                        }
                    ],
                },
            )
        )
    original = httpx.AsyncClient.send

    async def no_external(self, req, **kw):
        assert req.url.host in {"test", "control", "public", "admin"}
        return await original(self, req, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "send", no_external)
    body = {
        "model": "gpt-5.6-sol",
        "messages": [{"role": "user", "content": "hello"}],
        "estimate_only": True,
        "estimate_usage": {"input_tokens": 1000, "output_tokens": 2000},
    }
    r = await api.post("/v1/chat/completions", json=body)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["status"] == "estimated"
    assert Decimal(result["amount_cny"]) == Decimal("0.07")
    assert Decimal(result["points"]) == 7
    assert result["generated"] is False and result["charged"] is False
    assert (await api.post("/v1/pricing/estimate", json=body)).json() == result
    automatic = await api.post(
        "/v1/chat/completions",
        json={
            "model": body["model"],
            "messages": [{"role": "user", "content": "请简述春天"}],
            "max_tokens": 100,
            "estimate_only": True,
        },
    )
    assert automatic.status_code == 200, automatic.text
    assert automatic.json()["status"] == "estimated"
    assert Decimal(automatic.json()["estimated_usage"]["output_tokens"]) == 100
    assert automatic.json()["reference_range_cny"] is not None
    assert automatic.json()["estimation"]["sample_count"] == 0
    missing = await api.post("/v1/pricing/estimate", json={"model": body["model"]})
    assert missing.json()["status"] == "needs_usage" and missing.json()["amount_cny"] is None
    for value in [-1, "NaN", True]:
        assert (await api.post("/v1/pricing/estimate", json={**body, "estimate_usage": {"input_tokens": value}})).status_code == 422
    assert (await api.post("/v1/chat/completions", json={**body, "estimate_only": "true"})).status_code == 422
    config = {
        "policy": {"cost_multiplier": "2", "fixed_cny": "0.03", "use_history": False, "default_output_tokens": 80},
        "rules": [
            {
                "rates": [
                    {"label": "输入", "path": "input_tokens", "unit": 1000000, "cny": "10"},
                    {"label": "输出", "path": "output_tokens", "unit": 1000000, "cny": "30"},
                ]
            }
        ],
    }
    saved = await ctl.put("/admin/routes/quote-route/estimate-pricing", json=config)
    assert saved.status_code == 200, saved.text
    assert saved.json()["pricing"]["estimate_manual_override"] is True
    changed = (await api.post("/v1/pricing/estimate", json=body)).json()
    assert Decimal(changed["amount_cny"]) == Decimal("0.17")
    assert changed["rate_version"].startswith("manual-")
    config["rules"][0]["conditions"] = {"input_max": "not-a-number"}
    assert (await ctl.put("/admin/routes/quote-route/estimate-pricing", json=config)).status_code == 422
    async with Session() as db:
        assert await db.scalar(select(func.count()).select_from(Job)) == 0
        assert await db.scalar(select(func.count()).select_from(Ledger)) == initial_ledger


def test_quote_counts_text_not_media_payload_and_matches_task_prices():
    from gateway.estimates import matches
    from gateway.usage_estimation import output_usage, resolution, text_tokens

    assert text_tokens({"model": "test"}) is None
    assert text_tokens({"prompt": "你好"}) > text_tokens({"prompt": "hi"})
    assert text_tokens({"messages": [{"content": [{"type": "image", "source": {"data": "a" * 10000}}]}]}) is None
    assert resolution({"size": "2048x2048"}) == "2k"
    assert output_usage({"rawUsage": {"output_tokens": 6144}}) == 6144
    assert matches({"duration": "4s", "resolution": "720p"}, {"duration": 4, "resolution": "720p"}, {})
    assert not matches({"duration": "4s"}, {"duration": 8}, {})
    assert not matches({"input_image_count": 0}, {"images": ["https://example.com/image.png"]}, {})
