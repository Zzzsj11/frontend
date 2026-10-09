"""CPU-bounded, single-encode MV assembly; no model calls or remote FFmpeg inputs."""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path


async def process(args: list[str], folder: Path, progress=None, duration: float = 1, timeout: int = 7200) -> None:
    # stderr 落盘，避免管道堵塞；取消、超时必须结束子进程，不能留下占用 CPU 的孤儿。
    with (folder / "ffmpeg.log").open("wb") as log:
        child = await asyncio.create_subprocess_exec(*args, cwd=folder, stdout=asyncio.subprocess.PIPE, stderr=log)
        try:
            async with asyncio.timeout(timeout):
                while raw := await child.stdout.readline():
                    line = raw.decode(errors="replace").strip()
                    if progress and line.startswith("out_time_us="):
                        try:
                            seconds = float(line.split("=", 1)[1]) / 1_000_000
                        except ValueError:
                            continue
                        await progress(min(1, seconds / duration), seconds)
                if await child.wait():
                    raise ValueError("视频处理失败，请检查素材是否完整后重试")
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()


async def probe(path: Path) -> dict:
    child = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        raw, _ = await asyncio.wait_for(child.communicate(), 60)
        if child.returncode:
            raise ValueError("无法读取媒体文件，请重新上传或生成对应素材")
        return json.loads(raw)
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


def normalize_ass(raw: str, offset: float = 0) -> str:
    raw = re.sub(r"(?im)^(PlayRes[XY]:)\s*([\d,]+)", lambda m: m[1] + " " + m[2].replace(",", ""), raw)
    raw = re.sub(r"(?im)^ScaledBorderAndShadow:.*$", "ScaledBorderAndShadow: Yes", raw)
    output, fields, section = [], [], ""
    for line in raw.splitlines():
        if line.startswith("["):
            section = line.strip().lower()
        if line.lower().startswith("format:"):
            fields = [s.strip().lower() for s in line.split(":", 1)[1].split(",")]
        if line.lower().startswith("style:") and section == "[v4+ styles]":
            values = line.split(":", 1)[1].strip().split(",")
            for name, value in [("fontname", "Noto Sans CJK SC"), ("borderstyle", "1"), ("primarycolour", "&H0000FFFF"), ("secondarycolour", "&H00FFFFFF")]:
                if name in fields and len(values) == len(fields):
                    values[fields.index(name)] = value
            line = "Style: " + ",".join(values)
        if line.lower().startswith("dialogue:") and offset:
            values = line.split(":", 1)[1].strip().split(",", len(fields) - 1)
            for name in ["start", "end"]:
                if name in fields:
                    i = fields.index(name)
                    h, m, s = values[i].split(":")
                    shifted = max(0, round((int(h) * 3600 + int(m) * 60 + float(s) + offset) * 100))
                    line_time = f"{shifted // 360000}:{shifted // 6000 % 60:02d}:{shifted // 100 % 60:02d}.{shifted % 100:02d}"
                    values[i] = line_time
            line = "Dialogue: " + ",".join(values)
        output.append(line)
    if not any(line.lower().startswith("dialogue:") for line in output):
        raise ValueError("原始 ASS 没有可用字幕，无法合成")
    return "\n".join(output)


def rate(stream: dict) -> float:
    numerator, _, denominator = str(stream.get("avg_frame_rate", "30/1")).partition("/")
    value = float(numerator) / max(1, float(denominator or 1))
    return value if math.isfinite(value) and 1 <= value <= 60 else 30


