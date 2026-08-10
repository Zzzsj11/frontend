from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import utcnow

QUOTA_LABELS = {"chat": "Chat", "image": "图片生成", "video": "视频生成"}


def quota_date() -> date:
    try:
        timezone = ZoneInfo(settings.daily_quota_timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Asia/Shanghai")
    return datetime.now(timezone).date()


async def consume_daily_quota(db: AsyncSession, *, user_id: str, category: str, limit: int) -> int:
    """Atomically consume one accepted model call from a user's natural-day quota."""
    if category not in QUOTA_LABELS:
        raise ValueError(f"未知限额分类：{category}")
    now = utcnow()
    result = await db.execute(
        text(
            """
            INSERT INTO daily_usage_quotas
                (id, user_id, usage_date, category, usage_count, created_at, updated_at, deleted_at)
            VALUES
                (:id, :user_id, :usage_date, :category, 1, :now, :now, NULL)
            ON CONFLICT (user_id, usage_date, category) DO UPDATE
            SET usage_count = daily_usage_quotas.usage_count + 1,
                updated_at = :now
            WHERE daily_usage_quotas.usage_count < :limit
              AND daily_usage_quotas.deleted_at IS NULL
            RETURNING usage_count
            """
        ),
        {
            "id": f"quota-{uuid.uuid4().hex}",
            "user_id": user_id,
            "usage_date": quota_date(),
            "category": category,
            "limit": limit,
            "now": now,
        },
    )
    consumed = result.scalar_one_or_none()
    if consumed is None:
        await db.rollback()
        raise HTTPException(429, f"今日{QUOTA_LABELS[category]}调用量已达到上限（{limit}次），请明日再试")
    await db.commit()
    return int(consumed)
