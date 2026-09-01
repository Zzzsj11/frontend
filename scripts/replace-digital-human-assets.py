#!/usr/bin/env python3
"""Atomically replace system/dev01 identity cards and both provider assets.

Manifest format: [{"id": "dh-...", "url": "https://..."}, ...]. The source
images must already be generated through the audited application API.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image, ImageOps
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / "backend" / ".env")

from app.database import session_factory
from app.models import DigitalHumanModel, UserModel
from app.providers import (
    create_ppio_synthetic_image_asset,
    create_real_face_asset,
)
from app.storage import get_storage


def _jpeg_pair(content: bytes) -> tuple[bytes, bytes]:
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        original = image.copy()
        original.thumbnail((1600, 900), Image.Resampling.LANCZOS)
        thumbnail = image.copy()
        thumbnail.thumbnail((640, 360), Image.Resampling.LANCZOS)
        original_buffer, thumbnail_buffer = io.BytesIO(), io.BytesIO()
        original.save(
            original_buffer, format="JPEG", quality=90, optimize=True, progressive=True
        )
        thumbnail.save(
            thumbnail_buffer, format="JPEG", quality=78, optimize=True, progressive=True
        )
        return original_buffer.getvalue(), thumbnail_buffer.getvalue()


def _identity_text(human: DigitalHumanModel) -> str:
    return (
        "，".join(value for value in (human.age_description, human.gender) if value)
        or human.name
    )


async def replace(
    manifest_path: Path, owner_username: str, include_system: bool, dry_run: bool
) -> None:
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, list) or not manifest:
        raise SystemExit("manifest must be a non-empty JSON array")
    requested = {str(item["id"]): str(item["url"]) for item in manifest}
    if len(requested) != len(manifest):
        raise SystemExit("manifest contains duplicate ids")
    run_id = datetime.now(timezone.utc).strftime("neutral-%Y%m%dT%H%M%SZ")
    async with session_factory() as session:
        owner = (
            await session.execute(
                select(UserModel).where(
                    UserModel.username == owner_username, UserModel.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if not owner:
            raise SystemExit(f"owner not found: {owner_username}")
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
            allowed = human.user_id == owner.id or (
                include_system and human.scope == "system"
            )
            if not allowed:
                raise SystemExit(f"out-of-scope human: {human.id}")
        backup = [
            {
                "id": human.id,
                "user_id": human.user_id,
                "scope": human.scope,
                "avatar_url": human.avatar_url,
                "avatar_thumbnail_url": human.avatar_thumbnail_url,
                "asset_avatar_url": human.asset_avatar_url,
                "ppio_asset_avatar_url": human.ppio_asset_avatar_url,
                "description": human.description,
                "appearance_style": human.appearance_style,
                "clothing_description": human.clothing_description,
                "suitable_music_styles": human.suitable_music_styles,
                "system_prompt": human.system_prompt,
            }
            for human in humans
        ]
        backup_path = manifest_path.with_name(
            f"{manifest_path.stem}-{run_id}-backup.json"
        )
        backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2))
        if dry_run:
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "count": len(humans),
                        "backup": str(backup_path),
                        "dry_run": True,
                    },
                    ensure_ascii=False,
                )
            )
            return

        storage = get_storage()
        prepared = []
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            for index, human in enumerate(humans, 1):
                response = await client.get(requested[human.id])
                response.raise_for_status()
                original, thumbnail = _jpeg_pair(response.content)
                owner_prefix = (
                    "system" if human.scope == "system" else f"users/{human.user_id}"
                )
                code = human.asset_code or human.id
                original_url = await storage.put_bytes(
                    f"{owner_prefix}/digital-humans/{run_id}/{code}.jpg",
                    original,
                    "image/jpeg",
                )
                thumbnail_url = await storage.put_bytes(
                    f"{owner_prefix}/digital-humans/{run_id}/thumbnails/{code}.jpg",
                    thumbnail,
                    "image/jpeg",
                )
                yinghe_asset, ppio_asset = await asyncio.gather(
                    create_real_face_asset(original_url, name=f"mv-{code}-{run_id}"),
                    create_ppio_synthetic_image_asset(original_url),
                )
                prepared.append(
                    (human, original_url, thumbnail_url, yinghe_asset, ppio_asset)
                )
                print(f"prepared {index}/{len(humans)} {human.id}", flush=True)

        for human, original_url, thumbnail_url, yinghe_asset, ppio_asset in prepared:
            identity = _identity_text(human)
            human.avatar_url = original_url
            human.avatar_thumbnail_url = thumbnail_url
            human.asset_avatar_url = yinghe_asset
            human.ppio_asset_avatar_url = ppio_asset
            human.description = identity
            human.appearance_style = identity
            human.clothing_description = ""
            human.suitable_music_styles = ""
            human.avatar_prompt = (
                "中性人物身份参考卡，仅保留人物五官、年龄感、发型与身体比例"
            )
            if human.scope == "system":
                human.system_prompt = f"图片ID：{human.asset_code}\n人物名称：{human.name}\n性别：{human.gender}\n年龄估计：{human.age_description}\n人物身份描述：{identity}"
        await session.commit()
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "count": len(prepared),
                    "backup": str(backup_path),
                    "committed": True,
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--owner-username", default="dev01")
    parser.add_argument("--include-system", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        replace(
            args.manifest.resolve(),
            args.owner_username,
            args.include_system,
            args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
