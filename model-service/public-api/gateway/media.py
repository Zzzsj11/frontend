import asyncio
import base64
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .channels import unwrap
from .storage import (
    download_public_url,
    download_public_url_to_path,
    get_storage,
    put_image_with_thumbnail,
    safe_key,
)


async def gemini_images(payload):
    payload = dict(payload)
    images = []
    for url in payload.get("images", []):
        if url.startswith("data:image/"):
            # Validate existing data URLs as well as downloaded originals.
            raw = base64.b64decode(url.split(",", 1)[1], validate=True)
        else:
            _, raw, _ = await download_public_url(url, max_bytes=20 * 1024 * 1024)
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError("Reference image exceeds 20 MiB")
        with Image.open(io.BytesIO(raw)) as im:
            mime = Image.MIME[im.format]
            im.verify()
        images.append(f"data:{mime};base64," + base64.b64encode(raw).decode())
    if images:
        payload["images"] = images
    return payload


def output_urls(body, kind):
    data = unwrap(body)
    if isinstance(body.get("data"), list):
        urls = [item["url"] for item in body["data"] if isinstance(item, dict) and item.get("url")]
        if urls:
            return urls
    choices = data.get("output", {}).get("choices", [])
    urls = [item["image"] for choice in choices for item in choice.get("message", {}).get("content", []) if item.get("image")]
    if urls:
        return urls
    candidates = data.get("resultUrls") or ([data["resultUrl"]] if data.get("resultUrl") else [])
    if candidates:
        return candidates
    for obj in (data, data.get("content", {}), data.get("result", {}), data.get("output", {}), data.get("task_result", {})):
        if not isinstance(obj, dict):
            continue
        for key in ("video_url", "videoUrl", "result_url", "url"):
            if isinstance(obj.get(key), str):
                return [obj[key]]
        for key in ("videos", "results", "data"):
            if obj.get(key):
                return [x["url"] if isinstance(x, dict) else x for x in obj[key]]
    raise ValueError(f"No {kind} output in successful provider response")


def replace_urls(value, replacements):
    if isinstance(value, dict):
        return {k: replace_urls(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_urls(v, replacements) for v in value]
    return replacements.get(value, value) if isinstance(value, str) else value


async def archive(job, body):
    urls = output_urls(body, job.kind)
    prefix = f"clients/{job.client_id}/users/{job.user_id}/{job.id}"
    replacements, media = {}, []
    for i, url in enumerate(urls):
        if job.kind == "image":
            _, content, content_type = await download_public_url(url, max_bytes=50 * 1024 * 1024)
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                suffix = (image.format or "png").lower()
                image.verify()
            stored, thumb = await put_image_with_thumbnail(safe_key(prefix + "/images", f"{i}.{suffix}"), content, content_type)
            media.append(
                {"url": stored, "thumbnail_url": thumb, "width": width, "height": height, "requested_size": job.payload.get("size")}
            )
        else:
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "video.mp4"
                await download_public_url_to_path(url, path)
                stored = await get_storage().put_file(safe_key(prefix + "/videos", f"{i}.mp4"), path, "video/mp4")
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    import imageio_ffmpeg

                    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

                def probe():
                    if shutil.which("ffprobe"):
                        result = subprocess.run(
                            [
                                "ffprobe",
                                "-v",
                                "error",
                                "-select_streams",
                                "v:0",
                                "-show_entries",
                                "stream=width,height,r_frame_rate,duration,codec_name:format=duration,size",
                                "-of",
                                "json",
                                str(path),
                            ],
                            capture_output=True,
                            text=True,
                            check=True,
                            timeout=60,
                        )
                        metadata = json.loads(result.stdout)
                        return {"stream": metadata.get("streams", [{}])[0], "format": metadata.get("format", {})}
                    import imageio_ffmpeg

                    reader = imageio_ffmpeg.read_frames(str(path))
                    try:
                        metadata = next(reader)
                        return {
                            "width": metadata["size"][0],
                            "height": metadata["size"][1],
                            "fps": metadata["fps"],
                            "duration": metadata["duration"],
                        }
                    finally:
                        reader.close()

                metadata = await asyncio.to_thread(probe)
                cover = Path(temp) / "cover.jpg"
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    str(cover),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await proc.communicate()
                if proc.returncode:
                    raise ValueError("Video cover extraction failed")
                cover_url, thumb = await put_image_with_thumbnail(
                    safe_key(prefix + "/covers", f"{i}.jpg"), cover.read_bytes(), "image/jpeg"
                )
            media.append(
                {
                    "url": stored,
                    "cover_url": cover_url,
                    "thumbnail_url": thumb,
                    "metadata": metadata,
                    "requested_resolution": job.payload.get("resolution", job.payload.get("parameters", {}).get("resolution")),
                }
            )
        replacements[url] = stored
    return {"media": media, "native": replace_urls(body, replacements)}
