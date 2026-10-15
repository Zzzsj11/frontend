"""Only the MV-used models and explicitly requested text models."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

TEXT_MODELS = (
    ("gpt-6.1-sol", "GPT 6.1 Sol"),
    ("doubao-seed-2-1-pro-260915", "Doubao Seed 2.1 Pro"),
    ("gpt-6-astra", "GPT 6 Astra"),
    ("gpt-6-sol", "GPT 6.0 Sol"),
)
IMAGE_MODELS = (
    (
        "nano-banana-2.1",
        "Nano Banana 2.1",
        {"ratios": ["16:9", "9:16", "4:3", "1:1", "3:2", "2:3", "3:4"], "resolutions": ["1K", "2K", "4K"], "imageToImage": True, "referenceImage": {"min": 0, "max": 14}},
    ),
    (
        "seedream-5.0-pro",
        "Seedream 5.0 Pro",
        {"ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"], "resolutions": ["1K", "1.5K", "2K"], "imageToImage": True, "referenceImage": {"min": 0, "max": 10}},
    ),
)


def video_rows() -> list[dict]:
    return json.loads((Path(__file__).parent / "data" / "all_in_one_video_models_20261015.json").read_text())


VIDEO_MODEL_CODES = frozenset(row["code"] for row in video_rows())


def rows(source_capabilities: dict[str, dict]) -> list[dict]:
    result = []
    for order, (code, name) in enumerate(TEXT_MODELS):
        result.append(
            {
                "code": code + "-all-in-one",
                "provider_model_id": code,
                "name": name + "（all in one）",
                "modality": "chat",
                "capabilities": {"structuredOutput": True, "providerCode": "all-in-one"},
                "sort_order": 100 + order,
            }
        )
    for order, (code, name, capabilities) in enumerate(IMAGE_MODELS):
        caps = deepcopy(capabilities)
        caps.update(
            providerCode="all-in-one",
            providerProtocol="all-in-one",
            executionPool=f"all-in-one:{code}",
            executionConcurrency=5 if code == "seedream-5.0-pro" else 32,
            billing={"provider": "all-in-one", "balanceCheck": False, "billingMode": "platform_points", "currency": "points"},
            sortOrder=10 + order,
        )
        result.append({"code": code + "-all-in-one", "provider_model_id": code, "name": name, "modality": "image", "capabilities": caps, "sort_order": 10 + order})
    result.extend(video_rows())
    return result
