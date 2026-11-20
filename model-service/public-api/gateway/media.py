import asyncio
import base64
import io
import json
import re
import shutil
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


async def run_media_tool(*args, timeout=60):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def collect():
        output = bytearray()
        while chunk := await proc.stdout.read(65536):
            output.extend(chunk[: max(0, 131072 - len(output))])
        if await proc.wait():
            raise ValueError("Video metadata or cover extraction failed")
        return bytes(output)

    try:
        return await asyncio.wait_for(collect(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.communicate()
        raise


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

                cover = Path(temp) / "cover.jpg"
                probe = shutil.which("ffprobe")
                if probe:
                    report = await run_media_tool(
                        probe,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=width,height,r_frame_rate,duration,codec_name:format=duration,size",
                        "-of",
                        "json",
                        str(path),
                    )
                    parsed = json.loads(report)
                    metadata = {"stream": parsed["streams"][0], "format": parsed.get("format", {})}
                output = await run_media_tool(
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-nostats",
                    "-v",
                    "error" if probe else "info",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    str(cover),
                )
                if not probe:
                    # The bundled ffmpeg also prints input metadata while extracting the cover.
                    header = output.decode("utf-8", "replace").partition("Output #")[0]
                    video = next((line for line in header.splitlines() if "Stream #" in line and "Video:" in line), "")
                    fps = re.search(r"(\d+(?:\.\d+)?) fps", video)
                    duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", header)
                    with Image.open(cover) as frame:
                        metadata = {
                            "width": frame.width,
                            "height": frame.height,
                            "fps": float(fps[1]) if fps else 0,
                            "duration": int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3]) if duration else 0,
                        }
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
