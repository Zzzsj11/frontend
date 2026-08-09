from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"


def _load_dotenv() -> None:
    path = BACKEND_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _read_shared_provider_key() -> str:
    direct = os.getenv("AIGC_TOKEN", "")
    if direct:
        return direct
    for path in (Path("/run/secrets/provider_config"), BACKEND_DIR / ".provider_config.py"):
        if not path.is_file():
            continue
        match = re.search(r'^AIGC_TOKEN\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1)
    return ""


SHARED_PROVIDER_KEY = _read_shared_provider_key()


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "8000"))
    cors_origins: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("APP_CORS_ORIGINS", "http://localhost:5173").split(",")
        if value.strip()
    )
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://mvagent:mvagent@127.0.0.1:5433/mvagent"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-change-me-at-least-32-bytes")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
    refresh_cookie_secure: bool = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"
    llm_base_url: str = os.getenv("LLM_BASE_URL") or (
        "https://ai-aigc.fzyinghe.com/v1"
        if SHARED_PROVIDER_KEY
        else os.getenv("ANTHROPIC_BASE_URL", "https://api.openai.com/v1")
    )
    llm_api_key: str = os.getenv("LLM_API_KEY") or SHARED_PROVIDER_KEY or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
    llm_model: str = os.getenv("LLM_MODEL") or os.getenv("AIGC_CHAT_MODEL") or os.getenv("MODEL_ID", "gpt-4o-mini")
    llm_api_mode: str = os.getenv("LLM_API_MODE", "openai").lower()
    storyboard_generation_concurrency: int = max(1, min(8, int(os.getenv("STORYBOARD_GENERATION_CONCURRENCY", "4"))))
    image_api_base_url: str = os.getenv("IMAGE_API_BASE_URL", "https://api-aigc.fzyinghe.com")
    image_api_key: str = os.getenv("IMAGE_API_KEY") or SHARED_PROVIDER_KEY
    image_model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")
    video_api_base_url: str = os.getenv("VIDEO_API_BASE_URL", "https://api-aigc.fzyinghe.com")
    video_api_key: str = os.getenv("VIDEO_API_KEY") or SHARED_PROVIDER_KEY
    video_model: str = os.getenv("VIDEO_MODEL", "doubao-seedance-2.0")
    business_api_key: str = os.getenv("BUSINESS_API_KEY", "")
    business_user_id: str = os.getenv("BUSINESS_USER_ID", "")
    business_balance_url: str = os.getenv("BUSINESS_BALANCE_URL", "https://api-aigc.fzyinghe.com/business/reconcile/balance")
    business_balance_timeout: float = float(os.getenv("BUSINESS_BALANCE_TIMEOUT", "10"))
    business_balance_cache_seconds: int = max(5, int(os.getenv("BUSINESS_BALANCE_CACHE_SECONDS", "30")))
    storage_backend: str = os.getenv("STORAGE_BACKEND", "tos").lower()
    tos_endpoint: str = os.getenv("TOS_ENDPOINT", "")
    tos_region: str = os.getenv("TOS_REGION", "")
    tos_access_key: str = os.getenv("TOS_ACCESS_KEY_ID", "")
    tos_secret_key: str = os.getenv("TOS_SECRET_ACCESS_KEY", "")
    tos_reference_bucket: str = os.getenv("TOS_REFERENCE_BUCKET", "")
    tos_video_bucket: str = os.getenv("TOS_VIDEO_ARCHIVE_BUCKET", "")
    tos_reference_prefix: str = os.getenv("TOS_REFERENCE_PREFIX", "mv-agent/references").strip("/")
    tos_video_prefix: str = os.getenv("TOS_VIDEO_ARCHIVE_PREFIX", "mv-agent/generated-videos").strip("/")
    tos_public_domain: str = os.getenv("TOS_PUBLIC_BUCKET_DOMAIN", "").replace("https://", "").replace("http://", "").strip("/")


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
