from __future__ import annotations

MIN_VIDEO_DURATION = 4
MAX_VIDEO_DURATION = 15
DEFAULT_VIDEO_DURATION = 5


def normalize_video_duration(value: float | int | None) -> int:
    """Map a timeline duration to a provider-supported integer duration."""
    if value is None:
        return DEFAULT_VIDEO_DURATION
    return min(MAX_VIDEO_DURATION, max(MIN_VIDEO_DURATION, round(float(value))))
