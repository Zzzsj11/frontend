"""Environment-specific media paths for the built-in portraits."""

from .config import settings
from .oss_storage import public_host
from .storage import TosStorage


def portrait_key(code: str, thumbnail: bool = False) -> str:
    directory = "system/digital-humans"
    return f"{directory}/{'thumbnails/' if thumbnail else ''}{code}.jpg"


def legacy_portrait_url(key: str) -> str:
    return TosStorage._public_url(*TosStorage._bucket_for(key))


def portrait_url(key: str) -> str:
    if settings.storage_backend == "oss":
        return f"https://{public_host()}/{settings.oss_prefix}/{key}"
    return legacy_portrait_url(key)
