import importlib
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
async def test_toapis_conversion_uses_exact_credits_not_dollars(service):
    from control.channel_balances import view

    row = SimpleNamespace(
        id="toapis",
        channel="toapis",
        name="Toapis",
        currency="USD",
        usd_cny=Decimal("6.9"),
        points_per_unit=None,
        points_currency="CNY",
        snapshot={"balance": "5", "remain_credits": "1000"},
        queried_at=None,
        attempted_at=None,
        error=None,
    )
    result = view(row)
    assert result["currency"] == "POINTS"
    assert result["balance"] == "1000"
    assert Decimal(result["cny_balance"]) == Decimal("35")
    row.snapshot = {"balance": "5"}
    assert view(row)["cny_balance"] is None  # 不能把旧美元快照当作积分。


@pytest.mark.parametrize("channel,host", [("yinghe", "api-aigc.fzyinghe.com"), ("yseeai", "api-aigc.yseeai.com")])
@pytest.mark.asyncio
async def test_business_grants_are_incremental_signed_and_verified(channel, host):
    from gateway.yinghe_business import YingheBusiness, sign

    calls = []
    granted = {"old-model"}

    def transport(req):
        body = json.loads(req.content)
        signature = body.pop("sign")
        assert signature == sign(body, "business-secret")
        assert req.url.host == host
        assert req.headers["X-Agent-Name"] == "code-agent"
        assert body["userId"] == 2087458189668790273  # 保留 64 位 ID 精度
        assert body["apiKey"] == "target-key-secret"
        calls.append(req.url.path)
        if req.url.path.endswith("addModel"):
            granted.add(body["model"])
            return httpx.Response(200, json={"code": 200})
        return httpx.Response(200, json={"code": 200, "data": {"models": sorted(granted)}})

    api = YingheBusiness(
        channel,
        values={
            channel.upper() + "_BUSINESS_USER_ID": "2087458189668790273",
            channel.upper() + "_BUSINESS_API_KEY": "business-secret",
            channel.upper() + "_API_KEY": "target-key-secret",
        },
        transport=httpx.MockTransport(transport),
        run_id="test-balances",
    )
    result = await api.grant(["old-model", "new-model", "new-model"])
    assert result["missing"] == [] and result["added"] == ["new-model"]
    assert calls.count("/business/tokens/addModel") == 1
    assert "target-key-secret" not in json.dumps(result)
    assert "business-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_grant_timeout_reconciles_without_resubmit_and_stops():
    from gateway.yinghe_business import YingheBusiness

    calls = []

    def transport(req):
        calls.append(req.url.path)
        if req.url.path.endswith("addModel"):
            raise httpx.ReadTimeout("secret-in-exception", request=req)
        return httpx.Response(200, json={"code": 200, "data": {"models": []}})

    api = YingheBusiness(
        "yseeai",
        values={"YSEEAI_BUSINESS_USER_ID": "1", "YSEEAI_BUSINESS_API_KEY": "secret", "YSEEAI_API_KEY": "target"},
        transport=httpx.MockTransport(transport),
    )
    result = await api.grant(["first", "second"])
    assert result["missing"] == ["first", "second"]
    assert calls.count("/business/tokens/addModel") == 1
    assert calls.count("/business/tokens/authorizedModels") == 2
    assert "secret-in-exception" not in json.dumps(result)


@pytest.mark.asyncio
async def test_balance_paginates_target_and_keeps_merchant_on_quota_failure():
    from gateway.yinghe_business import YingheBusiness

    def transport(req):
        body = json.loads(req.content)
        if req.url.path.endswith("balance"):
            data = {"balance": "46.646693"}
        elif body["pageNum"] == 1:
            data = {"list": [{"apiKey": "other"}] * 100}
        else:
            data = {"list": [{"apiKey": "target", "quotaAmt": "30", "usedAmt": "5.123456"}]}
        return httpx.Response(200, json={"code": 200, "data": data})

    api = YingheBusiness(
        "yseeai",
        values={"YSEEAI_BUSINESS_USER_ID": "1", "YSEEAI_BUSINESS_API_KEY": "secret", "YSEEAI_API_KEY": "target"},
        transport=httpx.MockTransport(transport),
    )
    result = await api.balance()
    assert result["balance"] == "46.646693"
    assert result["quota"]["remaining"] == "24.876544"
    api.target = "missing"
    result = await api.balance()
    assert result["balance"] == "46.646693" and result["quota"] is None and result["quota_error"]


