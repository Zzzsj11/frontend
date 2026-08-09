#!/usr/bin/env python3
"""Compress the 30 system character sheets and upload originals plus thumbnails to TOS."""
from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps
from dotenv import load_dotenv

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


async def sync(source: Path) -> None:
    storage = get_storage()
    files = sorted(source.glob("*.png"))
    expected = {f"{index:03d}" for index in range(1, 31)}
    found = {path.stem for path in files}
    if found != expected:
        raise SystemExit(f"Expected character sheets 001–030, got {sorted(found)}")
    for path in files:
        original = jpeg_bytes(path, (1600, 900), 88)
        thumbnail = jpeg_bytes(path, (640, 360), 76)
        await storage.put_bytes(f"system/digital-humans/{path.stem}.jpg", original, "image/jpeg")
        await storage.put_bytes(f"system/digital-humans/thumbnails/{path.stem}.jpg", thumbnail, "image/jpeg")
        print(f"uploaded {path.stem}: original={len(original)} thumbnail={len(thumbnail)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Directory containing 001.png through 030.png")
    args = parser.parse_args()
    asyncio.run(sync(args.source.expanduser().resolve()))


if __name__ == "__main__":
    main()
