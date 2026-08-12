#!/usr/bin/env python3
"""定时扫描数字人资产表：为缺失 asset:// 链接的人物补注册平台虚拟资产（cron 每分钟调用）。

用法（容器内）：
    python /srv/mvagent/scripts/ensure_asset_avatars.py

宿主机 crontab（每分钟）：
    */1 * * * * docker exec mv-agent-frontend-backend-1 python /srv/mvagent/scripts/ensure_asset_avatars.py >> /var/log/mvagent-asset-sync.log 2>&1

说明：幂等；仅处理 active 且 asset_avatar_url 为空的人物；复用 seed.py 的
ensure_pending_asset_avatars。文件锁防止与上一分钟的任务重入。
"""
from __future__ import annotations

import asyncio
import fcntl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    # 防重入：同一时刻只允许一个同步进程
    lock_path = Path("/tmp/mvagent-asset-sync.lock")
    try:
        lock = lock_path.open("w")
    except OSError:
        lock = None
    if lock is not None:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{time.strftime('%H:%M:%S')}] another sync is running, skip")
            return 0

    from sqlalchemy import func, select

    from app.database import session_factory
    from app.models import DigitalHumanModel
    from app.seed import ensure_pending_asset_avatars

    async def run() -> int:
        async with session_factory() as db:
            missing = await db.scalar(
                select(func.count())
                .select_from(DigitalHumanModel)
                .where(
                    DigitalHumanModel.deleted_at.is_(None),
                    DigitalHumanModel.asset_avatar_url.is_(None),
                    DigitalHumanModel.avatar_url.isnot(None),
                    DigitalHumanModel.avatar_url != "",
                )
            )
        if not missing:
            return 0
        await ensure_pending_asset_avatars()
        return int(missing)

    count = asyncio.run(run())
    print(f"[{time.strftime('%H:%M:%S')}] asset avatar sync: handled {count} pending human(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
