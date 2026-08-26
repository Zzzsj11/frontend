from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import SHARED_PROVIDER_KEY, settings

_cache: dict[str, Any] | None = None
_cache_expires_at = 0.0
_lock = asyncio.Lock()
SD20_ESTIMATE_PRICE_PER_SECOND = 0.83
H3_ESTIMATE_PRICE_PER_SECOND = 0.425
PPIO_SD20_ESTIMATE_PRICE_PER_SECOND = 0.8


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


async def _query_current_key_quota(client: httpx.AsyncClient) -> dict[str, Any] | None:
    """查询当前 AIGC key 的月度额度使用情况；未配置或未命中返回 None，异常向上抛出由调用方降级。"""
    current_key = _current_provider_key()
    if not current_key:
        return None
    timestamp = int(time.time())
    user_id = settings.business_user_id
    sign_params = {"userId": user_id, "timestamp": str(timestamp), "pageNum": "1", "pageSize": "100"}
    payload = {
        "userId": int(user_id) if user_id.isdigit() else user_id,
        "timestamp": timestamp,
        "pageNum": 1,
        "pageSize": 100,
        "sign": build_business_sign(sign_params, settings.business_api_key),
    }
    response = await client.post(settings.business_tokens_list_url, headers={"Content-Type": "application/json"}, json=payload)
    response.raise_for_status()
    body = response.json()
    if body.get("code") != 200:
        raise ValueError(body.get("msg") or "Key 额度服务返回错误")
    items = (body.get("data") or {}).get("list") or []
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
        }
    return None


async def query_business_balance(*, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_expires_at
    if not settings.business_api_key or not settings.business_user_id:
        return unavailable_balance("未配置余额查询凭据")
    now = time.monotonic()
    if not force and _cache and now < _cache_expires_at:
        return dict(_cache)
    async with _lock:
        now = time.monotonic()
        if not force and _cache and now < _cache_expires_at:
            return dict(_cache)
        timestamp = int(time.time())
        user_id = settings.business_user_id
        payload = {"userId": int(user_id) if user_id.isdigit() else user_id, "timestamp": timestamp, "sign": build_balance_sign(user_id, timestamp, settings.business_api_key)}
        try:
            async with httpx.AsyncClient(timeout=settings.business_balance_timeout) as client:
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
                try:
                    result["key"] = await _query_current_key_quota(client)
                except (httpx.HTTPError, ValueError, TypeError):
                    # Key 额度查询失败不影响商户总余额展示
                    result["key"] = None
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            result = unavailable_balance(str(exc) or "余额服务请求失败")
        _cache = result
        _cache_expires_at = time.monotonic() + settings.business_balance_cache_seconds
        return dict(result)


async def query_ppio_balance() -> dict[str, Any]:
    if not settings.ppio_api_key:
        return unavailable_balance("未配置 PPIO_API_KEY")
    try:
        async with httpx.AsyncClient(timeout=settings.ppio_balance_timeout) as client:
            response = await client.get(settings.ppio_balance_url, headers={"Authorization": f"Bearer {settings.ppio_api_key}"})
            response.raise_for_status()
            data = response.json()
        available = _to_float(data.get("availableBalance"))
        if available is None:
            raise ValueError("PPIO 余额接口未返回 availableBalance")
        return {
            "available": True,
            "balance": str(data.get("availableBalance")),
            "balanceDisplay": f"{available:.2f}",
            "currency": "CNY",
            "updatedAt": datetime.now(UTC).isoformat(),
            "message": None,
            "details": {
                "cashBalance": _to_float(data.get("cashBalance")),
                "creditLimit": _to_float(data.get("creditLimit")),
                "pendingCharges": _to_float(data.get("pendingCharges")),
                "outstandingInvoices": _to_float(data.get("outstandingInvoices")),
            },
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return unavailable_balance(str(exc) or "PPIO 余额服务请求失败")


async def query_provider_balances(*, force: bool = False) -> dict[str, Any]:
    yinghe, ppio = await asyncio.gather(query_business_balance(force=force), query_ppio_balance())
    return {"providers": {"yinghe": yinghe, "ppio": ppio}, **yinghe}


def estimate_item_cost(item: Any) -> tuple[str, float]:
    model = str(item.model or "")
    provider = "ppio" if model.endswith("-ppio") else "yinghe"
    if model.startswith("minimax-h3"):
        unit_price = H3_ESTIMATE_PRICE_PER_SECOND
    elif provider == "ppio":
        unit_price = PPIO_SD20_ESTIMATE_PRICE_PER_SECOND
    else:
        unit_price = SD20_ESTIMATE_PRICE_PER_SECOND
    return provider, float(item.duration) * unit_price


async def ensure_video_batch_balance(items: list[Any]) -> dict[str, Any]:
    """按实际渠道分别预检批量视频余额，避免用一个渠道的余额替另一个渠道兜底。"""
    estimates: dict[str, float] = {}
    for item in items:
        provider, amount = estimate_item_cost(item)
        estimates[provider] = estimates.get(provider, 0) + amount
    balances = await query_provider_balances(force=True)
    available_by_provider: dict[str, float] = {}
    for provider, estimated in estimates.items():
        balance = balances["providers"][provider]
        raw_available = (balance.get("key") or {}).get("remaining") if provider == "yinghe" else balance.get("balance")
        available = _to_float(raw_available) if balance.get("available") else None
        if available is None:
            label = "PPIO" if provider == "ppio" else "英和子账号 Key"
            raise ValueError(f"{label} 余额暂时无法获取，请稍后再试")
        if available + 1e-9 < estimated:
            label = "PPIO" if provider == "ppio" else "英和子账号 Key"
            raise ValueError(f"{label} 余额不足，请先完成充值或提升余额上限后再试")
        available_by_provider[provider] = available
    estimated_total = round(sum(estimates.values()), 2)
    return {"estimatedCost": estimated_total, "availableBalance": min(available_by_provider.values(), default=-1.0), "providerEstimates": estimates}
