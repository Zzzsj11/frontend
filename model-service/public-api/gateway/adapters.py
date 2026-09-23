"""Canonical video request -> provider-specific payload. No network or MV imports."""

from fastapi import HTTPException

from .schemas import VideoCreate


def video_payload(model, req: VideoCreate):
    protocol = model.protocol
    images = req.images
    mode = req.reference_mode
    if mode == "auto":
        mode = "reference" if images or req.videos or req.audios else "text"
    if mode == "text" and (images or req.videos or req.audios):
        raise HTTPException(422, "Text mode cannot include references")
    if mode == "first_frame" and len(images) != 1:
        raise HTTPException(422, "First-frame mode requires exactly one image")
    if mode == "first_last" and len(images) != 2:
        raise HTTPException(422, "First/last mode requires exactly two images")
    if (req.videos or req.audios) and protocol not in {"h3", "wan", "dreamactor", "seedance", "toapis-video"}:
        raise HTTPException(422, "This model does not accept video/audio references through the canonical endpoint")
    duration = (
        req.duration
        if req.duration is not None
        else 8
        if model.provider_model.startswith("veo-")
        else 10
        if model.provider_model == "gemini-omni-flash-preview"
        else 5
    )
    common = {"model": model.provider_model, "duration": duration}
    if protocol == "toapis-video":
        result = {**common, "prompt": req.prompt, "resolution": req.resolution, "aspect_ratio": req.aspect_ratio}
        name = model.provider_model
        if name.startswith("gemini-"):
            result["image_urls"] = images
        else:
            result["image_with_roles"] = [
                {
                    "url": u,
                    "role": "first_frame"
                    if mode in {"first_frame", "first_last"} and i == 0
                    else "last_frame"
                    if mode == "first_last"
                    else "reference_image",
                }
                for i, u in enumerate(images)
            ]
            if name.startswith("wan"):
                result["ratio"] = result.pop("aspect_ratio")
                result["audio"] = req.generate_audio
                result["video_list"] = [{"url": u, "refer_type": "reference_video"} for u in req.videos]
            else:
                result["generate_audio"] = req.generate_audio
                result["video_with_roles"] = [{"url": u, "role": "reference_video"} for u in req.videos]
                result["audio_with_roles"] = [{"url": u, "role": "reference_audio"} for u in req.audios]
        return {k: v for k, v in result.items() if v != []}
    if protocol == "dreamactor":
        if len(images) != 1 or len(req.videos) != 1:
            raise HTTPException(422, "DreamActor requires one person image and one motion video")
        return {"model": model.provider_model, "image_urls": images, "video_url": req.videos[0], "cut_result_first_second_switch": True}
    if protocol in {"seedance", "seedance-unified", "h3"}:
        content = [{"type": "text", "text": req.prompt}]
        for i, url in enumerate(images):
            role = (
                "first_frame"
                if mode in {"first_frame", "first_last"} and i == 0
                else "last_frame"
                if mode == "first_last"
                else "reference_image"
            )
            content.append({"type": "image_url", "image_url": {"url": url}, "role": role})
        content.extend({"type": "video_url", "video_url": {"url": u}, "role": "reference_video"} for u in req.videos)
        content.extend({"type": "audio_url", "audio_url": {"url": u}, "role": "reference_audio"} for u in req.audios)
        if protocol == "h3":
            if req.resolution not in {"720p", "1080p"}:
                raise HTTPException(422, "H3 canonical resolution must be 720p (768P) or 1080p (2K)")
            return {
                **common,
                "content": content,
                "ratio": req.aspect_ratio,
                "resolution": "2K" if req.resolution == "1080p" else "768P",
                "aigc_watermark": req.watermark,
            }
        return {
            **common,
            "content": content,
            "ratio": req.aspect_ratio,
            "resolution": req.resolution,
            "generate_audio": req.generate_audio,
            "watermark": req.watermark,
            "return_last_frame": True,
        }
    if protocol == "wan":
        name = model.provider_model
        parameters = {"duration": duration, "resolution": req.resolution.upper(), "prompt_extend": False, "watermark": req.watermark}
        if name.startswith("wan2.6"):
            input_data = {"prompt": req.prompt}
            if "-i2v" in name:
                if len(images) != 1:
                    raise HTTPException(422, "Wan 2.6 i2v requires one first frame")
                input_data["img_url"] = images[0]
            else:
                parameters.pop("resolution")
                parameters["size"] = "1280*720" if req.aspect_ratio == "16:9" else "720*1280"
                if "-r2v" in name:
                    if not images and not req.videos:
                        raise HTTPException(422, "Wan reference mode requires media")
                    input_data["reference_urls"] = images + req.videos
            return {"model": name, "input": input_data, "parameters": parameters}
        media = [
            {
                "type": ("first_frame" if i == 0 else "last_frame")
                if mode == "first_last"
                else "first_frame"
                if mode == "first_frame"
                else "reference_image",
                "url": u,
            }
            for i, u in enumerate(images)
        ]
        media.extend({"type": "reference_video", "url": u} for u in req.videos)
        media.extend({"type": "reference_audio", "url": u} for u in req.audios)
        if "videoedit" in name:
            if not req.videos:
                raise HTTPException(422, "Video editing requires a source video")
            media = [{**item, "type": "video"} if item["type"] == "reference_video" else item for item in media]
            return {
                "model": name,
                "input": {"prompt": req.prompt, "media": media},
                "parameters": {"resolution": req.resolution.upper(), "prompt_extend": False},
            }
        input_data = {"prompt": req.prompt}
        if media:
            input_data["media"] = media
        return {
            "model": model.provider_model,
            "input": input_data,
            "parameters": {
                "duration": duration,
                "resolution": req.resolution.upper(),
                "ratio": req.aspect_ratio,
                "audio": req.generate_audio,
                "watermark": req.watermark,
            },
        }
    if protocol == "kling":
        if images and mode not in {"first_frame", "first_last"}:
            raise HTTPException(422, "Kling identity references are not supported; select explicit first-frame mode with a scene frame")
        result = {
            "model_name": model.provider_model,
            "prompt": req.prompt,
            "duration": duration,
            "mode": "pro" if req.resolution == "1080p" else "std",
            "sound": "on" if req.generate_audio else "off",
        }
        if images:
            result["image"] = images[0]
            if len(images) == 2:
                result["image_tail"] = images[1]
        else:
            result["aspect_ratio"] = req.aspect_ratio
        return result
    if protocol == "unified":
        if req.aspect_ratio not in {"16:9", "9:16"}:
            raise HTTPException(422, "This model requires 16:9 or 9:16")
        result = {**common, "prompt": req.prompt}
        if images:
            result["images"] = images
        if model.provider_model == "gemini-omni-flash-preview":
            if req.resolution != "720p":
                raise HTTPException(422, "Gemini Omni currently outputs 720p")
            if mode == "first_last":
                raise HTTPException(422, "Gemini Omni first/last mode is not verified")
            result["metadata"] = {
                "aspect_ratio": req.aspect_ratio,
                "task": "text_to_video" if not images else "image_to_video" if mode == "first_frame" else "reference_to_video",
            }
        else:
            if req.resolution not in {"720p", "1080p"}:
                raise HTTPException(422, "Veo canonical resolution must be 720p or 1080p")
            if mode in {"first_frame", "first_last"}:
                raise HTTPException(
                    422, "Veo canonical endpoint currently supports reference images, not explicit first/last frame control"
                )
            width, height = (1280, 720) if req.resolution == "720p" else (1920, 1080)
            if req.aspect_ratio == "9:16":
                width, height = height, width
            result.update(
                {
                    "size": f"{width}x{height}",
                    "resolution": req.resolution,
                    "metadata": {"aspectRatio": req.aspect_ratio, "resolution": req.resolution},
                }
            )
        return result
    if protocol == "grok":
        result = {
            **common,
            "prompt": req.prompt,
            "resolution": req.resolution,
            "aspect_ratio": req.aspect_ratio,
            "video_generation_mode": "text_to_video"
            if not images
            else "first_frame_image_to_video"
            if len(images) == 1
            else "reference_images_to_video",
        }
        if len(images) == 1:
            result["image"] = images[0]
        elif images:
            result["reference_images"] = images
        return result
    raise HTTPException(422, "This workflow model requires the native compatibility endpoint")
