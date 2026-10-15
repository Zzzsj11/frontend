from __future__ import annotations

MIN_VIDEO_DURATION = 4
MAX_VIDEO_DURATION = 15
DEFAULT_VIDEO_DURATION = 5


def normalize_video_duration(value: float | int | None, capabilities: dict | str | None = None) -> int:
    """Map a timeline duration to a provider-supported integer duration."""
    if value is None:
        return DEFAULT_VIDEO_DURATION
    if isinstance(capabilities, str):
        from .all_in_one_catalog import video_rows

        capabilities = next((row["capabilities"] for row in video_rows() if row["code"] == capabilities), {})
    requested = round(float(value))
    if capabilities:
        limits = capabilities.get("durations") or {}
        allowed = capabilities.get("durationOptions") or list(range(int(limits.get("min", MIN_VIDEO_DURATION)), int(limits.get("max", MAX_VIDEO_DURATION)) + 1))
        if allowed:
            return min(allowed, key=lambda item: (abs(item - requested), -item))
    return min(MAX_VIDEO_DURATION, max(MIN_VIDEO_DURATION, requested))
