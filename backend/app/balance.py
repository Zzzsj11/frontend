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


async def ensure_video_batch_balance(items: list[Any]) -> dict[str, float]:
    """按当前 Key 剩余额度预检批量视频；H3 0.425 元/秒，SD2.0 0.83 元/秒。"""
    estimated = sum(float(item.duration) * (H3_ESTIMATE_PRICE_PER_SECOND if str(item.model or "").startswith("minimax-h3") else SD20_ESTIMATE_PRICE_PER_SECOND) for item in items)
    balance = await query_business_balance(force=True)
    key_remaining = ((balance.get("key") or {}).get("remaining")) if balance.get("available") else None
    available = _to_float(key_remaining)
    if available is not None and available + 1e-9 < estimated:
        raise ValueError("子账号 Key 余额额度不足，请先完成充值或提升余额上限后再试")
    return {"estimatedCost": round(estimated, 2), "availableBalance": available if available is not None else -1.0}
