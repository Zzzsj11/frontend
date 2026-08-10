#!/usr/bin/env python3
"""Compress system character sheets and upload originals plus thumbnails to TOS."""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / "backend" / ".env")

from app.storage import get_storage  # noqa: E402


def jpeg_bytes(path: Path, size: tuple[int, int], quality: int) -> bytes:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        return output.getvalue()


async def upload_assets(assets: list[tuple[str, Path]]) -> None:
    storage = get_storage()
    for asset_code, path in assets:
        original = jpeg_bytes(path, (1600, 900), 88)
        thumbnail = jpeg_bytes(path, (640, 360), 76)
        await storage.put_bytes(f"system/digital-humans/{asset_code}.jpg", original, "image/jpeg")
        await storage.put_bytes(f"system/digital-humans/thumbnails/{asset_code}.jpg", thumbnail, "image/jpeg")
        print(f"uploaded {asset_code}: original={len(original)} thumbnail={len(thumbnail)}")


def directory_assets(source: Path) -> list[tuple[str, Path]]:
    files = sorted(source.glob("*.png"))
    expected = {f"{index:03d}" for index in range(1, 31)}
    found = {path.stem for path in files}
    if found != expected:
        raise SystemExit(f"Expected character sheets 001–030, got {sorted(found)}")
    return [(path.stem, path) for path in files]


def explicit_assets(values: list[str]) -> list[tuple[str, Path]]:
    result = []
    for value in values:
        asset_code, separator, filename = value.partition("=")
        path = Path(filename).expanduser().resolve()
        if not separator or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", asset_code) or not path.is_file():
            raise SystemExit(f"Invalid --asset value: {value!r}; expected CODE=/path/to/image")
        result.append((asset_code, path))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", type=Path, help="Directory containing 001.png through 030.png")
    parser.add_argument("--asset", action="append", default=[], help="Upload one asset as CODE=/path/to/image; repeat as needed")
    args = parser.parse_args()
    if bool(args.source) == bool(args.asset):
        parser.error("provide either a source directory or one or more --asset values")
    assets = explicit_assets(args.asset) if args.asset else directory_assets(args.source.expanduser().resolve())
    asyncio.run(upload_assets(assets))


if __name__ == "__main__":
    main()
