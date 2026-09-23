"""Validate supported product combinations before any paid submission."""

from fastapi import HTTPException


def require(condition, message):
    if not condition:
        raise HTTPException(422, message)


def validate(model, payload):
    protocol = model.protocol
    if protocol == "image":
        n = payload.get("n", 1)
        require(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 4, "n must be 1..4")
        refs = payload.get("image", [])
        refs = [refs] if isinstance(refs, str) else refs
        require(isinstance(refs, list) and len(refs) <= 15 and all(isinstance(x, str) for x in refs), "image must contain at most 15 URLs")
        require(payload.get("quality", "auto") in {"auto", "low", "medium", "high", "xhigh", "max"}, "Unsupported image quality")
    if protocol in {"seedance", "seedance-unified", "h3"}:
        content = payload.get("content")
        require(isinstance(content, list) and bool(content), "content must be a nonempty list")
        require(all(isinstance(x, dict) for x in content), "Invalid content item")
        if protocol == "h3":
            images = sum(x.get("type") == "image_url" for x in content)
            videos = sum(x.get("type") == "video_url" for x in content)
            audios = sum(x.get("type") == "audio_url" for x in content)
            require(
                images <= 6 and videos <= 1 and audios <= 3 and images + videos + audios <= 10,
                "H3 reference limits: 6 images, 1 video, 3 audio, total 10",
            )
            require(not audios or images + videos > 0, "H3 audio requires visual reference")
            require(payload.get("resolution") in {"768P", "2K"}, "H3 resolution must be 768P or 2K")
    if protocol == "wan":
        require(isinstance(payload.get("input"), dict) and bool(payload["input"].get("prompt")), "Wan requires input.prompt")
        require(isinstance(payload.get("parameters"), dict), "Wan requires parameters")
    if protocol == "dreamactor":
        refs = payload.get("image_urls") or payload.get("binary_data_base64")
        require(isinstance(refs, list) and len(refs) == 1, "DreamActor requires exactly one person image")
        require(bool(payload.get("video_url")), "DreamActor requires motion video")
        require(not (payload.get("image_urls") and payload.get("binary_data_base64")), "Choose URL or Base64, not both")
    if protocol == "kling":
        require(payload.get("mode", "pro") in {"std", "pro", "4k"}, "Invalid Kling mode")
        require(
            not (payload.get("image") or payload.get("image_tail")) or not payload.get("aspect_ratio"),
            "Kling image mode must omit aspect_ratio",
        )
    if protocol == "unified":
        images = payload.get("images", [])
        require(isinstance(images, list) and all(isinstance(x, str) for x in images), "images must be a string array")
        require(len(images) <= model.capabilities.get("max_images", 3), "Too many reference images")
        metadata = payload.get("metadata", {})
        require(isinstance(metadata, dict), "metadata must be an object")
        if model.provider_model == "gemini-omni-flash-preview":
            task = metadata.get("task", "text_to_video" if not images else "reference_to_video")
            require(task in {"text_to_video", "image_to_video", "reference_to_video", "edit"}, "Invalid Gemini task")
            require(task != "text_to_video" or not images, "Text task must not include images")
            require(task not in {"image_to_video", "reference_to_video"} or bool(images), "Reference task requires images")
            require(task != "edit" or bool(metadata.get("previous_interaction_id")), "edit requires previous_interaction_id")
    if protocol == "runninghub":
        require(
            isinstance(payload.get("workflow"), (str, dict)) or isinstance(payload.get("nodeInfoList"), list),
            "Workflow or nodeInfoList required",
        )
