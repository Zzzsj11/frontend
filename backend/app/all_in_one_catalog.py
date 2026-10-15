"""Only the MV-used models and explicitly requested text models."""

from __future__ import annotations

from copy import deepcopy

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
MEDIA_MODELS = (
    ("doubao-seedance-2.0", "seedance-2.0", "SD2.0", "video"),
    ("wan3.0-video", "wan3.0-video", "Wan3.0", "video"),
    ("minimax-h3", "MiniMax-H3", "H3", "video"),
)


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
    for order, (code, upstream, name, modality) in enumerate(MEDIA_MODELS):
        ratios = ["16:9", "9:16", "4:3", "1:1"]
        caps = (
            {"ratios": ratios, "imageToImage": True, "referenceImage": {"min": 0, "max": 15}}
            if modality == "image"
            else {"ratios": ratios, "durations": {"min": 4, "max": 15}, "resolutions": ["480p", "720p", "1080p"]}
        )
        caps.update(deepcopy(source_capabilities.get(code, {})))
        if code == "doubao-seedance-2.0":
            caps.update(resolutions=["480p", "720p"], referenceImage={"min": 0, "max": 9}, referenceVideo={"min": 0, "max": 3}, referenceAudio={"min": 0, "max": 3})
        elif code == "minimax-h3":
            caps.update(
                resolutions=["720p", "1080p"],
                providerResolutionMap={"720p": "768P", "1080p": "2K"},
                h3Modes=["auto", "text", "first_frame", "first_last", "reference"],
                referenceImage={"min": 0, "max": 6},
                referenceVideo={"min": 0, "max": 1},
                referenceAudio={"min": 0, "max": 3},
                referenceTotalMax=10,
                referenceAudioRequiresVisual=True,
            )
        elif code == "wan3.0-video":
            caps.update(referenceImage={"min": 0, "max": 10}, referenceVideo={"min": 0, "max": 5}, referenceAudio={"min": 0, "max": 5})
        caps.update(providerCode="all-in-one", providerProtocol="all-in-one", executionPool=f"all-in-one:{code}", executionConcurrency=500)
        # Yinghe asset:// belongs to its own account; this channel receives original TOS URLs.
        caps["billing"] = {"provider": "all-in-one", "balanceCheck": False, "billingMode": "platform_points", "currency": "points"}
        if code != "minimax-h3":
            caps.pop("providerResolutionMap", None)
        caps.pop("systemManaged", None)
        caps["sortOrder"] = 100 + order
        result.append(
            {"code": code + "-all-in-one", "provider_model_id": upstream, "name": name + "（all in one）", "modality": modality, "capabilities": caps, "sort_order": 100 + order}
        )
    return result
