"""独立私有 TOS Bucket 的加密备份上传；未配置或无法验证私有性时拒绝上传。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from tos.enum import ACLType
from tos.exceptions import TosServerError


def require_private_bucket(client, bucket: str) -> None:
    acl = client.get_bucket_acl(bucket)
    for grant in acl.grants:
        grantee = grant.grantee
        if getattr(grantee, "canned", None) or (getattr(grantee, "id", None) and grantee.id != acl.owner.id):
            raise RuntimeError("备份 Bucket ACL 必须仅允许所有者访问")
    try:
        policy = json.loads(client.get_bucket_policy(bucket).policy)
    except TosServerError as exc:
        if exc.status_code != 404 or exc.code != "NoSuchBucketPolicy":
            raise
        return
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if str(statement.get("Effect", "")).lower() == "allow":
            principal = statement.get("Principal")
            if not principal or "*" in json.dumps(principal):
                raise RuntimeError("备份 Bucket 禁止通配符公开访问策略")


def backup_encryption(key: str) -> dict:
    raw = base64.b64decode(key, validate=True)
    if len(raw) != 32:
        raise ValueError("备份加密密钥必须为32字节的Base64编码")
    return {"ssec_algorithm": "AES256", "ssec_key": key, "ssec_key_md5": base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()}


def archive_backup(client, bucket: str, prefix: str, path: Path, expected_sha256: str, *, encryption_key: str = "") -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("备份 Bucket 名称无效")
    if any(part in {".", ".."} for part in prefix.split("/")):
        raise ValueError("备份目录无效")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest != expected_sha256:
        raise ValueError("备份 SHA-256 不匹配，停止上传")
    encryption = backup_encryption(encryption_key) if encryption_key else {"server_side_encryption": "AES256"}
    if not encryption_key:
        require_private_bucket(client, bucket)
    elif not prefix.strip("/").startswith(("mv/production/backups/", "mv/test/backups/")):
        raise ValueError("共享 Bucket 备份必须使用独立环境目录")
    key = "/".join(filter(None, (prefix.strip("/"), path.name)))
    client.upload_file(bucket, key, str(path), **encryption, acl=ACLType.ACL_Private, meta={"sha256": digest}, enable_checkpoint=False, task_num=2)
    head = client.head_object(bucket, key, **(backup_encryption(encryption_key) if encryption_key else {}))
    headers = {key.lower(): value for key, value in head.header.items()}
    if (
        head.content_length != path.stat().st_size
        or head.meta.get("sha256") != digest
        or headers.get("x-tos-server-side-encryption-customer-algorithm" if encryption_key else "x-tos-server-side-encryption") != "AES256"
    ):
        raise RuntimeError("备份对象长度、校验信息或加密状态未通过验证")
    client.put_object(bucket, key + ".sha256", content=f"{digest}  {path.name}\n".encode(), **encryption, acl=ACLType.ACL_Private)
    return {"bucket": bucket, "key": key, "bytes": path.stat().st_size, "sha256": digest, "encryption": "AES256"}
