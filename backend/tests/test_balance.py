from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app import balance

CURRENT_KEY = "yh-testkey1234567890"

FAKE_SETTINGS = SimpleNamespace(
    business_api_key="secret",
    business_user_id="123",
    business_balance_url="https://balance.test",
    business_tokens_list_url="https://tokens.test",
    business_balance_timeout=10,
    business_balance_cache_seconds=30,
    video_api_key="",
    image_api_key="",
)

KEY_ITEM = {"apiKey": CURRENT_KEY, "name": "gpt-image-dev", "quotaAmt": "1000.0000", "usedAmt": "751.30744"}


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class FakeClient:
    """按 URL 分支返回余额或 key 列表；tokens_url 为 None 时 key 查询抛 HTTP 错误。"""

    def __init__(self, calls, tokens_body=None, *args, **kwargs):
        self._calls = calls
        self._tokens_body = tokens_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, **kwargs):
        self._calls.append((url, kwargs["json"]))
        if "tokens" in url:
            if self._tokens_body is None:
                raise httpx.ConnectError("tokens endpoint down")
            return FakeResponse(self._tokens_body)
        return FakeResponse({"code": 200, "data": {"userId": 123, "balance": "287.391936"}})


def make_client(calls, tokens_body=None):
    def factory(*args, **kwargs):
        return FakeClient(calls, tokens_body, *args, **kwargs)

    return factory


@pytest.fixture(autouse=True)
def reset_balance_cache(monkeypatch):
    monkeypatch.setattr(balance, "_cache", None)
    monkeypatch.setattr(balance, "_cache_expires_at", 0.0)


def test_balance_signature_matches_business_protocol() -> None:
    assert balance.build_balance_sign("123", 1700000000, "secret") == "859668A4884CD3348D13D2B982ECB404"


def test_business_sign_matches_document_example() -> None:
    """官方文档 2.3 节示例：pageNum=1&pageSize=20&timestamp=1785744000&userId=1001&key=test-secret。"""
    params = {"userId": "1001", "timestamp": "1785744000", "pageNum": "1", "pageSize": "20"}
    assert balance.build_business_sign(params, "test-secret") == "7D5B7B168CC74B17233D405C071500E4"


def test_business_sign_ignores_empty_values() -> None:
    params = {"userId": "1001", "timestamp": "1785744000", "pageNum": "1", "pageSize": "20", "name": "", "status": None}
    assert balance.build_business_sign(params, "test-secret") == "7D5B7B168CC74B17233D405C071500E4"


def test_mask_api_key_shows_first_eight_chars() -> None:
    assert balance.mask_api_key(CURRENT_KEY) == "yh-testk***"
    assert balance.mask_api_key("short") == "short"


