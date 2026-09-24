"""Preserve reported usage while adding only observed token aliases; never estimate."""

from copy import deepcopy


def normalize_usage(value):
    result = deepcopy(value) if isinstance(value, dict) else {}
    raw = result.get("rawUsage")
    sources = [result] + ([raw] if isinstance(raw, dict) else [])
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }
    for target, names in aliases.items():
        # An explicit null is unknown, not permission to substitute another value.
        if target in result:
            continue
        for source in sources:
            found = next((name for name in names if name in source), None)
            if found is not None:
                result[target] = source[found]
                break
    return result
