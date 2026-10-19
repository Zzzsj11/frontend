"""Download an encrypted backup with the server-held customer key and verify its checksum."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tos import TosClientV2  # noqa: E402

from app.backup_archive import backup_encryption  # noqa: E402
from app.config import settings  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--bucket", required=True)
parser.add_argument("--key", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
if not args.key.startswith(("mv/production/backups/", "mv/test/backups/")) or not args.key.endswith(".dump"):
    raise SystemExit("invalid backup key")
path = Path(args.output)
if path.exists():
    raise SystemExit("output already exists")
client = TosClientV2(settings.tos_access_key, settings.tos_secret_key, settings.tos_endpoint, settings.tos_region)
try:
    encryption = backup_encryption(os.environ["BACKUP_TOS_ENCRYPTION_KEY"])
    head = client.head_object(args.bucket, args.key, **encryption)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    client.get_object_to_file(args.bucket, args.key, str(path), **encryption)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != head.meta.get("sha256") or path.stat().st_size != head.content_length:
        raise ValueError("download checksum mismatch")
    print("backup downloaded and SHA-256 verified")
except Exception as exc:
    path.unlink(missing_ok=True)
    print(f"backup download failed: {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1) from None
