from __future__ import annotations

from datetime import datetime


def generation_elapsed_seconds(
    *,
    created_at: datetime | None,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float | None:
    """计算端到端生成耗时，优先从 Worker 实际开始时间起算。"""
    started = started_at or created_at
    if started is None or finished_at is None:
        return None
    return round(max(0.0, (finished_at - started).total_seconds()), 3)
