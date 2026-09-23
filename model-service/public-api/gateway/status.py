"""User-facing status projection; persisted worker states remain unchanged."""


def public_status(status: str) -> str:
    return {
        "preparing": "running",
        "submitting": "running",
        "archiving": "running",
        "recoverable": "running",
        "manual_review": "failed",
    }.get(status, status)