async def render(folder: Path, snapshot: dict, progress) -> dict:
    audio = await probe(folder / "audio.mp3")
    if not any(s["codec_type"] == "audio" for s in audio["streams"]):
        raise ValueError("上传文件没有可用音轨")
    audio_duration = float(audio["format"]["duration"])
    offset = snapshot["audioOffset"]
    duration = audio_duration + offset
    if not 0 < duration <= 3600:
        raise ValueError("合成时长需在 1 小时以内，且音频偏移不能超出歌曲")
    (folder / "subtitles.ass").write_text(normalize_ass((folder / "source.ass").read_text(encoding="utf-8-sig"), offset), encoding="utf-8")
    clips = [v for v in snapshot["clips"] if v["start"] < duration]
    infos = []
    for i in range(len(clips)):
        info = await probe(folder / f"clip{i}.mp4")
        stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        if not stream:
            raise ValueError(f"第 {i + 1} 镜没有可用画面")
        infos.append((stream, float(stream.get("duration") or info["format"]["duration"])))
    # 保留首镜画幅，以最小源尺寸限制输出，避免混合清晰度时放大低清素材。
    first = infos[0][0]
    scale = min(1, min(min(s["width"] / first["width"], s["height"] / first["height"]) for s, _ in infos))
    width, height = max(2, int(first["width"] * scale) // 2 * 2), max(2, int(first["height"] * scale) // 2 * 2)
    fps = round(min(rate(s) for s, _ in infos), 3)
    args = ["ffmpeg", "-hide_banner", "-y", "-filter_complex_threads", "2"]
    filters = []
    for i, clip in enumerate(clips):
        end = min(duration, clips[i + 1]["start"] if i + 1 < len(clips) else duration)
        frames = round(end * fps) - round(clip["start"] * fps)
        source_duration = infos[i][1]
        if frames <= 0 or source_duration <= 0:
            raise ValueError(f"第 {i + 1} 镜时间轴无效")
        factor = max(1, frames / fps / source_duration)
        if factor > 1.5:
            raise ValueError(f"第 {i + 1} 镜视频过短，需要 {frames / fps:.1f} 秒、实际 {source_duration:.1f} 秒，请补齐后重试")
        args += ["-threads", "1", "-i", f"clip{i}.mp4"]
        filters.append(
            f"[{i}:v]setpts={factor:.10f}*(PTS-STARTPTS),fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={frames},setpts=PTS-STARTPTS[v{i}]"
        )
    args += ["-i", "audio.mp3"]
    filters.append("".join(f"[v{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0,ass=filename=subtitles.ass[out]")
    audio_filter = f"adelay={round(offset * 1000)}:all=1" if offset >= 0 else f"atrim=start={-offset},asetpts=PTS-STARTPTS"
    filters.append(f"[{len(clips)}:a]{audio_filter},apad[audio]")
    (folder / "filter.txt").write_text(";\n".join(filters))
    args += [
        "-filter_complex_script",
        "filter.txt",
        "-map",
        "[out]",
        "-map",
        "[audio]",
        "-c:v",
        "libx264",
        "-threads",
        "4",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-t",
        str(duration),
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        "final.mp4",
    ]
    await process(args, folder, progress, duration)
    return {"width": width, "height": height, "fps": fps, "duration": duration}


async def verify(folder: Path, metadata: dict, progress) -> None:
    info = await probe(folder / "final.mp4")
    if {s["codec_type"] for s in info["streams"]} != {"video", "audio"} or abs(float(info["format"]["duration"]) - metadata["duration"]) > 0.25:
        raise ValueError("成片音视频或时长校验失败，请重试")
    await process(["ffmpeg", "-v", "error", "-xerror", "-threads", "2", "-i", "final.mp4", "-progress", "pipe:1", "-f", "null", "-"], folder, progress, metadata["duration"])
    await process(["ffmpeg", "-v", "error", "-y", "-ss", str(min(5, metadata["duration"] / 2)), "-i", "final.mp4", "-frames:v", "1", "cover.jpg"], folder)
    await process(["ffmpeg", "-v", "error", "-y", "-i", "cover.jpg", "-vf", "scale=320:320:force_original_aspect_ratio=decrease", "-frames:v", "1", "thumbnail.jpg"], folder)
