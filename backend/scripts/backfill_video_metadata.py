from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import session_factory
from app.models import GenerationJobModel, ShotAssetModel
from app.video_metadata import probe_video_url, provider_resolution


async def run(limit: int) -> None:
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(ShotAssetModel, GenerationJobModel)
                .outerjoin(GenerationJobModel, GenerationJobModel.id == ShotAssetModel.generation_job_id)
                .where(ShotAssetModel.deleted_at.is_(None), ShotAssetModel.actual_width.is_(None))
                .order_by(ShotAssetModel.created_at)
                .limit(limit)
            )
        ).all()
    succeeded = failed = 0
    for asset, job in rows:
        try:
            metadata = await probe_video_url(asset.video_url)
            request = job.request if job else {}
            requested = str((request or {}).get("resolution") or asset.resolution or "720p")
            capabilities = (request or {}).get("_capabilities") if isinstance((request or {}).get("_capabilities"), dict) else None
            async with session_factory() as session:
                current = await session.get(ShotAssetModel, asset.id)
                current.requested_resolution = requested
                current.provider_resolution = provider_resolution(str((request or {}).get("model") or current.model_code or ""), requested, capabilities)
                current.actual_width = metadata["actualWidth"]
                current.actual_height = metadata["actualHeight"]
                current.fps = metadata["fps"]
                current.codec = metadata["codec"]
                current.actual_duration = metadata["actualDuration"]
                current.file_size = metadata["fileSize"]
                if job:
                    current_job = await session.get(GenerationJobModel, job.id)
                    current_job.result = {**(current_job.result or {}), **metadata, "requestedResolution": requested, "providerResolution": current.provider_resolution}
                await session.commit()
            succeeded += 1
        except Exception as exc:
            failed += 1
            print(f"failed asset={asset.id}: {str(exc)[:200]}")
    print({"selected": len(rows), "succeeded": succeeded, "failed": failed})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    asyncio.run(run(max(1, args.limit)))
