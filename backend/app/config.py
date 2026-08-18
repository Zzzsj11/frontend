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


def _read_provider_value(name: str) -> str:
    direct = os.getenv(name, "")
    if direct:
        return direct
    for path in (Path("/run/secrets/provider_config"), BACKEND_DIR / ".provider_config.py"):
        if not path.is_file():
            continue
        match = re.search(rf'^{re.escape(name)}\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1)
    return ""


SHARED_PROVIDER_KEY = _read_provider_value("AIGC_TOKEN")
SHARED_LLM_BASE_URL = _read_provider_value("CHAT_COMPLETIONS_BASE_URL") or "https://ai-aigc.fzyinghe.com/v1"
SHARED_LLM_MODEL = _read_provider_value("CHAT_DEFAULT_MODEL") or os.getenv("AIGC_CHAT_MODEL", "gpt-5.5")


def _resolve_llm_settings(shared_key: str, shared_base_url: str, shared_model: str) -> tuple[str, str, str]:
    if shared_key:
        return shared_base_url, shared_key, shared_model
    return (
        os.getenv("LLM_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL", "https://api.openai.com/v1"),
        os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
        os.getenv("LLM_MODEL") or os.getenv("AIGC_CHAT_MODEL") or os.getenv("MODEL_ID", "gpt-4o-mini"),
    )


LLM_BASE_URL, LLM_API_KEY, LLM_MODEL = _resolve_llm_settings(SHARED_PROVIDER_KEY, SHARED_LLM_BASE_URL, SHARED_LLM_MODEL)


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = int(os.getenv("APP_PORT", "8000"))
    cors_origins: tuple[str, ...] = tuple(value.strip() for value in os.getenv("APP_CORS_ORIGINS", "http://localhost:5173").split(",") if value.strip())
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://mvagent:mvagent@127.0.0.1:5433/mvagent")
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")
    jwt_secret: str = os.getenv("JWT_SECRET", "development-only-change-me-at-least-32-bytes")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
    refresh_cookie_secure: bool = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"
    # 统一供应商 Secret 中的 Token、地址和模型必须成组使用，避免旧环境变量将
    # 共享 Token 误发到其他供应商。没有共享 Token 时才允许独立 LLM_* 覆盖。
    llm_base_url: str = LLM_BASE_URL
    llm_api_key: str = LLM_API_KEY
    llm_model: str = LLM_MODEL
    llm_api_mode: str = os.getenv("LLM_API_MODE", "openai").lower()
    storyboard_generation_concurrency: int = max(1, min(8, int(os.getenv("STORYBOARD_GENERATION_CONCURRENCY", "4"))))
    export_concurrency: int = max(1, min(8, int(os.getenv("EXPORT_CONCURRENCY", "4"))))
    export_per_user_concurrency: int = max(1, min(4, int(os.getenv("EXPORT_PER_USER_CONCURRENCY", "2"))))
    # 单个素材导出任务最多同时拉取 20 个源文件；下载过程按 1 MiB 分块落盘，不整文件驻留内存。
    export_download_concurrency: int = max(1, min(20, int(os.getenv("EXPORT_DOWNLOAD_CONCURRENCY", "20"))))
    export_upload_concurrency: int = max(1, min(8, int(os.getenv("EXPORT_UPLOAD_CONCURRENCY", "4"))))
    export_upload_part_size_mb: int = max(5, min(64, int(os.getenv("EXPORT_UPLOAD_PART_SIZE_MB", "16"))))
    # 默认只记录带 X-Test-Run-Id 头的测试流量；置 true 后全量请求入库（排查用，注意数据量）
    api_request_log_all: bool = os.getenv("API_REQUEST_LOG_ALL", "false").lower() == "true"
    daily_quota_timezone: str = os.getenv("DAILY_QUOTA_TIMEZONE", "Asia/Shanghai")
    daily_chat_limit: int = max(1, int(os.getenv("DAILY_CHAT_LIMIT", "1000")))
    daily_image_limit: int = max(1, int(os.getenv("DAILY_IMAGE_LIMIT", "1000")))
    daily_video_limit: int = max(1, int(os.getenv("DAILY_VIDEO_LIMIT", "1000")))
    image_generation_concurrency: int = max(1, min(1000, int(os.getenv("IMAGE_GENERATION_CONCURRENCY", "200"))))
    video_generation_concurrency: int = max(1, min(1000, int(os.getenv("VIDEO_GENERATION_CONCURRENCY", "200"))))
    # 图片/视频共用同一个上游账户并发池，避免两类各 200 时合计超发。
    provider_generation_worker_concurrency: int = max(1, min(200, int(os.getenv("PROVIDER_GENERATION_WORKER_CONCURRENCY", "200"))))
    image_result_processing_concurrency: int = max(1, min(100, int(os.getenv("IMAGE_RESULT_PROCESSING_CONCURRENCY", "40"))))
    video_result_processing_concurrency: int = max(1, min(100, int(os.getenv("VIDEO_RESULT_PROCESSING_CONCURRENCY", "20"))))
    image_api_base_url: str = os.getenv("IMAGE_API_BASE_URL", "https://api-aigc.fzyinghe.com")
    image_api_key: str = os.getenv("IMAGE_API_KEY") or SHARED_PROVIDER_KEY
    image_model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")
    video_api_base_url: str = os.getenv("VIDEO_API_BASE_URL", "https://api-aigc.fzyinghe.com")
    video_api_key: str = os.getenv("VIDEO_API_KEY") or SHARED_PROVIDER_KEY
    video_model: str = os.getenv("VIDEO_MODEL", "doubao-seedance-2.0")
    # 虚拟资产（真人人脸素材）注册用的分组；资产创建后返回 asset:// 链接，生成视频时
    # 传 asset:// 引用可绕过上游对真实人物的直接检测（原始 TOS 路径保留用于展示）
    # V3 素材组（POST /v3/asset-groups 创建，按 API Key 所属账户隔离）
    aigc_asset_group_id: str = os.getenv("AIGC_ASSET_GROUP_ID", "group-20260817142427-1cfe75")
    business_api_key: str = os.getenv("BUSINESS_API_KEY", "")
    business_user_id: str = os.getenv("BUSINESS_USER_ID", "")
    business_balance_url: str = os.getenv("BUSINESS_BALANCE_URL", "https://api-aigc.fzyinghe.com/business/reconcile/balance")
    business_tokens_list_url: str = os.getenv("BUSINESS_TOKENS_LIST_URL", "https://api-aigc.fzyinghe.com/business/tokens/list")
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
    # RunningHub 云端 ComfyUI 工作流（管理后台测试页用）；key 只放后端，不回显前端
    runninghub_api_key: str = os.getenv("RUNNINGHUB_API_KEY", "")
    runninghub_base_url: str = os.getenv("RUNNINGHUB_BASE_URL", "https://www.runninghub.cn/openapi/v2").rstrip("/")
    runninghub_workflow_id: str = os.getenv("RUNNINGHUB_WORKFLOW_ID", "2084514856253874178")
    runninghub_timeout: float = float(os.getenv("RUNNINGHUB_TIMEOUT", "60"))
    # Kling V3 Omni 视频模型（管理后台测试页）；默认复用英和 AIGC 网关，可用 KLING_* 覆盖
    kling_api_base_url: str = (os.getenv("KLING_API_BASE_URL") or video_api_base_url).rstrip("/")
    kling_api_key: str = os.getenv("KLING_API_KEY") or video_api_key
    kling_model: str = os.getenv("KLING_MODEL", "kling-v3-omni")
    kling_timeout: float = float(os.getenv("KLING_TIMEOUT", "60"))
    # 服务器监控：自然月仅统计默认公网出口网卡的发送字节，1 GiB = 1024^3 bytes。
    server_traffic_quota_gib: int = max(1, int(os.getenv("SERVER_TRAFFIC_QUOTA_GIB", "300")))
    server_monitor_timezone: str = os.getenv("SERVER_MONITOR_TIMEZONE", "Asia/Shanghai")
    server_metric_retention_days: int = max(7, int(os.getenv("SERVER_METRIC_RETENTION_DAYS", "35")))


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
