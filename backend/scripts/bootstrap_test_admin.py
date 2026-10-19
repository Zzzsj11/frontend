"""Create the first test administrator before exposing the API; never reset an existing account."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import func, select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.database import close_database, session_factory  # noqa: E402
from app.models import UserModel  # noqa: E402


async def main():
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if os.getenv("DEPLOYMENT_TIER") != "test" or len(password) < 20:
        raise RuntimeError("test tier and strong bootstrap password required")
    try:
        async with session_factory() as session:
            if await session.scalar(select(func.count()).select_from(UserModel)):
                raise RuntimeError("refusing to replace existing users")
            session.add(
                UserModel(
                    id=f"user-{uuid.uuid4().hex}", username="admin", display_name="测试管理员", password_hash=hash_password(password), role="admin", must_change_password=False
                )
            )
            await session.commit()
        print("isolated test administrator created")
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
