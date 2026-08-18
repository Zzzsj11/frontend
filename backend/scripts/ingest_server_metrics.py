"""Read a host metric JSON sample from stdin and persist it."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import session_factory
from app.server_monitoring import ingest_server_metric


async def main() -> None:
    payload = json.load(sys.stdin)
    async with session_factory() as db:
        sample = await ingest_server_metric(db, payload)
        print(sample.id)


if __name__ == "__main__":
    asyncio.run(main())
