"""ToAPIs ordinary image contracts, checked against official docs on 2026-09-22.

Pixel aliases select a documented aspect/tier, not a guarantee of output pixels.
VIP/official models have different contracts and must not reuse this adapter.
"""

from fastapi import HTTPException

# Ordinary GPT Image 2 / 2.5 documented pixel aliases, by resolution tier.
GPT_SIZES = {
    "1:1": ("1024x1024", "2048x2048", "2880x2880"),
    "3:2": ("1536x1024", "2048x1360", "3520x2336"),
    "2:3": ("1024x1536", "1360x2048", "2336x3520"),
    "4:3": ("1024x768", "2048x1536", "3312x2480"),
    "3:4": ("768x1024", "1536x2048", "2480x3312"),
    "5:4": ("1280x1024", "2560x2048", "3216x2576"),
    "4:5": ("1024x1280", "2048x2560", "2576x3216"),
    "16:9": ("1536x864", "2048x1152", "3840x2160"),
    "9:16": ("864x1536", "1152x2048", "2160x3840"),
    "2:1": ("2048x1024", "2688x1344", "3840x1920"),
    "1:2": ("1024x2048", "1344x2688", "1920x3840"),
    "21:9": ("2016x864", "2688x1152", "3840x1648"),
    "9:21": ("864x2016", "1152x2688", "1648x3840"),
}
COMMON_RATIOS = {"1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5", "16:9", "9:16", "21:9"}


def toapis_image(model, body):
    name = model.provider_model
    gpt = name in {"gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"}
    seed = name == "doubao-seedream-5-0"
    gemini = name in {"gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"}
    if not (gpt or seed or gemini):
        raise HTTPException(422, "No verified canonical image parameter contract for this route")
    if body.quality not in ({"auto", "high"} if gpt else {"auto"}):
        raise HTTPException(
            422, "This ordinary ToAPIs route does not support the requested quality; choose auto" + (" or high" if gpt else "")
        )
    ratios = set(GPT_SIZES) if gpt else COMMON_RATIOS | ({"9:21"} if seed else set())
    tiers = {"2K", "3K"} if seed else {"1K", "2K", "4K"}
    aliases = {size: (ratio, tier) for ratio, sizes in GPT_SIZES.items() for size, tier in zip(sizes, ("1K", "2K", "4K"))}
    if seed:
        aliases = {
            "2048x2048": ("1:1", "2K"),
            "2848x1600": ("16:9", "2K"),
            "1600x2848": ("9:16", "2K"),
            "3072x3072": ("1:1", "3K"),
            "4096x2304": ("16:9", "3K"),
            "2304x4096": ("9:16", "3K"),
        }
    elif gemini:
        aliases["4096x4096"] = ("1:1", "4K")
    if body.size in ratios:
        ratio, tier = body.size, body.resolution or ("2K" if seed else "1K")
    elif body.size in aliases:
        ratio, tier = aliases[body.size]
        if body.resolution and body.resolution != tier:
            raise HTTPException(422, "size and resolution specify different image tiers")
    else:
        raise HTTPException(422, "Unsupported image size; use a documented aspect ratio and explicit resolution")
    if ratio not in ratios or tier not in tiers:
        raise HTTPException(422, "Unsupported image aspect ratio or resolution for this route")
    limit = 10 if seed else 6 if gemini else 15
    if len(body.images) > limit or (seed and len(body.images) + body.n > 15):
        raise HTTPException(422, "Too many reference/output images for this route")
    result = {"prompt": body.prompt, "n": body.n, "size": ratio}
    if gpt:
        result.update(resolution=tier, reference_images=body.images)
        if name.startswith("gpt-image-2.5"):
            result["quality"] = "high"
    else:
        result["metadata"] = {"resolution": tier}
        result["image_urls"] = body.images if seed else [{"url": u} for u in body.images]
    return result
