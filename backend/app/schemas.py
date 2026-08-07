from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    system_prompt: str = "你是 MV 制作助手，帮助用户规划分镜、场景、角色和视频生成提示词。"


class ChatMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ImageGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    size: str = "1024x1024"
    quality: Literal["auto", "low", "medium", "high"] = "auto"
    n: int = Field(default=1, ge=1, le=4)
    images: list[str] = Field(default_factory=list)
    model: str | None = None


class VideoGenerationCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=30_000)
    duration: int = Field(default=5, ge=2, le=15)
    ratio: Literal["16:9", "9:16", "1:1", "4:3"] = "16:9"
    image_urls: list[str] = Field(default_factory=list)
    generate_audio: bool = False
    watermark: bool = False
    model: str | None = None


class RemoteImportCreate(BaseModel):
    url: str
    category: str = "imports"
    filename: str | None = None

