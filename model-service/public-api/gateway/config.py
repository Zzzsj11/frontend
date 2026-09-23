import os
from types import SimpleNamespace

settings = SimpleNamespace(
    storage_backend="tos",
    tos_access_key=os.getenv("TOS_ACCESS_KEY", ""),
    tos_secret_key=os.getenv("TOS_SECRET_KEY", ""),
    tos_endpoint=os.getenv("TOS_ENDPOINT", "tos-cn-beijing.volces.com"),
    tos_region=os.getenv("TOS_REGION", "cn-beijing"),
    tos_public_domain=os.getenv("TOS_PUBLIC_DOMAIN", ""),
    tos_reference_bucket=os.getenv("TOS_REFERENCE_BUCKET", ""),
    tos_video_bucket=os.getenv("TOS_VIDEO_BUCKET", ""),
    tos_reference_prefix=os.getenv("TOS_REFERENCE_PREFIX", "model-service"),
    tos_video_prefix=os.getenv("TOS_VIDEO_PREFIX", "model-service"),
    tos_request_timeout_seconds=180,
    tos_socket_timeout_seconds=180,
    tos_max_retry_count=3,
    export_upload_concurrency=4,
    export_upload_part_size_mb=5,
)
