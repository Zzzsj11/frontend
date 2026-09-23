#!/usr/bin/env python3
"""Prepare system headshots and an Alembic input mapping; never modify the database."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageOps
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / "backend" / ".env")

# Standalone entry point: configure the backend import path/environment first.
from app.database import session_factory  # noqa: E402
from app.models import DigitalHumanModel  # noqa: E402
from app.providers import create_real_face_asset  # noqa: E402
from app.storage import get_storage  # noqa: E402


def _jpeg_pair(content: bytes) -> tuple[bytes, bytes]:
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if image.size != (1024, 1536):
            raise ValueError(f"expected a 1024x1536 headshot, got {image.width}x{image.height}")
        original = image
        thumbnail = image.copy()
        thumbnail.thumbnail((320, 480), Image.Resampling.LANCZOS)
        original_buffer, thumbnail_buffer = io.BytesIO(), io.BytesIO()
        original.save(
            original_buffer, format="JPEG", quality=90, optimize=True, progressive=True
        )
        thumbnail.save(
            thumbnail_buffer, format="JPEG", quality=78, optimize=True, progressive=True
        )
        return original_buffer.getvalue(), thumbnail_buffer.getvalue()


def _identity_text(human: DigitalHumanModel) -> str:
    return "，".join(
        value.strip() for value in (human.age_description, human.gender) if value and value.strip()
    ) + "。仅参考人物五官、脸型、肤色、年龄感和发型；卡通人物保持卡通风格，儿童不得成人化"


async def replace(manifest_path: Path, dry_run: bool) -> None:
    manifest_path = manifest_path.resolve()
    try:
        manifest = json.loads(manifest_path.read_text())
    except (ValueError, OSError) as exc:
        raise SystemExit(f"cannot read manifest: {exc}") from exc
    if not isinstance(manifest, list) or not manifest:
        raise SystemExit("manifest must be a non-empty JSON array")
    requested = {}
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise SystemExit("manifest rows must have non-empty string ids")
        if item.get("scope", "system") != "system" or item.get("user_id") is not None:
            raise SystemExit("manifest contains a non-system human; private humans require manual updates")
        url = item.get("url")
        if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
            raise SystemExit("manifest URLs must be non-empty HTTP(S) strings")
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port == 0:
                raise ValueError("expected HTTP(S) without credentials and with a valid port")
        except ValueError as exc:
            raise SystemExit(f"invalid manifest URL for {item['id']}: {exc}") from exc
        requested[item["id"]] = item
    if len(requested) != len(manifest):
        raise SystemExit("manifest contains duplicate ids")
    run_id = datetime.now(timezone.utc).strftime("neutral-%Y%m%dT%H%M%SZ-") + uuid4().hex
    backup = []
    asset_mapping = []
    # Read and close the session before external preparation. No ORM mutation, flush or commit.
    async with session_factory() as session:
        humans = list(
            (
                await session.execute(
                    select(DigitalHumanModel).where(
                        DigitalHumanModel.id.in_(requested),
                        DigitalHumanModel.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        if len(humans) != len(requested):
            found = {human.id for human in humans}
            raise SystemExit(f"missing humans: {sorted(set(requested) - found)}")
        for human in humans:
            if human.scope != "system" or human.user_id is not None or human.deleted_at is not None:
                raise SystemExit(f"out-of-scope human (active system only): {human.id}")
            if not human.asset_code or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", human.asset_code):
                raise SystemExit(f"missing or unsafe system asset code: {human.id}")
            # Exact database column names, including lifecycle/identity fields for stale-value guards.
            old_values = {}
            for column in DigitalHumanModel.__table__.columns:
                value = getattr(human, column.name)
                old_values[column.name] = value.isoformat() if isinstance(value, datetime) else value
            backup.append(old_values)
            identity = _identity_text(human)
            asset_mapping.append({
                "id": human.id,
                "code": human.asset_code,
                "source_url": requested[human.id]["url"],
                "generation_job_id": requested[human.id].get("generation_job_id"),
                "generation_run_id": requested[human.id].get("run_id"),
                "original_key": f"system/digital-humans/{run_id}/{human.asset_code}.jpg",
                "thumbnail_key": f"system/digital-humans/{run_id}/thumbnails/{human.asset_code}.jpg",
                "registration_name": f"mv-{human.asset_code}-{run_id}",
                "provider": "yinghe",
                "status": "pending",
                "expected_old": old_values,
                "updates": {
                    "description": identity,
                    "appearance_style": identity,
                    "clothing_description": "",
                    "suitable_music_styles": "",
                    "avatar_prompt": (
                        "1024x1536单张头肩大头照，白色无图案T恤、纯灰背景；"
                        "仅保留人物五官、年龄感和发型，保留卡通/儿童身份"
                    ),
                    "system_prompt": f"图片ID：{human.asset_code}\n人物名称：{human.name}\n性别：{human.gender}\n年龄估计：{human.age_description}\n人物身份描述：{identity}",
                },
            })

    backup_path = manifest_path.with_name(f"{manifest_path.stem}-{run_id}-backup.json")
    mapping_path = manifest_path.with_name(f"{manifest_path.stem}-{run_id}-mapping.json")
    backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "count": len(asset_mapping),
        "backup": str(backup_path),
        "mapping": str(mapping_path),
        "dry_run": dry_run,
        "committed": False,
        "requires_alembic": True,
        "status": "dry_run" if dry_run else "preparing",
        "humans": asset_mapping,
    }

    def save_mapping() -> None:
        temporary = mapping_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        temporary.replace(mapping_path)

    save_mapping()
    if dry_run:
        print(json.dumps(result, ensure_ascii=False))
        return

    try:
        storage = get_storage()
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            for index, row in enumerate(asset_mapping, 1):
                response = await client.get(row["source_url"])
                response.raise_for_status()
                original, thumbnail = _jpeg_pair(response.content)
                row["status"] = "uploading_original"
                save_mapping()
                row["updates"]["avatar_url"] = await storage.put_bytes(row["original_key"], original, "image/jpeg")
                row["status"] = "uploading_thumbnail"
                save_mapping()
                row["updates"]["avatar_thumbnail_url"] = await storage.put_bytes(row["thumbnail_key"], thumbnail, "image/jpeg")
                row["status"] = "registering"
                save_mapping()
                yinghe_asset = await create_real_face_asset(row["updates"]["avatar_url"], name=row["registration_name"])
                if not isinstance(yinghe_asset, str) or not yinghe_asset.startswith("asset://") or not yinghe_asset[8:]:
                    raise ValueError(f"{row['id']}: Yinghe registration returned no asset URL")
                row["updates"]["asset_avatar_url"] = yinghe_asset
                row["status"] = "prepared"
                save_mapping()
                print(json.dumps({"prepared": index, "count": len(asset_mapping), **row}, ensure_ascii=False), flush=True)
        result["status"] = "prepared"
    except BaseException:
        # Upload/registration cannot roll back; preserve partial URLs and planned keys for reconciliation.
        result["status"] = "reconcile_required"
        raise
    finally:
        save_mapping()
        print(json.dumps(result, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate system scope and save backup/plan; no uploads, registration or DB writes")
    args = parser.parse_args()
    asyncio.run(replace(args.manifest.resolve(), args.dry_run))


if __name__ == "__main__":
    main()
