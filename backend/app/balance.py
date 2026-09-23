from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from . import redis_store
from .config import SHARED_PROVIDER_KEY, settings
from .video_estimation import video_estimate_policy

_cache: dict[str, Any] | None = None
_cache_expires_at = 0.0
_cache_cached_at = 0.0
_key_quota_cache: dict[str, Any] | None = None
_key_quota_cached_at = 0.0
_business_cooldown_until = 0.0
_local_business_request_times: deque[float] = deque()
_local_business_rate_lock = asyncio.Lock()
_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


class BusinessApiRateLimitedError(ValueError):
    def __init__(self, retry_after: int, source: str) -> None:
        self.retry_after = max(1, retry_after)
        self.source = source
        reason = {"supplier": "供应商返回 429", "cooldown": "供应商 429 冷却中"}.get(source, "应用已主动限流")
        super().__init__(f"{reason}，请在 {self.retry_after} 秒后重试")


def build_balance_sign(user_id: str, timestamp: int, api_key: str) -> str:
    raw = f"timestamp={timestamp}&userId={user_id}&key={api_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()  # noqa: S324 - upstream protocol requires MD5


def build_business_sign(params: dict[str, str], api_key: str) -> str:
    """业务开放接口通用签名：字段名 ASCII 升序、忽略空值，末尾拼 &key=，MD5 大写。"""
    items = sorted((key, value) for key, value in params.items() if value not in (None, ""))
    raw = "&".join(f"{key}={value}" for key, value in items) + f"&key={api_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()  # noqa: S324 - upstream protocol requires MD5


def mask_api_key(key: str, visible: int = 8) -> str:
    return f"{key[:visible]}***" if len(key) > visible else key


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unavailable_balance(message: str = "余额暂不可用") -> dict[str, Any]:
    return {
        "available": False,
        "balance": None,
        "balanceDisplay": "--",
        "currency": "credits",
        "updatedAt": datetime.now(UTC).isoformat(),
        "message": message,
        "key": None,
    }


def _current_provider_key() -> str:
    """生成链路实际使用的供应商 key：与 providers.py 口径一致（VIDEO/IMAGE_API_KEY 优先，回退 AIGC_TOKEN）。"""
    return settings.video_api_key or settings.image_api_key or SHARED_PROVIDER_KEY


def _cache_is_usable(cache: dict[str, Any] | None, expires_at: float, cached_at: float, *, force: bool, now: float) -> bool:
    if cache is None:
        return False
    if not force:
        return now < expires_at
    return now - cached_at < getattr(settings, "balance_force_coalesce_seconds", 10)


def _retry_after_seconds(response: httpx.Response | None) -> int:
    minimum = getattr(settings, "business_rate_limit_cooldown_seconds", 60)
    if response is None:
        return minimum
    value = response.headers.get("Retry-After", "").strip()
    if value.isdigit():
        return max(minimum, int(value))
    if value:
        try:
            delta = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            return max(minimum, int(delta + 0.999))
        except (TypeError, ValueError, OverflowError):
            pass
    return minimum


async def _activate_business_cooldown(seconds: int) -> None:
    global _business_cooldown_until
    _business_cooldown_until = max(_business_cooldown_until, time.monotonic() + seconds)
    await redis_store.set_provider_cooldown("yinghe-business", seconds)


async def _business_cooldown_remaining() -> int:
    local = max(0, int(_business_cooldown_until - time.monotonic() + 0.999))
    shared = await redis_store.provider_cooldown_remaining("yinghe-business")
    return max(local, shared or 0)


async def _acquire_business_api_permit() -> None:
    """Count every English business API request against one shared budget."""
    cooldown_remaining = _business_cooldown_until - time.monotonic()
    if cooldown_remaining > 0:
        raise BusinessApiRateLimitedError(int(cooldown_remaining + 0.999), "cooldown")
    limit = getattr(settings, "business_api_rate_limit_per_minute", 45)
    shared = await redis_store.acquire_provider_request_permit("yinghe-business", limit, 60)
    if shared is not None:
        acquired, retry_after, source = shared
        if not acquired:
            raise BusinessApiRateLimitedError(retry_after, source)
        return

    # Redis outages must not amplify traffic. Keep a rolling single-process
    # fallback while allowing balance checks to recover without Redis.
    async with _local_business_rate_lock:
        now = time.monotonic()
        while _local_business_request_times and _local_business_request_times[0] <= now - 60:
            _local_business_request_times.popleft()
        if len(_local_business_request_times) >= limit:
            retry_after = max(1, int(60 - (now - _local_business_request_times[0]) + 0.999))
            raise BusinessApiRateLimitedError(retry_after, "budget")
        _local_business_request_times.append(now)


