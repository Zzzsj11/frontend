from typing import Literal

from pydantic import BaseModel, Field, StrictBool


class VideoCreate(BaseModel):
    estimate_only: StrictBool = False
    estimate_usage: dict = Field(default_factory=dict)
    model: str
    prompt: str = Field(min_length=1, max_length=20000)
    duration: int | None = Field(default=None, ge=1, le=15)
    aspect_ratio: Literal["16:9", "9:16", "4:3", "1:1"] = "16:9"
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    images: list[str] = Field(default_factory=list, max_length=15)
    videos: list[str] = Field(default_factory=list, max_length=1)
    audios: list[str] = Field(default_factory=list, max_length=3)
    reference_mode: Literal["auto", "text", "first_frame", "first_last", "reference"] = "auto"
    generate_audio: bool = False
    watermark: bool = False


class ImageCreate(BaseModel):
    estimate_only: StrictBool = False
    estimate_usage: dict = Field(default_factory=dict)
    model: str
    prompt: str = Field(min_length=1, max_length=20000)
    images: list[str] = Field(default_factory=list, max_length=15)
    size: str = "1024x1024"
    resolution: Literal["1K", "2K", "3K", "4K"] | None = None
    quality: Literal["auto", "low", "medium", "high", "xhigh", "max"] = "auto"
    n: int = Field(default=1, ge=1, le=4)
