"""Readable provider failures without credentials or signed URLs."""

import re

from .channels import config, unwrap


def describe(body, channel):
    data = unwrap(body) if isinstance(body, dict) else {}
    nested = data.get("error") if isinstance(data.get("error"), dict) else {}
    value = (
        data.get("failReason")
        or data.get("message")
        or data.get("msg")
        or data.get("errorMessage")
        or nested.get("message")
        or "Provider rejected the request"
    )
    text = str(value)
    try:
        key = config(channel)[1]
        if key:
            text = text.replace(key, "[redacted]")
    except ValueError:
        pass
    return re.sub(r"https?://\S+", "[URL]", text)[:1000]
