"""公开执行服务负责余额采集；后台通过共享数据库消费脱敏快照。"""

import asyncio
import os
from datetime import timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from .credits import lock
from .db import ChannelAccount, Session, now
from .yinghe_business import BusinessError, YingheBusiness, mask, number

AUTOMATIC = ("yinghe", "yseeai", "toapis")


async def fetch(row):
    if row.channel in ("yinghe", "yseeai"):
        return await YingheBusiness(row.channel, target_env=row.key_env).balance()
    key = os.getenv(row.key_env, "")
    if row.channel == "toapis" and key:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://toapis.cn/v1/user/balance", headers={"Authorization": "Bearer " + key})
            response.raise_for_status()
            data = response.json()
        if not data.get("success") or data.get("unlimited_quota"):
            raise BusinessError("Toapis 未返回可核实的有限账户余额")
        return {
            "balance": number(data["remain_credits"]),
            "remain_credits": number(data["remain_credits"]),
            "used_credits": number(data["used_credits"]),
            "credits_per_usd": number(data["credits_per_usd"]),
            "used_balance": number(Decimal(str(data["used_credits"])) / Decimal(str(data["credits_per_usd"]))),
            "key_masked": mask(key),
            "currency": "POINTS",
            "source": "provider",
        }
    raise BusinessError("未配置该渠道的余额查询凭据")


async def sync_one():
    async with Session.begin() as db:
        await lock(db)
        row = await db.scalar(
            select(ChannelAccount)
            .where(
                ChannelAccount.deleted_at.is_(None),
                ChannelAccount.channel.in_(AUTOMATIC),
                ChannelAccount.next_check_at <= now(),
            )
            .order_by(ChannelAccount.next_check_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not row:
            return False
        # 120 秒采集截止时间短于租约；进程崩溃后可安全重查只读接口。
        row.attempted_at = now()
        row.next_check_at = now() + timedelta(seconds=900)
        account_id, stamp = row.id, row.attempted_at
    try:
        snapshot = await asyncio.wait_for(fetch(row), timeout=120)
        error = None
    except (BusinessError, TimeoutError) as exc:
        snapshot = None
        error = str(exc) if isinstance(exc, BusinessError) else "余额查询超时"
    except Exception:
        snapshot, error = None, "余额查询失败，请检查执行服务配置"
    async with Session.begin() as db:
        current = await db.get(ChannelAccount, account_id, with_for_update=True)
        if not current or current.deleted_at or current.attempted_at.replace(tzinfo=None) != stamp.replace(tzinfo=None):
            return True
        if snapshot is not None:
            current.snapshot = {**snapshot, "source": "provider"}
            current.queried_at = now()
        current.error = error
        current.next_check_at = now() + timedelta(seconds=300)
    return True


async def loop():
    while True:
        try:
            if await sync_one():
                continue
        except Exception:
            # 余额故障不影响生成；部署时仍必须先执行 Alembic。
            import logging

            logging.getLogger(__name__).warning("Channel balance collector unavailable; retrying in 10 seconds")
        await asyncio.sleep(10)
