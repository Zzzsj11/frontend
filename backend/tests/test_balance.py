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