@pytest.mark.asyncio
async def test_balance_query_formats_and_caches_response(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(balance, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(FAKE_SETTINGS, "video_api_key", "yh-otherkey-not-match")
    monkeypatch.setattr(balance.httpx, "AsyncClient", make_client(calls, {"code": 200, "data": {"list": []}}))

    first = await balance.query_business_balance()
    second = await balance.query_business_balance()
    assert first["available"] is True
    assert first["balanceDisplay"] == "287.39"
    assert first["key"] is None
    assert second == first
    # 首次查询发余额 + key 列表两个请求，第二次命中缓存
    assert len(calls) == 2
    assert calls[0][1]["userId"] == 123


@pytest.mark.asyncio
async def test_key_quota_matched_and_remaining_computed(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(balance, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(FAKE_SETTINGS, "video_api_key", CURRENT_KEY)
    tokens_body = {"code": 200, "data": {"list": [{"apiKey": "yh-other999999", "quotaAmt": None, "usedAmt": 0}, KEY_ITEM]}}
    monkeypatch.setattr(balance.httpx, "AsyncClient", make_client(calls, tokens_body))

    result = await balance.query_business_balance()
    key = result["key"]
    assert key["keyMasked"] == "yh-testk***"
    assert key["keyName"] == "gpt-image-dev"
    assert key["quotaAmt"] == 1000.0
    assert key["usedAmt"] == 751.30744
    assert key["remaining"] == pytest.approx(248.69256)
    assert key["remainingDisplay"] == "248.69"


@pytest.mark.asyncio
async def test_key_quota_unlimited_when_quota_is_null(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(balance, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(FAKE_SETTINGS, "image_api_key", CURRENT_KEY)
    tokens_body = {"code": 200, "data": {"list": [{"apiKey": CURRENT_KEY, "name": None, "quotaAmt": None, "usedAmt": 12.5}]}}
    monkeypatch.setattr(balance.httpx, "AsyncClient", make_client(calls, tokens_body))

    result = await balance.query_business_balance()
    key = result["key"]
    assert key["remaining"] is None
    assert key["remainingDisplay"] == "不限额"
    assert key["keyName"] is None


@pytest.mark.asyncio
async def test_key_quota_failure_does_not_break_total_balance(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(balance, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(FAKE_SETTINGS, "video_api_key", CURRENT_KEY)
    monkeypatch.setattr(balance.httpx, "AsyncClient", make_client(calls, None))

    result = await balance.query_business_balance()
    assert result["available"] is True
    assert result["balanceDisplay"] == "287.39"
    assert result["key"] is None


@pytest.mark.asyncio
async def test_key_quota_skipped_when_provider_key_missing(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(balance, "settings", FAKE_SETTINGS)
    monkeypatch.setattr(balance, "SHARED_PROVIDER_KEY", "")
    monkeypatch.setattr(balance.httpx, "AsyncClient", make_client(calls, {"code": 200, "data": {"list": [KEY_ITEM]}}))

    result = await balance.query_business_balance()
    assert result["key"] is None
    # 未配置当前 key 时不发 tokens/list 请求
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_current_provider_key_fallback_order(monkeypatch) -> None:
    monkeypatch.setattr(balance, "settings", SimpleNamespace(video_api_key="", image_api_key="img-key", business_user_id="1"))
    monkeypatch.setattr(balance, "SHARED_PROVIDER_KEY", "shared-key")
    assert balance._current_provider_key() == "img-key"
    monkeypatch.setattr(balance.settings, "video_api_key", "video-key")
    assert balance._current_provider_key() == "video-key"
    monkeypatch.setattr(balance.settings, "video_api_key", "")
    monkeypatch.setattr(balance.settings, "image_api_key", "")
    assert balance._current_provider_key() == "shared-key"


@pytest.mark.asyncio
async def test_balance_query_degrades_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(balance, "settings", SimpleNamespace(business_api_key="", business_user_id=""))
    result = await balance.query_business_balance()
    assert result["available"] is False
    assert result["balanceDisplay"] == "--"
    assert result["key"] is None


async def test_video_batch_cost_estimate_and_insufficient_key_balance(monkeypatch) -> None:
    async def enough(force=False):
        return {"available": True, "key": {"remaining": 20}}

    async def enough_providers(force=False):
        return {"providers": {"yinghe": await enough(force), "ppio": balance.unavailable_balance()}}

    monkeypatch.setattr(balance, "query_provider_balances", enough_providers)
    items = [SimpleNamespace(duration=10, model="doubao-seedance-2.0"), SimpleNamespace(duration=10, model="minimax-h3-runninghub")]
    assert (await balance.ensure_video_batch_balance(items))["estimatedCost"] == 8.3

    async def insufficient(force=False):
        return {"available": True, "key": {"remaining": 8.29}}

    async def insufficient_providers(force=False):
        return {"providers": {"yinghe": await insufficient(force), "ppio": balance.unavailable_balance()}}

    monkeypatch.setattr(balance, "query_provider_balances", insufficient_providers)
    with pytest.raises(ValueError, match="英和子账号 Key 余额不足，请先完成充值或提升余额上限后再试"):
        await balance.ensure_video_batch_balance(items)


@pytest.mark.asyncio
async def test_ppio_balance_and_channel_cost_precheck(monkeypatch) -> None:
    class PpioClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            assert headers == {
                "Authorization": "Bearer ppio-test-key",
                "Content-Type": "application/json",
            }
            if url == "https://api.ppio.com/v3/user":
                return FakeResponse({"credit_balance": 25000000})
            assert url == "https://api.ppio.com/openapi/v1/billing/balance/detail"
            return FakeResponse(
                {
                    "availableBalance": "1000000",
                    "cashBalance": "800000",
                    "creditLimit": "200000",
                    "pendingCharges": "0",
                    "outstandingInvoices": "0",
                }
            )

    ppio_settings = SimpleNamespace(
        ppio_api_key="ppio-test-key",
        ppio_balance_url="https://api.ppio.com/openapi/v1/billing/balance/detail",
        ppio_model_balance_url="https://api.ppio.com/v3/user",
        ppio_balance_timeout=10,
    )
    monkeypatch.setattr(balance, "settings", ppio_settings)
    monkeypatch.setattr(balance.httpx, "AsyncClient", lambda **_kwargs: PpioClient())
    result = await balance.query_ppio_balance()
    assert result["rawBalance"] == "1000000"
    assert result["balance"] == "125"
    assert result["balanceDisplay"] == "125.00"
    assert result["unitScale"] == 10000
    assert result["details"]["cashBalance"] == 80
    assert result["details"]["creditLimit"] == 20
    assert result["details"]["accountAvailableBalance"] == 100
    assert result["details"]["modelCreditBalance"] == 25
    assert result["rawModelCreditBalance"] == "25000000"
    assert result["rawDetails"]["cashBalance"] == "800000"

    async def provider_balances(force=False):
        return {"providers": {"yinghe": balance.unavailable_balance(), "ppio": result}}

    monkeypatch.setattr(balance, "query_provider_balances", provider_balances)
    estimate = await balance.ensure_video_batch_balance([SimpleNamespace(duration=10, model="doubao-seedance-2.0-ppio"), SimpleNamespace(duration=10, model="minimax-h3-ppio")])
    assert estimate["estimatedCost"] == 12.25
    assert estimate["providerEstimates"] == {"ppio": 12.25}

    async def insufficient_provider_balances(force=False):
        return {"providers": {"yinghe": balance.unavailable_balance(), "ppio": {**result, "balance": "10", "balanceDisplay": "10.00"}}}

    monkeypatch.setattr(balance, "query_provider_balances", insufficient_provider_balances)
    with pytest.raises(ValueError, match="PPIO 余额不足，请先完成充值或提升余额上限后再试"):
        await balance.ensure_video_batch_balance([SimpleNamespace(duration=10, model="doubao-seedance-2.0-ppio"), SimpleNamespace(duration=10, model="minimax-h3-ppio")])


@pytest.mark.asyncio
async def test_runninghub_batch_is_excluded_from_cost_and_balance_check(monkeypatch):
    async def should_not_query(*, force=False):
        raise AssertionError("RunningHub 暂不计费时不应查询英和或 PPIO 余额")

    monkeypatch.setattr(balance, "query_provider_balances", should_not_query)
    estimate = await balance.ensure_video_batch_balance([SimpleNamespace(duration=10, model="minimax-h3-runninghub")])
    assert estimate == {"estimatedCost": 0, "availableBalance": -1.0, "providerEstimates": {}}
