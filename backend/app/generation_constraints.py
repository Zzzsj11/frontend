GENERAL_STORYBOARD_MAX_SHOTS = 30
GENERAL_STORYBOARD_MAX_GROUPS = 10
OUTLINE_STALE_SECONDS = 150
OUTLINE_WATCH_TIMEOUT_SECONDS = 300
STORYBOARD_LINE_TIMEOUT_SECONDS = 12 * 60
ALL_IN_ONE_VIDEO_JOB_TIMEOUT_SECONDS = 2 * 60 * 60


def video_job_timeout_seconds(provider: str | None, request: dict | None) -> int:
    if provider == "all-in-one" or str((request or {}).get("model") or "").endswith("-all-in-one"):
        return ALL_IN_ONE_VIDEO_JOB_TIMEOUT_SECONDS
    return 20 * 60


SHORT_LYRIC_MERGE_SECONDS = 5.0
INTERLUDE_GAP_SECONDS = 2.0
