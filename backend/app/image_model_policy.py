"""Validate the image capabilities exposed by the MV model registry."""

from __future__ import annotations

import re

from fastapi import HTTPException


def image_ratio(size: str, model_code: str = "") -> str:
    if ":" in size:
        return size
    try:
        width, height = (int(part) for part in size.lower().split("x", 1))
        if width <= 0 or height <= 0:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(422, "不支持的图片尺寸") from exc
    choices = ("16:9", "9:16", "4:3", "1:1", "3:2", "2:3", "3:4", "21:9", "5:4", "4:5", "1:4", "4:1", "1:8", "8:1")
    if model_code.removesuffix("-all-in-one") == "gpt-image-2":
        from .all_in_one_catalog import GPT2_RATIOS

        choices = GPT2_RATIOS
    return min(choices, key=lambda ratio: abs(width / height - int(ratio.split(":")[0]) / int(ratio.split(":")[1])))


def validate_image_selection(
    model_code: str,
    capabilities: dict,
    *,
    size: str,
    resolution: str,
    purpose: str = "scene",
    images: list[str] | None = None,
    quality: str = "auto",
) -> None:
    if not model_code.endswith("-all-in-one"):
        return
    ratio = image_ratio(size, model_code)
    ratios = capabilities.get("ratios") or []
    resolutions = capabilities.get("resolutions") or []
    if images and capabilities.get("editResolutions"):
        resolutions = capabilities["editResolutions"]
    if ratios and ratio not in ratios:
        raise HTTPException(422, f"该图片模型不支持 {ratio} 画幅，可选：{'、'.join(ratios)}")
    if resolutions and resolution not in resolutions:
        raise HTTPException(422, f"该图片模型不支持 {resolution}，可选：{'、'.join(resolutions)}")
    if quality != "auto":
        raise HTTPException(422, "all in one 图片模型仅支持自动质量")
    references = images or []
    maximum = (capabilities.get("referenceImage") or {}).get("max")
    if isinstance(maximum, int) and len(references) > maximum:
        raise HTTPException(422, f"该图片模型最多支持 {maximum} 张参考图")
    byte_limit = (10 if model_code == "nano-banana-2.1-all-in-one" else 20) * 1024**2
    for reference in references:
        if reference.startswith("https://"):
            continue
        match = re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", reference)
        if not match:
            raise HTTPException(422, "参考图需要 HTTPS 地址或 PNG/JPEG/WebP Data URL")
        encoded = match[1]
        if len(encoded) * 3 // 4 - encoded.count("=") > byte_limit:
            raise HTTPException(422, "参考图超过模型单图大小限制")
    if sum(len(ref.encode()) for ref in references) >= 32 * 1024**2:
        raise HTTPException(422, "参考图接近请求体上限，请使用 HTTPS 地址")
    if capabilities.get("sceneOnly") and purpose != "scene":
        raise HTTPException(422, "该图片模型仅支持场景图，不支持人物身份图")