def _apply_key_quota_failure(result: dict[str, Any], exc: Exception) -> None:
    error_message = str(exc) or "Key 额度服务请求失败"
    logger.warning("英和 Key 额度查询失败：%s", error_message)
    stale_age = time.monotonic() - _key_quota_cached_at
    stale_limit = settings.business_key_quota_stale_seconds
    if _key_quota_cache is not None and stale_age <= stale_limit:
        result["key"] = {
            **_key_quota_cache,
            "stale": True,
            "warning": f"实时额度查询失败，当前显示 {round(stale_age)} 秒前的缓存",
        }
    else:
        result["key"] = None
    result["keyError"] = error_message


async def _query_current_key_quota(client: httpx.AsyncClient) -> dict[str, Any] | None:
    """查询当前 AIGC key 的月度额度使用情况；未配置或未命中返回 None，异常向上抛出由调用方降级。"""
    current_key = _current_provider_key()
    if not current_key:
        return None
    user_id = settings.business_user_id
    page_size = 100
    for page_num in range(1, 21):
        timestamp = int(time.time())
        sign_params = {
            "userId": user_id,
            "timestamp": str(timestamp),
            "pageNum": str(page_num),
            "pageSize": str(page_size),
        }
        payload = {
            "userId": int(user_id) if user_id.isdigit() else user_id,
            "timestamp": timestamp,
            "pageNum": page_num,
            "pageSize": page_size,
            "sign": build_business_sign(sign_params, settings.business_api_key),
        }
        await _acquire_business_api_permit()
        response = await client.post(
            settings.business_tokens_list_url,
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200:
            raise ValueError(body.get("msg") or "Key 额度服务返回错误")
        data = body.get("data") or {}
        items = data.get("list") or []
        for item in items:
            if item.get("apiKey") != current_key:
                continue
            quota = _to_float(item.get("quotaAmt"))
            used = _to_float(item.get("usedAmt")) or 0.0
            remaining = quota - used if quota is not None else None
            return {
                "keyMasked": mask_api_key(current_key),
                "keyName": item.get("name") or None,
                "quotaAmt": quota,
                "usedAmt": used,
                "remaining": remaining,
                "remainingDisplay": f"{remaining:.2f}" if remaining is not None else "不限额",
                "updatedAt": datetime.now(UTC).isoformat(),
                "stale": False,
                "warning": None,
            }
        total = _to_float(data.get("total"))
        if len(items) < page_size or (total is not None and page_num * page_size >= total):
            break
    raise ValueError("当前生成 Key 未在额度列表中找到")


async def query_business_balance(*, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_expires_at, _cache_cached_at, _key_quota_cache, _key_quota_cached_at
    if not settings.business_api_key or not settings.business_user_id:
        return unavailable_balance("未配置余额查询凭据")
    cooldown_remaining = await _business_cooldown_remaining()
    if cooldown_remaining > 0:
        return unavailable_balance(f"供应商余额查询正在限流冷却，请在 {cooldown_remaining} 秒后重试")
    now = time.monotonic()
    if _cache_is_usable(_cache, _cache_expires_at, _cache_cached_at, force=force, now=now):
        return dict(_cache)
    async with _lock:
        now = time.monotonic()
        if _cache_is_usable(_cache, _cache_expires_at, _cache_cached_at, force=force, now=now):
            return dict(_cache)
        timestamp = int(time.time())
        user_id = settings.business_user_id
        payload = {"userId": int(user_id) if user_id.isdigit() else user_id, "timestamp": timestamp, "sign": build_balance_sign(user_id, timestamp, settings.business_api_key)}
        try:
            async with httpx.AsyncClient(timeout=settings.business_balance_timeout) as client:
                await _acquire_business_api_permit()
                response = await client.post(settings.business_balance_url, headers={"Content-Type": "application/json"}, json=payload)
                response.raise_for_status()
                body = response.json()
                if body.get("code") != 200:
                    raise ValueError(body.get("msg") or "余额服务返回错误")
                data = body.get("data") or {}
                raw_balance = data.get("balance")
                result = {
                    "available": True,
                    "userId": str(data.get("userId") or user_id),
                    "balance": str(raw_balance),
                    "balanceDisplay": f"{float(raw_balance):.2f}",
                    "currency": "credits",
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "message": None,
                    "key": None,
                }
                quota_age = time.monotonic() - _key_quota_cached_at
                quota_cache_seconds = getattr(settings, "business_key_quota_cache_seconds", 300)
                if _key_quota_cache is not None and quota_age < quota_cache_seconds:
                    result["key"] = {**_key_quota_cache, "stale": False, "warning": None}
                    result["keyError"] = None
                else:
                    try:
                        key_quota = await _query_current_key_quota(client)
                        result["key"] = key_quota
                        result["keyError"] = None
                        if key_quota is not None:
                            _key_quota_cache = dict(key_quota)
                            _key_quota_cached_at = time.monotonic()
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 429:
                            retry_after = _retry_after_seconds(exc.response)
                            await _activate_business_cooldown(retry_after)
                            quota_exc: Exception = BusinessApiRateLimitedError(retry_after, "supplier")
                        else:
                            quota_exc = exc
                        _apply_key_quota_failure(result, quota_exc)
                    except (httpx.HTTPError, ValueError, TypeError) as exc:
                        _apply_key_quota_failure(result, exc)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = _retry_after_seconds(exc.response)
                await _activate_business_cooldown(retry_after)
                result = unavailable_balance(str(BusinessApiRateLimitedError(retry_after, "supplier")))
            else:
                result = unavailable_balance(str(exc) or "余额服务请求失败")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            result = unavailable_balance(str(exc) or "余额服务请求失败")
        _cache = result
        _cache_cached_at = time.monotonic()
        _cache_expires_at = time.monotonic() + settings.business_balance_cache_seconds
        return dict(result)


async def query_provider_balances(*, force: bool = False, providers: set[str] | None = None) -> dict[str, Any]:
    requested = providers or {"yinghe"}
    yinghe = await query_business_balance(force=force) if "yinghe" in requested else unavailable_balance("本次未查询英和余额")
    return {"providers": {"yinghe": yinghe}, **yinghe}


def estimate_item_cost(item: Any) -> tuple[str, float]:
    model = str(item.model or "")
    policy = video_estimate_policy(model)
    return policy.provider, float(item.duration) * policy.unit_price_per_second


async def ensure_video_batch_balance(items: list[Any]) -> dict[str, Any]:
    """按实际渠道分别预检批量视频余额，避免用一个渠道的余额替另一个渠道兜底。"""
    estimates: dict[str, float] = {}
    for item in items:
        policy = video_estimate_policy(str(item.model or ""))
        if not policy.balance_check:
            continue
        provider, amount = estimate_item_cost(item)
        estimates[provider] = estimates.get(provider, 0) + amount
    if not estimates:
        return {"estimatedCost": 0, "availableBalance": -1.0, "providerEstimates": {}}
    balances = await query_provider_balances(force=True, providers=set(estimates))
    available_by_provider: dict[str, float] = {}
    for provider, estimated in estimates.items():
        balance = balances["providers"][provider]
        if provider == "yinghe" and balance.get("keyError"):
            raise ValueError(f"英和子账号 Key 余额查询失败（{balance['keyError']}），请稍后再试")
        raw_available = (balance.get("key") or {}).get("remaining")
        available = _to_float(raw_available) if balance.get("available") else None
        if available is None:
            reason = balance.get("keyError") or balance.get("message")
            detail = f"（{reason}）" if reason else ""
            raise ValueError(f"英和子账号 Key 余额查询失败{detail}，请稍后再试")
        if available + 1e-9 < estimated:
            raise ValueError("英和子账号 Key 余额不足，请先完成充值或提升余额上限后再试")
        available_by_provider[provider] = available
    estimated_total = round(sum(estimates.values()), 2)
    return {"estimatedCost": estimated_total, "availableBalance": min(available_by_provider.values(), default=-1.0), "providerEstimates": estimates}
