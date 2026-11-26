"""Copy built-in system portrait media into the current environment's OSS."""

from hashlib import sha256
from io import BytesIO

import httpx
import sqlalchemy as sa
from alembic import context, op
from PIL import Image

from app.config import settings, validate_runtime_security
from app.headshot_assets import HEADSHOT_ASSETS
from app.oss_storage import OssStorage, internal_read_url
from app.storage import is_tos_url
from app.system_human_media import legacy_portrait_url, portrait_key, portrait_url
from app.system_humans import SYSTEM_HUMANS

revision = "0dc71af19e32"
down_revision = "d83108ae269f"
branch_labels = None
depends_on = None

_MAX_BYTES = 20 * 1024 * 1024
_IMAGE_TYPES = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}


def _copy(client, storage, source, key, *, versioned=False):
    if not is_tos_url(source):
        raise RuntimeError(f"Unexpected source for system portrait {key}")
    content = bytearray()
    with client.stream("GET", source) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > _MAX_BYTES:
                raise RuntimeError(f"System portrait exceeds size limit: {key}")
    with Image.open(BytesIO(content)) as image:
        extension, content_type = _IMAGE_TYPES[image.format]
        image.verify()
    if versioned:
        directory, filename = key.rsplit("/", 1)
        version = "neutral-" if "/neutral-" in source else "legacy-"
        key = f"{directory}/{version}{sha256(content).hexdigest()}/{filename.rsplit('.', 1)[0]}.{extension}"
    object_key = f"{settings.oss_prefix}/{key}"
    storage.bucket.put_object(object_key, bytes(content), headers={"Content-Type": content_type})
    destination = portrait_url(key)
    client.head(destination).raise_for_status()
    return destination


def upgrade():
    if settings.storage_backend != "oss":
        return
    if context.is_offline_mode():
        raise RuntimeError("OSS portrait migration requires an online Alembic upgrade")
    validate_runtime_security()
    connection = op.get_bind()
    humans = sa.table(
        "digital_humans",
        sa.column("id"),
        sa.column("scope"),
        sa.column("user_id"),
        sa.column("deleted_at"),
        sa.column("updated_at"),
        sa.column("avatar_url"),
        sa.column("avatar_thumbnail_url"),
    )
    scope = (humans.c.scope == "system", humans.c.user_id.is_(None), humans.c.deleted_at.is_(None))
    storage = OssStorage()
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for human in SYSTEM_HUMANS:
            code = human["asset_code"]
            human_id = f"dh-system-{code}"
            match = (*scope, humans.c.id == human_id)
            row = connection.execute(sa.select(humans).where(*match)).mappings().one_or_none()
            changes = {}
            for field, thumbnail in (("avatar_url", False), ("avatar_thumbnail_url", True)):
                key = portrait_key(code, thumbnail)
                default = HEADSHOT_ASSETS.get(human_id, {}).get(field) or legacy_portrait_url(key)
                current = row[field] if row else None
                source = current or default
                if current and internal_read_url(current):
                    continue
                changes[field] = _copy(client, storage, source, key, versioned=source != default)
            if row and changes:
                connection.execute(humans.update().where(*match).values(updated_at=sa.func.now(), **changes))


def downgrade():
    # Old code can read the published URLs. Retain the copied media and the references.
    pass
