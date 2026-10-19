"""从标准输入接收备份，不把数据库内容或凭据写入日志。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tos import TosClientV2  # noqa: E402

from app.backup_archive import archive_backup  # noqa: E402
from app.config import settings  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--bucket", required=True)
parser.add_argument("--prefix", default="mv-agent/database")
parser.add_argument("--name", required=True)
parser.add_argument("--sha256", required=True)
args = parser.parse_args()
if Path(args.name).name != args.name or not args.name.endswith(".dump"):
    raise SystemExit("invalid backup filename")
if args.bucket in {settings.tos_reference_bucket, settings.tos_video_bucket} and not os.getenv("BACKUP_TOS_ENCRYPTION_KEY"):
    raise SystemExit("backup requires a separate private bucket")
if bool(os.getenv("BACKUP_TOS_ACCESS_KEY_ID")) != bool(os.getenv("BACKUP_TOS_SECRET_ACCESS_KEY")):
    raise SystemExit("backup credentials must be configured as a complete pair")
client = TosClientV2(
    os.getenv("BACKUP_TOS_ACCESS_KEY_ID") or settings.tos_access_key,
    os.getenv("BACKUP_TOS_SECRET_ACCESS_KEY") or settings.tos_secret_key,
    os.getenv("BACKUP_TOS_ENDPOINT") or settings.tos_endpoint,
    os.getenv("BACKUP_TOS_REGION") or settings.tos_region,
)
try:
    with tempfile.TemporaryDirectory(prefix="mv-backup-") as directory:
        path = Path(directory) / args.name
        with path.open("wb") as output:
            shutil.copyfileobj(sys.stdin.buffer, output, 1024 * 1024)
        print(json.dumps(archive_backup(client, args.bucket, args.prefix, path, args.sha256, encryption_key=os.getenv("BACKUP_TOS_ENCRYPTION_KEY", ""))))
except Exception as exc:
    # SDK 错误对象可能包含请求信息；备份日志不输出原始异常和凭据。
    print(f"backup upload failed: {type(exc).__name__}; status={getattr(exc, 'status_code', 'n/a')}", file=sys.stderr)
    raise SystemExit(1) from None