def test_no_cross_site_fallback_or_custom_destination():
    from gateway.yinghe_business import BusinessError, YingheBusiness

    with pytest.raises(BusinessError):
        YingheBusiness("yseeai", values={"BUSINESS_USER_ID": "1", "BUSINESS_API_KEY": "domestic", "YSEEAI_API_KEY": "overseas"})
    with pytest.raises(BusinessError):
        YingheBusiness("yseeai", values={"YSEEAI_BUSINESS_BASE_URL": "https://api-aigc.fzyinghe.com"})


@pytest.mark.asyncio
async def test_admin_currency_conversion_permissions_and_audits(service):
    api, ctl, _, _ = service
    dbmod = importlib.import_module("control.db")
    async with dbmod.Session.begin() as db:
        row = await db.get(dbmod.ChannelAccount, "yseeai")
        row.snapshot = {"balance": "46.646693", "source": "provider"}
        row.queried_at = dbmod.now()
    response = await ctl.get("/admin/channel-balances")
    overseas = next(x for x in response.json() if x["id"] == "yseeai")
    assert Decimal(overseas["cny_balance"]) == Decimal("321.8621817")
    assert overseas["currency"] == "USD" and not overseas["stale"]
    assert "key_env" not in response.text and "fake-test-key" not in response.text
    assert (await ctl.get("/admin/channel-balances", headers={"Authorization": api.headers["Authorization"]})).status_code == 401
    bad = {"currency": "CNY", "usd_cny": "6.9"}
    assert (await ctl.patch("/admin/channel-balances/yseeai", json=bad)).status_code == 422
    assert (await ctl.patch("/admin/channel-balances/runninghub", json={"currency": "POINTS", "points_per_unit": "0"})).status_code == 422
    assert (await ctl.patch("/admin/channel-balances/runninghub", json={"currency": "POINTS", "usd_cny": "NaN"})).status_code == 422
    result = await ctl.post("/admin/channel-balances/runninghub/manual", json={"balance": "1250", "note": "供应商控制台核对"})
    assert result.status_code == 200 and result.json()["cny_balance"] is None
    policy = {"currency": "POINTS", "points_per_unit": "100", "points_currency": "USD", "usd_cny": "6.9"}
    result = await ctl.patch("/admin/channel-balances/runninghub", json=policy)
    assert Decimal(result.json()["cny_balance"]) == Decimal("86.25")
    policy["points_currency"] = "CNY"
    result = await ctl.patch("/admin/channel-balances/runninghub", json=policy)
    assert Decimal(result.json()["cny_balance"]) == Decimal("12.5")
    policy["currency"] = "USD"
    result = await ctl.patch("/admin/channel-balances/runninghub", json=policy)
    assert result.json()["balance"] is None  # 不把旧积分金额直接解释成美元
    assert (await ctl.post("/admin/channel-balances/yseeai/manual", json={"balance": "1", "note": "override"})).status_code == 409
    audits = (await ctl.get("/admin/audits")).json()
    assert any(x["action"] == "channel.policy" for x in audits)
    assert any(x["action"] == "channel.manual_balance" for x in audits)


@pytest.mark.asyncio
async def test_collector_retains_old_snapshot_and_coalesces_refresh(service, monkeypatch):
    _, ctl, _, _ = service
    worker = importlib.import_module("gateway.channel_balances")
    dbmod = importlib.import_module("gateway.db")
    async with dbmod.Session.begin() as db:
        for row in (await db.scalars(worker.select(dbmod.ChannelAccount))).all():
            row.next_check_at = dbmod.now() + timedelta(days=1)
        row = await db.get(dbmod.ChannelAccount, "yseeai")
        row.next_check_at = dbmod.now() - timedelta(seconds=1)

    async def good(row):
        return {"balance": "10.123456", "key_masked": "yh-…abcd"}

    monkeypatch.setattr(worker, "fetch", good)
    assert await worker.sync_one()
    assert not await worker.sync_one()
    assert (await ctl.post("/admin/channel-balances/yseeai/refresh")).status_code == 202
    assert not await worker.sync_one()  # 60 秒内不能强刷打穿上游限流
    async with dbmod.Session.begin() as db:
        row = await db.get(dbmod.ChannelAccount, "yseeai")
        row.next_check_at = dbmod.now() - timedelta(seconds=1)

    async def bad(row):
        raise worker.BusinessError("查询失败")

    monkeypatch.setattr(worker, "fetch", bad)
    assert await worker.sync_one()
    row = next(x for x in (await ctl.get("/admin/channel-balances")).json() if x["id"] == "yseeai")
    assert row["balance"] == "10.123456" and row["stale"] and row["error"] == "查询失败"
