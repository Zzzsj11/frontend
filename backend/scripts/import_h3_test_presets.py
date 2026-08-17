"""Archive completed H3 test outputs in TOS and seed per-admin test presets.

This script is idempotent by task_id. It intentionally stores no credentials or media in git.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import session_factory  # noqa: E402
from app.models import H3TestPresetModel, UserModel  # noqa: E402
from app.runninghub import query_task  # noqa: E402
from app.storage import get_storage, import_remote, safe_key  # noqa: E402

TASKS = (
    ("2089322216687886337", "H3 纯文本示例", "text", "minimax_h3_text_to_video.json", "25", 6),
    ("2089324649245790209", "H3 多图参考示例", "reference", "reference-api.json", "83", 12),
    ("2089326744648765442", "H3 首帧示例", "first_frame", "minimax_h3_first_frame_to_video.json", "55", 8),
    ("2089335383799332866", "H3 六图三视频三音频示例", "reference", "reference-api.json", "83", 12),
)


def load_prompt(workflow_path: Path, node_id: str) -> str:
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    return str(data[node_id]["inputs"]["text"])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="admin")
    parser.add_argument("--reference-workflow", required=True, type=Path)
    parser.add_argument("--reference-video-dir", type=Path)
    args = parser.parse_args()
    workflow_dir = Path(__file__).resolve().parents[1] / "app" / "workflows"
    async with session_factory() as db:
            user = (await db.execute(select(UserModel).where(UserModel.username == args.username, UserModel.deleted_at.is_(None)))).scalar_one()
            uploaded_refs: list[dict] = []
            if args.reference_video_dir:
                for index in range(1, 4):
                    path = args.reference_video_dir / f"ref{index}.mp4"
                    if path.exists():
                        url = await get_storage().put_file(safe_key(f"h3-tests/videos/{user.id}", path.name), path, "video/mp4")
                        uploaded_refs.append({"type": "video", "name": f"参考视频 {index}", "url": url})
            for order, (task_id, name, mode, filename, node_id, duration) in enumerate(TASKS):
                existing = (
                    await db.execute(
                        select(H3TestPresetModel).where(
                            H3TestPresetModel.user_id == user.id,
                            H3TestPresetModel.task_id == task_id,
                            H3TestPresetModel.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    print("exists", task_id)
                    continue
                result = await query_task(task_id)
                outputs = []
                for index, output in enumerate(result.get("results") or []):
                    source = output["url"]
                    url = await import_remote(source, f"h3-tests/videos/{user.id}", f"{task_id}-{index}.mp4")
                    outputs.append({**output, "type": "video", "sourceUrl": source, "url": url})
                inputs = uploaded_refs if task_id == "2089335383799332866" else []
                db.add(
                    H3TestPresetModel(
                        id=f"h3test-{uuid.uuid4().hex}", user_id=user.id, name=name, mode=mode,
                        prompt=load_prompt(args.reference_workflow if filename == "reference-api.json" else workflow_dir / filename, node_id), duration=duration,
                        aspect_ratio="16:9 (Widescreen)", input_media=inputs, output_media=outputs,
                        task_id=task_id, task_status=result.get("status", "SUCCESS"), usage_data=result.get("usage") or {},
                        sort_order=order,
                    )
                )
                print("imported", task_id, url)
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
