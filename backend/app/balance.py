from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import settings

_cache: dict[str, Any] | None = None
_cache_expires_at = 0.0
_lock = asyncio.Lock()


def build_balance_sign(user_id: str, timestamp: int, api_key: str) -> str:
    raw = f"timestamp={timestamp}&userId={user_id}&key={api_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()  # noqa: S324 - upstream protocol requires MD5


def unavailable_balance(message: str = "余额暂不可用") -> dict[str, Any]:
    return {"available": False, "balance": None, "balanceDisplay": "--", "currency": "credits", "updatedAt": datetime.now(UTC).isoformat(), "message": message}


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
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            result = unavailable_balance(str(exc) or "余额服务请求失败")
        _cache = result
        _cache_expires_at = time.monotonic() + settings.business_balance_cache_seconds
        return dict(result)
