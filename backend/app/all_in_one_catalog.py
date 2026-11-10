"""Only the MV-used models and explicitly requested text models."""

from __future__ import annotations

import json
from pathlib import Path

TEXT_MODELS = (
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
    ("gpt-6.1-sol", "GPT 6.1 Sol"),
    ("doubao-seed-2-1-pro-260915", "Doubao Seed 2.1 Pro"),
    ("gpt-6-astra", "GPT 6 Astra"),
    ("gpt-6-sol", "GPT 6.0 Sol"),
)
BASE_RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]
EXTENDED_RATIOS = [*BASE_RATIOS, "5:4", "4:5"]
GPT2_RATIOS = [*EXTENDED_RATIOS, "2:1", "1:2", "9:21"]
IMAGE_MODELS = (
    ("nano-banana-2.1", "Nano Banana 2.1", [*EXTENDED_RATIOS, "1:4", "4:1", "1:8", "8:1"], ["1K", "2K", "4K"], 14),
    ("seedream-5.0-pro", "Seedream Pro", BASE_RATIOS, ["1K", "2K"], 10),
    ("seedream-5.0-flash", "Seedream Flash", BASE_RATIOS, ["1K", "2K"], 10),
    ("gpt-image-2", "GPT Image 2", GPT2_RATIOS, ["1K", "2K", "4K"], 15),
    ("gpt-image-2.5-flare", "GPT Image 2.5 Flare", EXTENDED_RATIOS, ["1K", "2K", "4K"], 15),
    ("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst", EXTENDED_RATIOS, ["1K", "2K", "4K"], 15),
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
                "capabilities": {"systemManaged": True, "structuredOutput": False, "providerCode": "all-in-one"},
                "sort_order": 100 + order,
            }
        )
    for order, (code, name, ratios, resolutions, limit) in enumerate(IMAGE_MODELS):
        caps = {"ratios": list(ratios), "resolutions": list(resolutions), "imageToImage": True, "referenceImage": {"min": 0, "max": limit}}
        if code == "gpt-image-2":
            caps["editResolutions"] = ["1K"]
        if code in {"seedream-5.0-flash", "seedream-5.0-pro"}:
            caps["editResolutions"] = ["2K"]
        caps.update(
            systemManaged=True,
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
