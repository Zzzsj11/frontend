"""Allowlisted, read-only task presentation; never return raw provider payloads."""

from urllib.parse import urlsplit


def media_url(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return ""


def content_view(payload, default_role="user"):
    texts, media = [], []
    text_seen, media_seen = set(), set()

    def text(value, role):
        if isinstance(value, str) and value.strip() and (role, value) not in text_seen:
            text_seen.add((role, value))
            texts.append({"role": role, "text": value})

    def asset(value, kind, role=""):
        if isinstance(value, list):
            for item in value:
                asset(item, kind, role)
            return
        if isinstance(value, dict):
            role = value.get("role") or value.get("type") or role
            value = value.get("url") or value.get("file_uri") or value.get("fileUri")
        url = media_url(value)
        if url and (kind, url, role) not in media_seen:
            media_seen.add((kind, url, role))
            media.append({"kind": kind, "url": url, "role": role})

    fields = {
        "image": "image",
        "images": "image",
        "image_url": "image",
        "image_urls": "image",
        "img_url": "image",
        "image_tail": "image",
        "reference_images": "image",
        "image_with_roles": "image",
        "video_url": "video",
        "video_urls": "video",
        "videos": "video",
        "video_list": "video",
        "video_with_roles": "video",
        "audio_url": "audio",
        "audio_urls": "audio",
        "audios": "audio",
        "audio_with_roles": "audio",
    }

    def walk(value, role="user", depth=0):
        if depth > 12:
            return
        if isinstance(value, str):
            text(value, role)
        elif isinstance(value, list):
            for item in value:
                walk(item, role, depth + 1)
        elif isinstance(value, dict):
            role = str(value.get("role") or role)
            for key in ("prompt", "text", "output_text", "negative_prompt"):
                text(value.get(key), "negative" if key == "negative_prompt" else role)
            for key, kind in fields.items():
                if key in value:
                    asset(value[key], kind, str(value.get("role") or ""))
            type_name = str(value.get("type") or "")
            if value.get("url") and any(t in type_name for t in ("image", "frame", "video", "audio")):
                asset(value, "video" if "video" in type_name else "audio" if "audio" in type_name else "image")
            for key in ("input", "messages", "message", "content", "contents", "parts", "choices", "output", "media"):
                if key in value:
                    walk(value[key], role, depth + 1)
            # Responses input_image and Gemini file references.
            if type_name == "input_image":
                asset(value.get("image_url"), "image")
            file = value.get("file_data") or value.get("fileData")
            if isinstance(file, dict):
                mime = str(file.get("mime_type") or file.get("mimeType") or "")
                asset(file, "video" if mime.startswith("video") else "audio" if mime.startswith("audio") else "image")
            # Native workflow inputs: only named prompt/media fields, never arbitrary nodes.
            for node in value.get("nodeInfoList", []) if isinstance(value.get("nodeInfoList"), list) else []:
                if not isinstance(node, dict):
                    continue
                name = str(node.get("fieldName", "")).lower()
                if name in {"prompt", "text", "positive_prompt", "negative_prompt"}:
                    text(node.get("fieldValue"), "negative" if name == "negative_prompt" else role)
                elif name in {"image", "video", "audio"}:
                    asset(node.get("fieldValue"), name)

    walk(payload, default_role)
    return {"texts": texts, "media": media}


def task_content(job):
    request = content_view(job.payload or {})
    result = job.result or {}
    output = content_view(result if job.kind in {"chat", "text"} else {}, "assistant")
    if isinstance(result, dict):
        for item in result.get("media", []):
            if not isinstance(item, dict) or not media_url(item.get("url")):
                continue
            output["media"].append(
                {
                    "kind": job.kind,
                    "url": media_url(item["url"]),
                    "thumbnail_url": media_url(item.get("thumbnail_url") or item.get("cover_url")),
                    "role": "",
                }
            )
    return {"kind": job.kind, "request_content": request, "result_content": output}
